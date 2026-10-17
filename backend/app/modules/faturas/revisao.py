from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.core.audit import registrar_evento_auditoria
from app.db.models import Distribuidora, Fatura, FaturaItem, UnidadeConsumidora
from app.integrations.llm.hints import HINT_GENERICO
from app.modules.faturas import estados
from app.modules.faturas.estados import TransicaoInvalidaError
from app.modules.faturas.normalizacao import (
    ALIQUOTA_PARA_CAMPO_PCT,
    COLUNA_PARA_CAMPO,
    extraida_revisada,
)
from app.modules.faturas.pipeline import existe_fatura_duplicada
from app.modules.faturas.validacoes import (
    Alerta,
    ContextoValidacao,
    Severidade,
    tem_bloqueante,
    validar_extracao,
)
from app.modules.tarifas.parametros import carregar_parametros_regulatorios
from app.modules.unidades.service import obter_unidade
from sqlalchemy import select
from sqlalchemy.orm import Session

COLUNAS_VALORES = (*COLUNA_PARA_CAMPO, *ALIQUOTA_PARA_CAMPO_PCT)
COLUNAS_ITEM = (
    "descricao",
    "categoria",
    "posto",
    "unidade",
    "quantidade",
    "tarifa_unitaria",
    "valor",
)


class FaturaNaoEncontradaError(LookupError):
    pass


class FaturaDuplicadaError(Exception):
    pass


class FaturaComBloqueantesError(Exception):
    def __init__(self, alertas: list[Alerta]) -> None:
        super().__init__("A fatura possui alertas bloqueantes.")
        self.alertas = alertas


def obter_fatura(session: Session, organizacao_id: UUID, fatura_id: UUID) -> Fatura:
    fatura = session.scalar(
        select(Fatura).where(Fatura.id == fatura_id, Fatura.organizacao_id == organizacao_id)
    )
    if fatura is None:
        raise FaturaNaoEncontradaError("Fatura não encontrada.")
    return fatura


def listar_faturas(
    session: Session,
    organizacao_id: UUID,
    *,
    status: str | None,
    uc_id: UUID | None,
    limite: int,
    deslocamento: int,
) -> list[Fatura]:
    consulta = select(Fatura).where(Fatura.organizacao_id == organizacao_id)
    if status:
        consulta = consulta.where(Fatura.status == status)
    if uc_id:
        consulta = consulta.where(Fatura.uc_id == uc_id)
    consulta = (
        consulta.order_by(Fatura.criado_em.desc(), Fatura.id).limit(limite).offset(deslocamento)
    )
    return list(session.scalars(consulta))


def listar_itens(session: Session, fatura: Fatura) -> list[FaturaItem]:
    return list(
        session.scalars(
            select(FaturaItem)
            .where(
                FaturaItem.fatura_id == fatura.id,
                FaturaItem.organizacao_id == fatura.organizacao_id,
            )
            .order_by(FaturaItem.ordem)
        )
    )


def _revalidar(session: Session, fatura: Fatura, itens: list[dict[str, Any]]) -> list[Alerta]:
    valores = {nome: getattr(fatura, nome) for nome in COLUNAS_VALORES}
    extraida = extraida_revisada(fatura.dados_extraidos, valores, itens)
    parametros = carregar_parametros_regulatorios(
        session, data=fatura.mes_referencia or datetime.now(UTC).date()
    )
    uc = session.get(UnidadeConsumidora, fatura.uc_id) if fatura.uc_id else None
    detectada = (
        session.get(Distribuidora, fatura.distribuidora_detectada_id)
        if fatura.distribuidora_detectada_id is not None
        else None
    )
    sigla = detectada.sigla if detectada is not None else None
    contexto = ContextoValidacao(
        tolerancia_divergencia_rs=parametros.tolerancia_divergencia_item_rs,
        uc_codigo=uc.codigo_uc if uc is not None else None,
        distribuidora_sigla=sigla,
        hint_especifico=fatura.hint_usado not in (None, HINT_GENERICO),
        fatura_duplicada=existe_fatura_duplicada(
            session, fatura, fatura.mes_referencia, fatura.uc_id
        ),
    )
    return validar_extracao(extraida, contexto)


def _itens_como_dict(itens: list[FaturaItem]) -> list[dict[str, Any]]:
    return [{nome: getattr(item, nome) for nome in COLUNAS_ITEM} for item in itens]


def atualizar_dados(
    session: Session,
    *,
    organizacao_id: UUID,
    usuario_id: UUID,
    fatura_id: UUID,
    valores: dict[str, Any],
    itens: list[dict[str, Any]] | None,
    ip: str | None,
) -> Fatura:
    fatura = obter_fatura(session, organizacao_id, fatura_id)
    if fatura.status not in estados.EDITAVEIS:
        raise TransicaoInvalidaError(fatura.status, estados.EM_REVISAO)
    antes = {nome: str(getattr(fatura, nome)) for nome in valores if hasattr(fatura, nome)}

    if "uc_id" in valores and valores["uc_id"] is not None:
        obter_unidade(session, organizacao_id=organizacao_id, unidade_id=valores["uc_id"])
    mes = valores.get("mes_referencia", fatura.mes_referencia)
    if mes is not None:
        mes = mes.replace(day=1)
        valores = {**valores, "mes_referencia": mes}
    uc_id = valores.get("uc_id", fatura.uc_id)
    if existe_fatura_duplicada(session, fatura, mes, uc_id):
        raise FaturaDuplicadaError("Já existe fatura desta UC para o mês informado.")

    for nome, valor in valores.items():
        setattr(fatura, nome, valor)
    if itens is not None:
        session.query(FaturaItem).filter(FaturaItem.fatura_id == fatura.id).delete()
        for ordem, item in enumerate(itens, start=1):
            session.add(
                FaturaItem(organizacao_id=organizacao_id, fatura_id=fatura.id, ordem=ordem, **item)
            )
        session.flush()
    fatura.alertas = [
        a.como_dict()
        for a in _revalidar(session, fatura, _itens_como_dict(listar_itens(session, fatura)))
    ]
    registrar_evento_auditoria(
        session,
        organizacao_id=organizacao_id,
        usuario_id=usuario_id,
        acao="FATURA_DADOS_EDITADOS",
        entidade="fatura",
        entidade_id=str(fatura.id),
        antes=antes,
        depois={nome: str(valor) for nome, valor in valores.items()} | {"itens": itens is not None},
        ip=ip,
    )
    if fatura.status != estados.EM_REVISAO:
        estados.transicionar(session, fatura, estados.EM_REVISAO, usuario_id=usuario_id, ip=ip)
    session.commit()
    return fatura


def validar_fatura(
    session: Session, *, organizacao_id: UUID, usuario_id: UUID, fatura_id: UUID, ip: str | None
) -> Fatura:
    fatura = obter_fatura(session, organizacao_id, fatura_id)
    if estados.VALIDADA not in estados.TRANSICOES.get(fatura.status, frozenset()):
        raise TransicaoInvalidaError(fatura.status, estados.VALIDADA)
    alertas = _revalidar(session, fatura, _itens_como_dict(listar_itens(session, fatura)))
    fatura.alertas = [a.como_dict() for a in alertas]
    if tem_bloqueante(alertas):
        session.commit()
        raise FaturaComBloqueantesError(
            [a for a in alertas if a.severidade is Severidade.BLOQUEANTE]
        )
    fatura.validada_por = usuario_id
    fatura.validada_em = datetime.now(UTC)
    estados.transicionar(session, fatura, estados.VALIDADA, usuario_id=usuario_id, ip=ip)
    session.commit()
    return fatura


def preparar_reextracao(
    session: Session, *, organizacao_id: UUID, usuario_id: UUID, fatura_id: UUID, ip: str | None
) -> Fatura:
    fatura = obter_fatura(session, organizacao_id, fatura_id)
    estados.transicionar(
        session, fatura, estados.EXTRAINDO, usuario_id=usuario_id, ip=ip, motivo="reextracao"
    )
    session.commit()
    return fatura


__all__ = [
    "FaturaComBloqueantesError",
    "FaturaDuplicadaError",
    "FaturaNaoEncontradaError",
    "TransicaoInvalidaError",
    "atualizar_dados",
    "listar_faturas",
    "obter_fatura",
    "preparar_reextracao",
    "validar_fatura",
]
