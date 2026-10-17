from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import date
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from app.core.audit import registrar_evento_auditoria
from app.db.models import (
    ContratoDemanda,
    Diagnostico,
    DiagnosticoAchado,
    Fatura,
    FaturaItem,
    Tarifa,
    UnidadeConsumidora,
)
from app.domain.energia.acl import CenarioPreco, EntradaACL
from app.domain.energia.diagnostico import (
    InsumosDiagnostico,
    ResultadoDiagnostico,
    diagnosticar,
)
from app.domain.energia.modalidade import TarifasAzul, TarifasVerde
from app.domain.energia.parametros import ParametrosRegulatorios
from app.domain.energia.tipos import Modalidade, arredondar_moeda
from app.modules.diagnosticos.insumos import (
    DadosContrato,
    DadosFatura,
    InsumosInsuficientesError,
    TarifasDisponiveis,
    montar_insumos,
)
from app.modules.diagnosticos.snapshot import de_json, para_json
from app.modules.faturas import estados
from app.modules.tarifas.parametros import (
    ParametroRegulatorioNaoEncontrado,
    carregar_parametros_regulatorios,
)
from app.modules.tarifas.resolver import (
    TarifaAmbiguaError,
    TarifaNaoEncontrada,
    resolver_tarifa,
)
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

ESCOPO_FATURA_UNICA = "FATURA_UNICA"
ESCOPO_HISTORICO = "HISTORICO"
STATUS_RASCUNHO = "RASCUNHO"
STATUS_FATURA_APTA = (estados.VALIDADA, estados.DIAGNOSTICADA)
MESES_MAXIMOS_HISTORICO = 36
MWH_PARA_KWH = Decimal(1000)


class UnidadeDiagnosticoNaoEncontrada(LookupError):
    pass


class FaturaDiagnosticoNaoEncontrada(LookupError):
    pass


class FaturaNaoValidadaError(ValueError):
    pass


class EscopoDiagnosticoInvalido(ValueError):
    pass


class ParametrosDiagnosticoIndisponiveis(LookupError):
    pass


class TarifasDiagnosticoInvalidas(ValueError):
    pass


def criar_diagnostico(
    session: Session,
    *,
    organizacao_id: UUID,
    usuario_id: UUID,
    uc_id: UUID,
    escopo: str,
    fatura_id: UUID | None = None,
    periodo_inicio: date | None = None,
    periodo_fim: date | None = None,
    idempotency_key: str | None = None,
    acl: EntradaACL | None = None,
    cenarios_acl: tuple[CenarioPreco, ...] = (),
    ip: str | None = None,
) -> Diagnostico:
    """Monta insumos → motor → grava snapshot e achados (§4.3, P5, P6)."""
    if idempotency_key is not None:
        existente = _por_idempotencia(session, organizacao_id, idempotency_key)
        if existente is not None:
            return existente

    unidade = _obter_unidade(session, organizacao_id, uc_id)
    faturas, premissas = _selecionar_faturas(
        session, organizacao_id, uc_id, escopo, fatura_id, periodo_inicio, periodo_fim
    )
    referencias = sorted(_referencia(f) for f in faturas)
    ultima = referencias[-1]
    parametros = carregar_parametros(session, ultima)
    contrato = _contrato_vigente(session, uc_id, ultima)
    tarifas, fontes_tarifas = _resolver_tarifas(
        session,
        unidade,
        parametros,
        faturas[-1].modalidade or _modalidade_contrato(contrato),
        ultima,
    )
    insumos, premissas_montagem = montar_insumos(
        subgrupo=unidade.subgrupo,
        tipo_rede=unidade.tipo_rede,
        faturas=[_dados_fatura(session, f) for f in faturas],
        contrato=_dados_contrato(contrato),
        tarifas=tarifas,
    )
    if acl is not None and cenarios_acl:
        insumos = _com_acl(insumos, acl, cenarios_acl)
    premissas_montagem = (
        *premissas,
        *premissas_montagem,
        f"Tarifas vigentes em {ultima.isoformat()} aplicadas a todo o período",
    )

    resultado = diagnosticar(insumos, parametros)
    diagnostico = _persistir(
        session,
        organizacao_id=organizacao_id,
        usuario_id=usuario_id,
        uc_id=uc_id,
        escopo=escopo,
        referencias=referencias,
        faturas=faturas,
        idempotency_key=idempotency_key,
        insumos=insumos,
        parametros=parametros,
        resultado=resultado,
        premissas_montagem=premissas_montagem,
        fontes_tarifas=fontes_tarifas,
        contrato=contrato,
    )
    try:
        for fatura in faturas:
            if fatura.status == estados.VALIDADA:
                estados.transicionar(
                    session, fatura, estados.DIAGNOSTICADA, usuario_id=usuario_id, ip=ip
                )
        registrar_evento_auditoria(
            session,
            organizacao_id=organizacao_id,
            usuario_id=usuario_id,
            acao="DIAGNOSTICO_CRIADO",
            entidade="diagnostico",
            entidade_id=str(diagnostico.id),
            depois={
                "uc_id": str(uc_id),
                "escopo": escopo,
                "versao_motor": resultado.versao_motor,
                "achados": len(resultado.achados),
            },
            ip=ip,
        )
        session.commit()
    except IntegrityError:
        session.rollback()
        if idempotency_key is not None:
            existente = _por_idempotencia(session, organizacao_id, idempotency_key)
            if existente is not None:
                return existente
        raise
    except Exception:
        session.rollback()
        raise
    return diagnostico


def recalcular_snapshot(diagnostico: Diagnostico) -> ResultadoDiagnostico:
    """Reexecuta o motor sobre o snapshot gravado; deve reproduzir `resultado` (P6)."""
    insumos = de_json(InsumosDiagnostico, diagnostico.insumos_snapshot["insumos"])
    parametros = de_json(ParametrosRegulatorios, diagnostico.parametros_snapshot)
    return diagnosticar(insumos, parametros)


def _por_idempotencia(session: Session, organizacao_id: UUID, chave: str) -> Diagnostico | None:
    return session.scalar(
        select(Diagnostico).where(
            Diagnostico.organizacao_id == organizacao_id, Diagnostico.idempotency_key == chave
        )
    )


def _obter_unidade(session: Session, organizacao_id: UUID, uc_id: UUID) -> UnidadeConsumidora:
    unidade = session.scalar(
        select(UnidadeConsumidora).where(
            UnidadeConsumidora.id == uc_id,
            UnidadeConsumidora.organizacao_id == organizacao_id,
            UnidadeConsumidora.deletado_em.is_(None),
        )
    )
    if unidade is None:
        raise UnidadeDiagnosticoNaoEncontrada("Unidade consumidora não encontrada.")
    return unidade


def _referencia(fatura: Fatura) -> date:
    assert fatura.mes_referencia is not None
    return fatura.mes_referencia


def _selecionar_faturas(
    session: Session,
    organizacao_id: UUID,
    uc_id: UUID,
    escopo: str,
    fatura_id: UUID | None,
    inicio: date | None,
    fim: date | None,
) -> tuple[list[Fatura], tuple[str, ...]]:
    base = select(Fatura).where(Fatura.organizacao_id == organizacao_id, Fatura.uc_id == uc_id)
    if escopo == ESCOPO_FATURA_UNICA:
        if fatura_id is None:
            raise EscopoDiagnosticoInvalido("FATURA_UNICA exige fatura_id.")
        fatura = session.scalar(base.where(Fatura.id == fatura_id))
        if fatura is None:
            raise FaturaDiagnosticoNaoEncontrada("Fatura não encontrada.")
        if fatura.status not in STATUS_FATURA_APTA or fatura.mes_referencia is None:
            raise FaturaNaoValidadaError("Somente faturas VALIDADAS alimentam o diagnóstico.")
        return [fatura], ()
    if escopo != ESCOPO_HISTORICO:
        raise EscopoDiagnosticoInvalido("Escopo de diagnóstico inválido.")
    if inicio is None or fim is None or inicio > fim:
        raise EscopoDiagnosticoInvalido("HISTORICO exige periodo_inicio <= periodo_fim.")
    meses = (fim.year - inicio.year) * 12 + fim.month - inicio.month + 1
    if meses > MESES_MAXIMOS_HISTORICO:
        raise EscopoDiagnosticoInvalido(
            f"O período não pode exceder {MESES_MAXIMOS_HISTORICO} meses."
        )
    no_periodo = list(
        session.scalars(
            base.where(Fatura.mes_referencia >= inicio, Fatura.mes_referencia <= fim).order_by(
                Fatura.mes_referencia
            )
        )
    )
    aptas = [f for f in no_periodo if f.status in STATUS_FATURA_APTA]
    if not aptas:
        raise InsumosInsuficientesError(["Nenhuma fatura validada no período"])
    ignoradas = len(no_periodo) - len(aptas)
    premissas = (
        (f"{ignoradas} fatura(s) do período não validada(s) foram ignoradas",) if ignoradas else ()
    )
    return aptas, premissas


def carregar_parametros(session: Session, referencia: date) -> ParametrosRegulatorios:
    try:
        return carregar_parametros_regulatorios(session, data=referencia, usar_cache=False)
    except ParametroRegulatorioNaoEncontrado as erro:
        raise ParametrosDiagnosticoIndisponiveis(str(erro)) from erro


def _contrato_vigente(session: Session, uc_id: UUID, data: date) -> ContratoDemanda | None:
    return session.scalar(
        select(ContratoDemanda)
        .where(
            ContratoDemanda.uc_id == uc_id,
            ContratoDemanda.vigencia_inicio <= data,
            or_(ContratoDemanda.vigencia_fim.is_(None), ContratoDemanda.vigencia_fim > data),
        )
        .order_by(ContratoDemanda.vigencia_inicio.desc())
        .limit(1)
    )


def _modalidade_contrato(contrato: ContratoDemanda | None) -> str | None:
    return contrato.modalidade if contrato else None


def _dados_contrato(contrato: ContratoDemanda | None) -> DadosContrato | None:
    if contrato is None:
        return None
    return DadosContrato(
        modalidade=contrato.modalidade,
        dc_ponta_kw=contrato.demanda_ponta_kw,
        dc_fora_ponta_kw=contrato.demanda_fora_ponta_kw,
        dc_unica_kw=contrato.demanda_unica_kw,
    )


def _dados_fatura(session: Session, fatura: Fatura) -> DadosFatura:
    multas = session.scalars(
        select(FaturaItem.valor).where(
            FaturaItem.organizacao_id == fatura.organizacao_id,
            FaturaItem.fatura_id == fatura.id,
            FaturaItem.categoria == "MULTA_JUROS",
        )
    ).all()
    return DadosFatura(
        referencia=_referencia(fatura),
        modalidade=fatura.modalidade,
        dias_faturados=fatura.dias_faturados,
        leitura_anterior=fatura.leitura_anterior,
        leitura_atual=fatura.leitura_atual,
        dc_ponta_kw=fatura.dc_ponta_kw,
        dc_fora_ponta_kw=fatura.dc_fora_ponta_kw,
        dc_unica_kw=fatura.dc_unica_kw,
        dm_ponta_kw=fatura.dm_ponta_kw,
        dm_fora_ponta_kw=fatura.dm_fora_ponta_kw,
        consumo_ponta_kwh=fatura.consumo_ponta_kwh,
        consumo_fora_ponta_kwh=fatura.consumo_fora_ponta_kwh,
        icms_aliquota=fatura.icms_aliquota,
        pis_aliquota=fatura.pis_aliquota,
        cofins_aliquota=fatura.cofins_aliquota,
        multa_juros=sum((abs(v) for v in multas), Decimal(0)),
    )


def _resolver_tarifas(
    session: Session,
    unidade: UnidadeConsumidora,
    parametros: ParametrosRegulatorios,
    modalidade_atual: str | None,
    data: date,
) -> tuple[TarifasDisponiveis, list[dict[str, Any]]]:
    usadas: list[Tarifa] = []

    def tarifa(modalidade: str, posto: str, componente: str) -> Tarifa:
        registro = resolver_tarifa(
            session,
            distribuidora_id=unidade.distribuidora_id,
            subgrupo=unidade.subgrupo,
            modalidade=modalidade,
            posto=posto,
            componente=componente,
            data=data,
        )
        usadas.append(registro)
        return registro

    def energia(modalidade: str, posto: str) -> Decimal:
        consumo = tarifa(modalidade, posto, "TUSD_CONSUMO")
        te = tarifa(modalidade, posto, "TE_CONSUMO")
        for registro in (consumo, te):
            if registro.unidade != "RS_MWH":
                raise TarifasDiagnosticoInvalidas("Unidade de tarifa de energia inesperada.")
        return (consumo.valor + te.valor) / MWH_PARA_KWH

    def azul() -> TarifasAzul:
        return TarifasAzul(
            demanda_ponta_rs_kw=tarifa("AZUL", "PONTA", "TUSD_DEMANDA").valor,
            demanda_fora_ponta_rs_kw=tarifa("AZUL", "FORA_PONTA", "TUSD_DEMANDA").valor,
            energia_ponta_rs_kwh=energia("AZUL", "PONTA"),
            energia_fora_ponta_rs_kwh=energia("AZUL", "FORA_PONTA"),
        )

    def verde() -> TarifasVerde:
        return TarifasVerde(
            demanda_rs_kw=tarifa("VERDE", "UNICO", "TUSD_DEMANDA").valor,
            energia_ponta_rs_kwh=energia("VERDE", "PONTA"),
            energia_fora_ponta_rs_kwh=energia("VERDE", "FORA_PONTA"),
        )

    resolvidas: dict[str, Any] = {}
    candidatas: dict[str, Callable[[], Any]] = {"azul": azul}
    if unidade.subgrupo in parametros.modalidades_verde_elegiveis or (
        modalidade_atual == Modalidade.VERDE.value
    ):
        candidatas["verde"] = verde
    for nome, construir in candidatas.items():
        try:
            resolvidas[nome] = construir()
        except TarifaNaoEncontrada:
            resolvidas[nome] = None
        except TarifaAmbiguaError as erro:
            raise TarifasDiagnosticoInvalidas(str(erro)) from erro
    fontes = [
        {
            "id": str(t.id),
            "modalidade": t.modalidade,
            "posto": t.posto,
            "componente": t.componente,
            "unidade": t.unidade,
            "valor": str(t.valor),
            "vigencia_inicio": t.vigencia_inicio.isoformat(),
            "resolucao_homologatoria": t.resolucao_homologatoria,
        }
        for t in usadas
    ]
    return TarifasDisponiveis(azul=resolvidas.get("azul"), verde=resolvidas.get("verde")), fontes


def _com_acl(
    insumos: InsumosDiagnostico, acl: EntradaACL, cenarios: tuple[CenarioPreco, ...]
) -> InsumosDiagnostico:
    return replace(insumos, acl=acl, cenarios_acl=cenarios)


def _persistir(
    session: Session,
    *,
    organizacao_id: UUID,
    usuario_id: UUID,
    uc_id: UUID,
    escopo: str,
    referencias: list[date],
    faturas: list[Fatura],
    idempotency_key: str | None,
    insumos: InsumosDiagnostico,
    parametros: ParametrosRegulatorios,
    resultado: ResultadoDiagnostico,
    premissas_montagem: tuple[str, ...],
    fontes_tarifas: list[dict[str, Any]],
    contrato: ContratoDemanda | None,
) -> Diagnostico:
    anual = resultado.economia_anual_estimada
    diagnostico = Diagnostico(
        organizacao_id=organizacao_id,
        uc_id=uc_id,
        idempotency_key=idempotency_key,
        escopo=escopo,
        periodo_inicio=referencias[0],
        periodo_fim=referencias[-1],
        status=STATUS_RASCUNHO,
        versao_motor=resultado.versao_motor,
        insumos_snapshot={
            "insumos": para_json(insumos),
            "premissas_montagem": list(premissas_montagem),
            "fontes": {
                "faturas": [str(f.id) for f in faturas],
                "contrato_id": str(contrato.id) if contrato else None,
                "tarifas": fontes_tarifas,
            },
        },
        parametros_snapshot=cast(dict[str, Any], para_json(parametros)),
        resultado={
            **cast(dict[str, Any], para_json(resultado)),
            "premissas_montagem": list(premissas_montagem),
            "parametros_pendentes": list(parametros.pendentes_validacao),
        },
        economia_mensal_estimada=arredondar_moeda(anual / Decimal(12)),
        economia_anual_estimada=anual,
        criado_por=usuario_id,
    )
    session.add(diagnostico)
    session.flush()
    for ordem, achado in enumerate(resultado.achados):
        session.add(
            DiagnosticoAchado(
                organizacao_id=organizacao_id,
                diagnostico_id=diagnostico.id,
                ordem=ordem,
                codigo=achado.codigo.value,
                severidade=achado.severidade.value,
                titulo=achado.titulo,
                descricao=achado.descricao,
                economia_anual=achado.economia_anual_estimada,
                recomendacao=achado.recomendacao,
                evidencias=list(achado.evidencias),
                premissas=list(achado.premissas),
                trace=achado.trace.para_dict(),
            )
        )
    return diagnostico
