from __future__ import annotations

from datetime import UTC, date, datetime, time
from decimal import Decimal

from app.modules.medicoes.analise import (
    ContratoAnalise,
    ParametrosAnalise,
    analisar_memoria,
)
from app.modules.medicoes.importacao import RegistroMedicao

D = Decimal


def _medicao(hour: int, minute: int, *, kwh: str, kvarh: str = "0") -> RegistroMedicao:
    return RegistroMedicao(
        ts_inicio=datetime(2026, 1, 5, hour, minute, tzinfo=UTC),
        intervalo_min=15,
        kwh_ativo=D(kwh),
        kvarh_indutivo=D(kvarh),
        kvarh_capacitivo=D("0"),
    )


def test_analisa_demanda_fator_de_carga_e_curva_tipica() -> None:
    resultado = analisar_memoria(
        [
            _medicao(12, 0, kwh="10"),
            _medicao(12, 15, kwh="20"),
            _medicao(12, 30, kwh="15"),
            _medicao(12, 45, kwh="15"),
        ],
        fuso="UTC",
        ponta_inicio=time(17),
        ponta_fim=time(20),
        ponta_validada=True,
        feriados=frozenset(),
        parametros_por_mes={},
        contratos=(),
    )

    assert resultado["dm_por_mes"] == [
        {"mes_referencia": date(2026, 1, 1), "posto": "FORA_PONTA", "dm_kw": D("80.000000")}
    ]
    assert resultado["fator_de_carga_por_mes"][0]["fator_de_carga"] == D("0.75")
    assert resultado["curva_tipica"][0]["tipo_dia"] == "DIA_UTIL"
    assert resultado["curva_tipica"][0]["hora"] == 12


def test_feriado_fica_fora_de_ponta_e_janela_nao_validada_nao_e_inferida() -> None:
    args = {
        "fuso": "UTC",
        "ponta_inicio": time(12),
        "ponta_fim": time(15),
        "feriados": frozenset({date(2026, 1, 5)}),
        "parametros_por_mes": {},
        "contratos": (),
    }
    holiday = analisar_memoria(
        [_medicao(12, 0, kwh="15"), _medicao(12, 15, kwh="15")],
        ponta_validada=True,
        **args,
    )
    unvalidated = analisar_memoria(
        [_medicao(12, 0, kwh="15"), _medicao(12, 15, kwh="15")],
        ponta_validada=False,
        **args,
    )

    assert holiday["dm_por_mes"][0]["posto"] == "FORA_PONTA"
    assert unvalidated["dm_por_mes"][0]["posto"] == "NAO_CLASSIFICADO"
    assert "JANELA_PONTA_NAO_VALIDADA" in unvalidated["alertas"]


def test_completude_abaixo_de_95_pct_emite_alerta() -> None:
    result = analisar_memoria(
        [
            _medicao(0, 0, kwh="1"),
            _medicao(0, 15, kwh="1"),
            _medicao(1, 0, kwh="1"),
            _medicao(1, 15, kwh="1"),
        ],
        fuso="UTC",
        ponta_inicio=None,
        ponta_fim=None,
        ponta_validada=False,
        feriados=frozenset(),
        parametros_por_mes={},
        contratos=(),
    )

    assert result["completude_pct"] == D("66.67")
    assert "DADOS_INSUFICIENTES" in result["alertas"]


def test_fp_horario_e_ere_dre_sao_simulados_sem_tarifas_ficticias() -> None:
    measurements = [
        _medicao(hour, minute, kwh="10", kvarh="10")
        for hour in (10, 11, 12, 13)
        for minute in (0, 15, 30, 45)
    ]
    parameters = ParametrosAnalise(
        fator_potencia_referencia=D("0.92"),
        janela_indutiva="06:00-24:00",
        janela_capacitiva="00:00-06:00",
        tolerancia_ultrapassagem=D("0.05"),
    )
    contract = ContratoAnalise(
        vigencia_inicio=date(2026, 1, 1),
        vigencia_fim=None,
        modalidade="VERDE",
        dc_unica_kw=D("30"),
        dc_ponta_kw=None,
        dc_fora_ponta_kw=None,
    )
    result = analisar_memoria(
        measurements,
        fuso="UTC",
        ponta_inicio=time(17),
        ponta_fim=time(20),
        ponta_validada=True,
        feriados=frozenset(),
        parametros_por_mes={date(2026, 1, 1): parameters},
        contratos=(contract,),
    )

    assert result["horas_fp_abaixo_referencia"] == 4
    assert result["reativos_por_mes"][0]["ere_kwh"] > 0
    assert result["reativos_por_mes"][0]["dre_kw"] > 0
    assert result["ultrapassagens"][0]["ultrapassagem_kw"] == D("10.000000")
    assert len(result["horas_ultrapassagem"]) == 4
