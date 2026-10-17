from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

import structlog
from app.core.settings import Settings
from app.db.models import (
    Arquivo,
    Distribuidora,
    Extracao,
    Fatura,
    FaturaItem,
    UnidadeConsumidora,
)
from app.integrations.llm.base import LLMError, LLMOrcamentoExcedido
from app.integrations.llm.extrator import ExtratorLLM
from app.integrations.llm.montagem import PROMPT_VERSAO
from app.integrations.storage import StorageBackend
from app.modules.faturas import estados
from app.modules.faturas.extracao import (
    HintResolver,
    HintResolvido,
    ResultadoExtracao,
    executar_extracao,
    resolver_hint_arquivo,
)
from app.modules.faturas.normalizacao import confianca_minima, normalizar_para_fatura
from app.modules.faturas.validacoes import Alerta, Severidade
from app.modules.tarifas.hints import resolver_hint
from app.modules.tarifas.parametros import carregar_parametros_regulatorios
from sqlalchemy import func, select
from sqlalchemy.orm import Session

logger = structlog.get_logger(__name__)


def gasto_mensal_organizacao(session: Session, organizacao_id: UUID) -> Decimal:
    agora = datetime.now(UTC)
    inicio = agora.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    total = session.scalar(
        select(func.coalesce(func.sum(Extracao.custo_estimado), 0)).where(
            Extracao.organizacao_id == organizacao_id, Extracao.criado_em >= inicio
        )
    )
    return Decimal(total or 0)


def existe_fatura_duplicada(
    session: Session, fatura: Fatura, mes: date | None, uc_id: UUID | None
) -> bool:
    if mes is None or uc_id is None:
        return False
    return (
        session.scalar(
            select(func.count())
            .select_from(Fatura)
            .where(
                Fatura.organizacao_id == fatura.organizacao_id,
                Fatura.uc_id == uc_id,
                Fatura.mes_referencia == mes,
                Fatura.id != fatura.id,
            )
        )
        or 0
    ) > 0


def distribuidora_por_sigla(session: Session, sigla: str | None) -> Distribuidora | None:
    if not sigla:
        return None
    return session.scalar(
        select(Distribuidora).where(func.lower(Distribuidora.sigla) == sigla.lower())
    )


def _resolvedor_hint(session: Session, hoje: date) -> HintResolver:
    def resolver(sigla: str | None) -> HintResolvido:
        distribuidora = distribuidora_por_sigla(session, sigla)
        if sigla and distribuidora is not None:
            try:
                versionado = resolver_hint(session, distribuidora_id=distribuidora.id, data=hoje)
            except LookupError:
                versionado = None
            if versionado is not None:
                return HintResolvido(
                    f"{sigla.lower()}@{versionado.versao}", versionado.arquivo_md, True
                )
        return resolver_hint_arquivo(sigla)

    return resolver


def _mensagem_falha(erro: Exception) -> str:
    if isinstance(erro, LLMOrcamentoExcedido):
        return "Orçamento mensal de LLM esgotado; preencha os dados manualmente ou aguarde."
    if isinstance(erro, LLMError):
        return "O provedor de LLM não conseguiu extrair a fatura; revise manualmente."
    return "Falha ao processar o arquivo da fatura; revise manualmente."


def _registrar_falha(
    session: Session, fatura: Fatura, erro: Exception, usuario_id: UUID | None
) -> None:
    alerta = Alerta("FALHA_EXTRACAO", Severidade.BLOQUEANTE, _mensagem_falha(erro))
    fatura.alertas = [alerta.como_dict()]
    estados.transicionar(
        session, fatura, estados.FALHA_EXTRACAO, usuario_id=usuario_id, motivo=type(erro).__name__
    )
    session.commit()


def processar_extracao(
    session: Session,
    storage: StorageBackend,
    extrator: ExtratorLLM,
    settings: Settings,
    *,
    fatura_id: UUID,
    organizacao_id: UUID,
    usuario_id: UUID | None,
) -> None:
    """Job de extração (E1–E5): ENVIADA/EXTRAINDO → EXTRAIDA ou FALHA_EXTRACAO."""
    fatura = session.scalar(
        select(Fatura).where(Fatura.id == fatura_id, Fatura.organizacao_id == organizacao_id)
    )
    if fatura is None or fatura.arquivo_id is None:
        return
    if fatura.status == estados.ENVIADA:
        estados.transicionar(session, fatura, estados.EXTRAINDO, usuario_id=usuario_id)
        session.commit()
    if fatura.status != estados.EXTRAINDO:
        return

    try:
        resultado = _extrair(session, storage, extrator, settings, fatura)
    except Exception as erro:
        logger.exception("extracao_falhou", fatura_id=str(fatura.id))
        session.rollback()
        fatura = session.get(Fatura, fatura_id)
        if fatura is not None:
            _registrar_falha(session, fatura, erro, usuario_id)
        return

    _persistir(session, fatura, resultado, usuario_id)
    session.commit()
    logger.info("fatura_extraida", fatura_id=str(fatura.id), origem=resultado.origem.value)


def _extrair(
    session: Session,
    storage: StorageBackend,
    extrator: ExtratorLLM,
    settings: Settings,
    fatura: Fatura,
) -> ResultadoExtracao:
    arquivo = session.get(Arquivo, fatura.arquivo_id)
    if arquivo is None:
        raise FileNotFoundError("Arquivo da fatura ausente.")
    conteudo = storage.get(arquivo.storage_key)
    hoje = datetime.now(UTC).date()
    parametros = carregar_parametros_regulatorios(session, data=hoje)
    uc = session.get(UnidadeConsumidora, fatura.uc_id) if fatura.uc_id else None
    return executar_extracao(
        extrator,
        conteudo=conteudo,
        mime=arquivo.mime,
        sha256=arquivo.sha256,
        tolerancia_divergencia_rs=parametros.tolerancia_divergencia_item_rs,
        uc_codigo=uc.codigo_uc if uc is not None else None,
        resolver_hint=_resolvedor_hint(session, hoje),
        gasto_mensal_brl=gasto_mensal_organizacao(session, fatura.organizacao_id),
        orcamento_mensal_brl=settings.llm_monthly_budget_brl,
    )


def _persistir(
    session: Session, fatura: Fatura, resultado: ResultadoExtracao, usuario_id: UUID | None
) -> None:
    extraida = resultado.extraida
    uso = resultado.resultado.usage
    session.add(
        Extracao(
            organizacao_id=fatura.organizacao_id,
            fatura_id=fatura.id,
            provider=resultado.provider,
            modelo=resultado.resultado.modelo,
            prompt_versao=PROMPT_VERSAO,
            hint_usado=resultado.hint_usado,
            metodo=resultado.metodo,
            tokens_entrada=0 if resultado.cache_hit else uso.tokens_entrada,
            tokens_saida=0 if resultado.cache_hit else uso.tokens_saida,
            custo_estimado=Decimal(0)
            if resultado.cache_hit
            else Decimal(str(uso.custo_estimado or 0)),
            latencia_ms=uso.latencia_ms,
            resultado=extraida.model_dump(mode="json"),
            validacoes=[a.como_dict() for a in resultado.alertas],
        )
    )
    valores = dict(normalizar_para_fatura(extraida).valores)
    mes = valores["mes_referencia"]
    alertas = list(resultado.alertas)
    if existe_fatura_duplicada(session, fatura, mes, fatura.uc_id):
        # uq_fatura_uc_mes: a fatura fica sem mês até o analista resolver o conflito.
        valores["mes_referencia"] = None
        if not any(a.codigo == "DUPLICADA" for a in alertas):
            alertas.append(
                Alerta("DUPLICADA", Severidade.BLOQUEANTE, "Já existe fatura desta UC para o mês.")
            )
    for nome, valor in valores.items():
        setattr(fatura, nome, valor)
    fatura.origem = resultado.origem.value
    fatura.dados_extraidos = extraida.model_dump(mode="json")
    fatura.alertas = [a.como_dict() for a in alertas]
    fatura.confianca_minima = confianca_minima(extraida)
    fatura.hint_usado = resultado.hint_usado
    distribuidora = distribuidora_por_sigla(session, resultado.distribuidora_sigla)
    fatura.distribuidora_detectada_id = distribuidora.id if distribuidora is not None else None

    session.query(FaturaItem).filter(FaturaItem.fatura_id == fatura.id).delete()
    for ordem, item in enumerate(extraida.itens, start=1):
        session.add(
            FaturaItem(
                organizacao_id=fatura.organizacao_id,
                fatura_id=fatura.id,
                ordem=ordem,
                descricao=item.descricao[:255],
                categoria=item.categoria.value,
                posto=item.posto,
                unidade=item.unidade,
                quantidade=item.quantidade,
                tarifa_unitaria=item.tarifa_unitaria,
                valor=item.valor,
            )
        )
    estados.transicionar(session, fatura, estados.EXTRAIDA, usuario_id=usuario_id)
