from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import TypedDict, cast
from zoneinfo import ZoneInfo

import pandas as pd
from app.domain.energia.indicadores import fator_de_carga
from app.domain.energia.reativos import fator_potencia
from app.modules.medicoes.importacao import RegistroMedicao

ZERO = Decimal(0)


@dataclass(frozen=True, slots=True)
class ParametrosAnalise:
    fator_potencia_referencia: Decimal | None
    janela_indutiva: str | None
    janela_capacitiva: str | None
    tolerancia_ultrapassagem: Decimal | None


@dataclass(frozen=True, slots=True)
class ContratoAnalise:
    vigencia_inicio: date
    vigencia_fim: date | None
    modalidade: str
    dc_unica_kw: Decimal | None
    dc_ponta_kw: Decimal | None
    dc_fora_ponta_kw: Decimal | None


class ResultadoAnalise(TypedDict):
    completude_pct: Decimal
    dm_por_mes: list[dict[str, object]]
    fator_de_carga_por_mes: list[dict[str, object]]
    fp_horario: list[dict[str, object]]
    horas_fp_abaixo_referencia: int
    reativos_por_mes: list[dict[str, object]]
    curva_tipica: list[dict[str, object]]
    ultrapassagens: list[dict[str, object]]
    horas_ultrapassagem: list[dict[str, object]]
    alertas: list[str]


def analisar_memoria(
    registros: list[RegistroMedicao] | tuple[RegistroMedicao, ...],
    *,
    fuso: str,
    ponta_inicio: time | None,
    ponta_fim: time | None,
    ponta_validada: bool,
    feriados: frozenset[date],
    parametros_por_mes: dict[date, ParametrosAnalise],
    contratos: tuple[ContratoAnalise, ...],
) -> ResultadoAnalise:
    """Gera indicadores e séries analíticas da memória de massa (§11.2)."""
    if not registros:
        raise ValueError("Informe ao menos uma medição.")
    zone = ZoneInfo(fuso)
    frame = pd.DataFrame(
        {
            "ts_utc": pd.to_datetime([item.ts_inicio for item in registros], utc=True),
            "intervalo_min": [item.intervalo_min for item in registros],
            "kwh_ativo": [float(item.kwh_ativo) for item in registros],
            "kvarh_indutivo": [
                float(item.kvarh_indutivo) if item.kvarh_indutivo is not None else float("nan")
                for item in registros
            ],
            "kvarh_capacitivo": [
                float(item.kvarh_capacitivo) if item.kvarh_capacitivo is not None else float("nan")
                for item in registros
            ],
        }
    )
    frame["ts_local"] = pd.DatetimeIndex(frame["ts_utc"]).tz_convert(zone)
    frame["kw"] = frame["kwh_ativo"] * 60 / frame["intervalo_min"]
    frame["mes_referencia"] = [
        date(timestamp.year, timestamp.month, 1) for timestamp in frame["ts_local"]
    ]
    frame["posto"] = [
        _posto(timestamp, ponta_inicio, ponta_fim, ponta_validada, feriados)
        for timestamp in frame["ts_local"]
    ]
    frame["tipo_dia"] = [
        "DIA_UTIL"
        if timestamp.weekday() < 5 and timestamp.date() not in feriados
        else "FIM_DE_SEMANA"
        for timestamp in frame["ts_local"]
    ]
    frame["hora"] = [timestamp.hour for timestamp in frame["ts_local"]]
    completeness, _gaps = _completude(registros)

    dm_por_mes: list[dict[str, object]] = []
    for (month, post), group in frame.groupby(["mes_referencia", "posto"], sort=True):
        dm_kw = float(group["kw"].max())
        dm_por_mes.append({"mes_referencia": month, "posto": post, "dm_kw": _decimal(dm_kw)})

    fator_carga: list[dict[str, object]] = []
    for month, group in frame.groupby("mes_referencia", sort=True):
        energy = _decimal(float(group["kwh_ativo"].sum()))
        max_demand = _decimal(float(group["kw"].max()))
        period_start = group["ts_local"].min()
        period_end = group["ts_local"].max()
        hours = _decimal(
            (
                period_end - period_start + pd.Timedelta(minutes=int(group["intervalo_min"].max()))
            ).total_seconds()
            / 3600
        )
        result = fator_de_carga(energy, max_demand, hours).valor
        fator_carga.append(
            {
                "mes_referencia": month,
                "energia_kwh": energy,
                "dm_max_kw": max_demand,
                "horas_observadas": hours,
                "fator_de_carga": result,
            }
        )

    frame["ts_hora"] = frame["ts_local"].dt.floor("h")
    source_rows = cast(
        list[dict[str, object]],
        frame[["ts_local", "kvarh_indutivo", "kvarh_capacitivo"]].to_dict(orient="records"),
    )
    frame["kvarh_aplicavel"] = [
        _reativo_aplicavel(
            cast(datetime, row["ts_local"]),
            float(cast(float, row["kvarh_indutivo"])),
            float(cast(float, row["kvarh_capacitivo"])),
            parametros_por_mes,
        )
        for row in source_rows
    ]
    hourly = (
        frame.groupby("ts_hora", sort=True)
        .agg(
            kwh_ativo=("kwh_ativo", "sum"),
            kvarh=("kvarh_aplicavel", lambda values: values.sum(min_count=1)),
            kw=("kwh_ativo", "sum"),
            quantidade=("intervalo_min", "size"),
            cobertura_min=("intervalo_min", "sum"),
            leituras_reativas=("kvarh_aplicavel", "count"),
        )
        .reset_index()
    )
    hourly = hourly[
        (hourly["cobertura_min"] == 60) & (hourly["leituras_reativas"] == hourly["quantidade"])
    ]

    fp_horario: list[dict[str, object]] = []
    reativos: dict[date, dict[str, object]] = {}
    hours_below_reference = 0
    hourly_rows = cast(
        list[dict[str, object]],
        hourly[["ts_hora", "kwh_ativo", "kvarh", "kw"]].to_dict(orient="records"),
    )
    for row in hourly_rows:
        timestamp = cast(pd.Timestamp, row["ts_hora"]).to_pydatetime()
        month = date(timestamp.year, timestamp.month, 1)
        params = parametros_por_mes.get(month)
        kvarh = row["kvarh"]
        if (
            params is None
            or params.fator_potencia_referencia is None
            or pd.isna(cast(float, kvarh))
        ):
            continue
        active = _decimal(float(cast(float, row["kwh_ativo"])))
        reactive = _decimal(float(cast(float, kvarh)))
        fp = fator_potencia(active, reactive)
        fp_horario.append({"ts_inicio": timestamp, "fator_potencia": fp, "mes_referencia": month})
        if fp is None:
            continue
        corrected = _decimal(float(cast(float, row["kw"]))) * params.fator_potencia_referencia / fp
        monthly = reativos.setdefault(
            month,
            {
                "mes_referencia": month,
                "ere_kwh": ZERO,
                "max_demanda_corrigida_kw": ZERO,
                "dre_kw": None,
                "premissas_paf_kw": [],
            },
        )
        monthly["max_demanda_corrigida_kw"] = max(
            _decimal_value(monthly["max_demanda_corrigida_kw"]), corrected
        )
        paf = _paf(_contract_at(contratos, timestamp.date()))
        if paf is not None:
            previous_dre = monthly["dre_kw"]
            monthly["dre_kw"] = max(
                ZERO if previous_dre is None else _decimal_value(previous_dre),
                max(ZERO, corrected - paf),
            )
            premissas = monthly["premissas_paf_kw"]
            if not isinstance(premissas, list):
                raise TypeError("A lista de premissas PAF está inválida.")
            if paf not in premissas:
                premissas.append(paf)
        if fp >= params.fator_potencia_referencia:
            continue
        hours_below_reference += 1
        ere = active * (params.fator_potencia_referencia / fp - 1)
        monthly["ere_kwh"] = _decimal_value(monthly["ere_kwh"]) + ere

    reativos_por_mes: list[dict[str, object]] = []
    for month, values in sorted(reativos.items()):
        params = parametros_por_mes.get(month)
        reativos_por_mes.append(
            {
                **values,
                "valor_monetario_calculado": False,
                "nota": "Quantidades calculadas; valores em R$ exigem tarifas vigentes resolvidas.",
                "janela_indutiva": params.janela_indutiva if params else None,
                "janela_capacitiva": params.janela_capacitiva if params else None,
            }
        )

    typical = frame.groupby(["tipo_dia", "hora"], sort=True)["kw"].mean().reset_index()
    typical_rows = cast(list[dict[str, object]], typical.to_dict(orient="records"))
    curva_tipica = [
        {
            "tipo_dia": cast(str, row["tipo_dia"]),
            "hora": int(cast(float, row["hora"])),
            "kw_medio": _decimal(float(cast(float, row["kw"]))),
        }
        for row in typical_rows
    ]
    ultrapassagens, horas_ultrapassagem = _calcular_ultrapassagens(
        frame, parametros_por_mes, contratos
    )
    alerts: list[str] = []
    if not ponta_validada or ponta_inicio is None or ponta_fim is None:
        alerts.append("JANELA_PONTA_NAO_VALIDADA")
    if not contratos:
        alerts.append("CONTRATO_DEMANDA_AUSENTE")
    if not parametros_por_mes:
        alerts.append("PARAMETROS_REGULATORIOS_INDISPONIVEIS")
    elif any(
        params.fator_potencia_referencia is None or params.tolerancia_ultrapassagem is None
        for params in parametros_por_mes.values()
    ):
        alerts.append("PARAMETROS_REGULATORIOS_INCOMPLETOS")
    if not fp_horario:
        alerts.append("FP_HORARIO_INDISPONIVEL")
    if completeness < Decimal(95):
        alerts.append("DADOS_INSUFICIENTES")

    return {
        "completude_pct": completeness,
        "dm_por_mes": dm_por_mes,
        "fator_de_carga_por_mes": fator_carga,
        "fp_horario": fp_horario,
        "horas_fp_abaixo_referencia": hours_below_reference,
        "reativos_por_mes": reativos_por_mes,
        "curva_tipica": curva_tipica,
        "ultrapassagens": ultrapassagens,
        "horas_ultrapassagem": horas_ultrapassagem,
        "alertas": alerts,
    }


def _completude(
    registros: list[RegistroMedicao] | tuple[RegistroMedicao, ...],
) -> tuple[Decimal, int]:
    ordered = sorted(registros, key=lambda item: item.ts_inicio)
    first = ordered[0].ts_inicio
    covered_until = first + timedelta(minutes=ordered[0].intervalo_min)
    covered_seconds = Decimal(ordered[0].intervalo_min * 60)
    gaps = 0
    for record in ordered[1:]:
        start = record.ts_inicio
        end = start + timedelta(minutes=record.intervalo_min)
        if start > covered_until:
            gaps += 1
            covered_until = end
            covered_seconds += Decimal(record.intervalo_min * 60)
        elif end > covered_until:
            covered_seconds += Decimal(str((end - covered_until).total_seconds()))
            covered_until = end
    period_seconds = Decimal(str((covered_until - first).total_seconds()))
    if period_seconds <= 0:
        raise ValueError("O período de medição deve ter duração positiva.")
    percentage = (covered_seconds * Decimal(100) / period_seconds).quantize(Decimal("0.01"))
    return min(percentage, Decimal(100)), gaps


def _posto(
    timestamp: datetime,
    ponta_inicio: time | None,
    ponta_fim: time | None,
    validada: bool,
    feriados: frozenset[date],
) -> str:
    if not validada or ponta_inicio is None or ponta_fim is None:
        return "NAO_CLASSIFICADO"
    if timestamp.weekday() >= 5 or timestamp.date() in feriados:
        return "FORA_PONTA"
    current = timestamp.timetz().replace(tzinfo=None)
    in_peak = (
        ponta_inicio <= current < ponta_fim
        if ponta_inicio < ponta_fim
        else current >= ponta_inicio or current < ponta_fim
    )
    return "PONTA" if in_peak else "FORA_PONTA"


def _reativo_aplicavel(
    timestamp: datetime,
    inductive: float,
    capacitive: float,
    parameters: dict[date, ParametrosAnalise],
) -> float:
    month = date(timestamp.year, timestamp.month, 1)
    params = parameters.get(month)
    if params is None:
        return float("nan")
    if _in_window(timestamp.timetz().replace(tzinfo=None), params.janela_indutiva):
        return inductive
    if _in_window(timestamp.timetz().replace(tzinfo=None), params.janela_capacitiva):
        return capacitive
    return float("nan")


def _in_window(value: time, window: str | None) -> bool:
    if window is None:
        return False
    start_text, end_text = window.split("-", maxsplit=1)
    start = _parse_time(start_text)
    end = _parse_time(end_text)
    return start <= value < end if start < end else value >= start or value < end


def _parse_time(value: str) -> time:
    return time(0) if value == "24:00" else time.fromisoformat(value)


def _contract_at(contracts: tuple[ContratoAnalise, ...], day: date) -> ContratoAnalise | None:
    return next(
        (
            contract
            for contract in contracts
            if contract.vigencia_inicio <= day
            and (contract.vigencia_fim is None or day < contract.vigencia_fim)
        ),
        None,
    )


def _paf(contract: ContratoAnalise | None) -> Decimal | None:
    if contract is None:
        return None
    if contract.modalidade == "VERDE":
        return contract.dc_unica_kw
    if contract.modalidade == "AZUL":
        demands = [
            demand
            for demand in (contract.dc_ponta_kw, contract.dc_fora_ponta_kw)
            if demand is not None
        ]
        return max(demands) if demands else None
    return None


def _calcular_ultrapassagens(
    frame: pd.DataFrame,
    parameters: dict[date, ParametrosAnalise],
    contracts: tuple[ContratoAnalise, ...],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    monthly_peaks: dict[tuple[date | datetime, str], dict[str, object]] = {}
    hourly_peaks: dict[tuple[date | datetime, str], dict[str, object]] = {}
    samples = cast(
        list[dict[str, object]],
        frame[["ts_local", "mes_referencia", "posto", "kw"]].to_dict(orient="records"),
    )
    for sample in samples:
        timestamp = cast(pd.Timestamp, sample["ts_local"]).to_pydatetime()
        month = cast(date, sample["mes_referencia"])
        contract = _contract_at(contracts, timestamp.date())
        params = parameters.get(month)
        if contract is None or params is None or params.tolerancia_ultrapassagem is None:
            continue
        if contract.modalidade == "VERDE":
            demand = contract.dc_unica_kw
            post = "UNICO"
        elif contract.modalidade == "AZUL":
            post = cast(str, sample["posto"])
            demand = (
                contract.dc_ponta_kw
                if post == "PONTA"
                else contract.dc_fora_ponta_kw
                if post == "FORA_PONTA"
                else None
            )
        else:
            continue
        if demand is None:
            continue
        measured = _decimal(float(cast(float, sample["kw"])))
        limit = demand * (1 + params.tolerancia_ultrapassagem)
        if measured <= limit:
            continue
        hourly_key = (timestamp.replace(minute=0, second=0, microsecond=0), post)
        _record_overrun(hourly_peaks, hourly_key, month, post, measured, demand, limit)
        _record_overrun(monthly_peaks, (month, post), month, post, measured, demand, limit)
    return (
        sorted(monthly_peaks.values(), key=lambda item: (item["mes_referencia"], item["posto"])),
        sorted(hourly_peaks.values(), key=lambda item: (item["ts_inicio"], item["posto"])),
    )


def _record_overrun(
    peaks: dict[tuple[date | datetime, str], dict[str, object]],
    key: tuple[date | datetime, str],
    month: date,
    post: str,
    measured: Decimal,
    demand: Decimal,
    limit: Decimal,
) -> None:
    amount = measured - demand
    current = peaks.get(key)
    if current is not None and _decimal_value(current["ultrapassagem_kw"]) >= amount:
        return
    peak: dict[str, object] = {
        "mes_referencia": month,
        "posto": post,
        "dm_kw": measured,
        "dc_kw": demand,
        "limite_kw": limit,
        "ultrapassagem_kw": amount,
    }
    if isinstance(key[0], datetime):
        peak["ts_inicio"] = key[0]
    peaks[key] = peak


def _decimal(value: float) -> Decimal:
    return Decimal(str(round(value, 6)))


def _decimal_value(value: object) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError("A agregação esperava um valor Decimal.")
    return value
