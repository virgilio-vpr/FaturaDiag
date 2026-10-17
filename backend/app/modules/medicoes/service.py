from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from app.core.audit import registrar_evento_auditoria
from app.db.models import (
    ContratoDemanda,
    Distribuidora,
    FeriadoNacional,
    MedicaoIntervalo,
    UnidadeConsumidora,
)
from app.domain.energia.parametros import ParametrosRegulatorios
from app.modules.medicoes.analise import (
    ContratoAnalise,
    ParametrosAnalise,
    analisar_memoria,
)
from app.modules.medicoes.importacao import RegistroMedicao, ResultadoImportacao
from app.modules.tarifas.parametros import (
    ParametroRegulatorioNaoEncontrado,
    carregar_parametros_regulatorios,
)
from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

LOTE_INSERCAO = 500


class UnidadeMedicoesNaoEncontrada(LookupError):
    pass


class ArquivoMedicoesComErros(ValueError):
    def __init__(self, result: ResultadoImportacao) -> None:
        super().__init__("O arquivo contém medições que precisam ser corrigidas.")
        self.result = result


class PeriodoMedicoesInvalido(ValueError):
    pass


class ParametrosAnaliseIndisponiveis(LookupError):
    pass


def importar_medicoes(
    session: Session,
    *,
    organizacao_id: UUID,
    usuario_id: UUID,
    uc_id: UUID,
    resultado: ResultadoImportacao,
    ip: str | None,
) -> int:
    unidade = _obter_unidade(session, organizacao_id, uc_id)
    if resultado.erros_bloqueantes:
        raise ArquivoMedicoesComErros(resultado)
    if not resultado.registros:
        raise ArquivoMedicoesComErros(resultado)

    values = [
        {
            "id": uuid4(),
            "organizacao_id": organizacao_id,
            "uc_id": uc_id,
            "ts_inicio": record.ts_inicio,
            "intervalo_min": record.intervalo_min,
            "kwh_ativo": record.kwh_ativo,
            "kvarh_indutivo": record.kvarh_indutivo,
            "kvarh_capacitivo": record.kvarh_capacitivo,
            "fonte": resultado.perfil.fonte,
            "arquivo_id": None,
        }
        for record in resultado.registros
    ]
    affected = 0
    try:
        for start in range(0, len(values), LOTE_INSERCAO):
            batch = values[start : start + LOTE_INSERCAO]
            statement = pg_insert(MedicaoIntervalo).values(batch)
            statement = statement.on_conflict_do_update(
                index_elements=[MedicaoIntervalo.uc_id, MedicaoIntervalo.ts_inicio],
                set_={
                    "organizacao_id": statement.excluded.organizacao_id,
                    "intervalo_min": statement.excluded.intervalo_min,
                    "kwh_ativo": statement.excluded.kwh_ativo,
                    "kvarh_indutivo": statement.excluded.kvarh_indutivo,
                    "kvarh_capacitivo": statement.excluded.kvarh_capacitivo,
                    "fonte": statement.excluded.fonte,
                    "arquivo_id": statement.excluded.arquivo_id,
                    "atualizado_em": datetime.now(UTC),
                },
            )
            session.execute(statement)
            affected += len(batch)
        registrar_evento_auditoria(
            session,
            organizacao_id=organizacao_id,
            usuario_id=usuario_id,
            acao="MEMORIA_MASSA_IMPORTADA",
            entidade="medicao_intervalo",
            entidade_id=str(unidade.id),
            depois={
                "uc_id": str(unidade.id),
                "registros": len(values),
                "registros_afetados": affected,
                "fonte": resultado.perfil.fonte,
            },
            ip=ip,
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    return affected


def obter_resumo_medicoes(
    session: Session,
    *,
    organizacao_id: UUID,
    uc_id: UUID,
    inicio: date,
    fim: date,
) -> dict[str, object]:
    if inicio > fim:
        raise PeriodoMedicoesInvalido("inicio deve ser anterior ou igual a fim.")
    if (fim - inicio).days > 366:
        raise PeriodoMedicoesInvalido("O período de análise não pode exceder 366 dias.")
    if fim == date.max:
        raise PeriodoMedicoesInvalido("fim deve ser anterior a 31/12/9999.")
    unidade = _obter_unidade(session, organizacao_id, uc_id)
    distributor = session.get(Distribuidora, unidade.distribuidora_id)
    if distributor is None:
        raise UnidadeMedicoesNaoEncontrada("Unidade consumidora não encontrada.")

    start_local = datetime.combine(inicio, time.min, tzinfo=ZoneInfo("America/Sao_Paulo"))
    end_local = datetime.combine(
        fim + timedelta(days=1), time.min, tzinfo=ZoneInfo("America/Sao_Paulo")
    )
    start_datetime = start_local.astimezone(UTC)
    end_datetime = end_local.astimezone(UTC)
    rows = session.scalars(
        select(MedicaoIntervalo)
        .where(
            MedicaoIntervalo.organizacao_id == organizacao_id,
            MedicaoIntervalo.uc_id == uc_id,
            MedicaoIntervalo.ts_inicio >= start_datetime,
            MedicaoIntervalo.ts_inicio < end_datetime,
        )
        .order_by(MedicaoIntervalo.ts_inicio)
    ).all()
    if not rows:
        raise PeriodoMedicoesInvalido("Não há medições no período informado.")

    local_zone = ZoneInfo("America/Sao_Paulo")
    month_starts: set[date] = set()
    for row in rows:
        local_timestamp = row.ts_inicio.astimezone(local_zone)
        month_starts.add(date(local_timestamp.year, local_timestamp.month, 1))
    parameters: dict[date, ParametrosRegulatorios] = {}
    for month in sorted(month_starts):
        try:
            parameters[month] = carregar_parametros_regulatorios(session, data=month)
        except ParametroRegulatorioNaoEncontrado as error:
            raise ParametrosAnaliseIndisponiveis(str(error)) from error

    contracts = session.scalars(
        select(ContratoDemanda).where(
            ContratoDemanda.uc_id == uc_id,
            ContratoDemanda.vigencia_inicio <= fim,
            or_(ContratoDemanda.vigencia_fim.is_(None), ContratoDemanda.vigencia_fim > inicio),
        )
    ).all()
    holidays = frozenset(
        session.scalars(
            select(FeriadoNacional.data).where(
                FeriadoNacional.data >= inicio,
                FeriadoNacional.data <= fim,
                FeriadoNacional.vale_para_ponta.is_(True),
            )
        ).all()
    )
    analysis = analisar_memoria(
        [
            RegistroMedicao(
                ts_inicio=row.ts_inicio,
                intervalo_min=row.intervalo_min,
                kwh_ativo=row.kwh_ativo,
                kvarh_indutivo=row.kvarh_indutivo,
                kvarh_capacitivo=row.kvarh_capacitivo,
            )
            for row in rows
        ],
        fuso="America/Sao_Paulo",
        ponta_inicio=distributor.ponta_inicio,
        ponta_fim=distributor.ponta_fim,
        ponta_validada=distributor.ponta_status == "VALIDADO",
        feriados=holidays,
        parametros_por_mes={
            month: ParametrosAnalise(
                fator_potencia_referencia=values.fator_potencia_referencia,
                janela_indutiva=values.janela_indutiva,
                janela_capacitiva=values.janela_capacitiva,
                tolerancia_ultrapassagem=values.tolerancia_ultrapassagem,
            )
            for month, values in parameters.items()
        },
        contratos=tuple(
            ContratoAnalise(
                vigencia_inicio=contract.vigencia_inicio,
                vigencia_fim=contract.vigencia_fim,
                modalidade=contract.modalidade,
                dc_unica_kw=contract.demanda_unica_kw,
                dc_ponta_kw=contract.demanda_ponta_kw,
                dc_fora_ponta_kw=contract.demanda_fora_ponta_kw,
            )
            for contract in contracts
        ),
    )
    pending = sorted(
        {
            key
            for value in parameters.values()
            for key in value.pendentes_validacao
            if key
            in {
                "fator_potencia_referencia",
                "janela_indutiva",
                "janela_capacitiva",
                "tolerancia_ultrapassagem",
            }
        }
    )
    if pending:
        analysis["alertas"].append("PARAMETROS_REGULATORIOS_PENDENTES")
    sources = sorted({row.fonte for row in rows})
    result: dict[str, object] = {
        "uc_id": uc_id,
        "periodo_inicio": inicio,
        "periodo_fim": fim,
        "registros": len(rows),
        "fontes": sources,
        "ressalvas": (
            ["Referência técnica; faturamento segue a medição da distribuidora."]
            if "MEDIDOR_PARALELO" in sources
            else []
        ),
        "parametros_pendentes": pending,
        **analysis,
    }
    return result


def _obter_unidade(session: Session, organizacao_id: UUID, uc_id: UUID) -> UnidadeConsumidora:
    unidade = session.scalar(
        select(UnidadeConsumidora).where(
            UnidadeConsumidora.id == uc_id,
            UnidadeConsumidora.organizacao_id == organizacao_id,
            UnidadeConsumidora.deletado_em.is_(None),
        )
    )
    if unidade is None:
        raise UnidadeMedicoesNaoEncontrada("Unidade consumidora não encontrada.")
    return unidade
