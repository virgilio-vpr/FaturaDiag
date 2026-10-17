from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from app.domain.energia.diagnostico import InsumosDiagnostico, diagnosticar
from app.domain.energia.modalidade import TarifasAzul, TarifasVerde
from app.domain.energia.parametros import ParametrosRegulatorios
from app.domain.energia.tipos import Modalidade
from app.modules.diagnosticos.insumos import (
    DadosContrato,
    DadosFatura,
    InsumosInsuficientesError,
    TarifasDisponiveis,
    montar_insumos,
)
from app.modules.diagnosticos.snapshot import de_json, para_json

D = Decimal
VERDE = TarifasVerde(D("40"), D("0.90"), D("0.40"))
AZUL = TarifasAzul(D("20"), D("30"), D("0.90"), D("0.40"))


def fatura(mes: int = 1, **kw: object) -> DadosFatura:
    base: dict[str, object] = {
        "referencia": date(2026, mes, 1),
        "modalidade": "VERDE",
        "dias_faturados": 30,
        "leitura_anterior": None,
        "leitura_atual": None,
        "dc_ponta_kw": None,
        "dc_fora_ponta_kw": None,
        "dc_unica_kw": D("500"),
        "dm_ponta_kw": D("280"),
        "dm_fora_ponta_kw": D("300"),
        "consumo_ponta_kwh": D("10000"),
        "consumo_fora_ponta_kwh": D("90000"),
        "icms_aliquota": D("0.18"),
        "pis_aliquota": D("0.0165"),
        "cofins_aliquota": D("0.076"),
    }
    return DadosFatura(**{**base, **kw})  # type: ignore[arg-type]


def montar(faturas: list[DadosFatura], **kw: object):  # type: ignore[no-untyped-def]
    args: dict[str, object] = {
        "subgrupo": "A4",
        "tipo_rede": "AEREA",
        "faturas": faturas,
        "contrato": None,
        "tarifas": TarifasDisponiveis(azul=AZUL, verde=VERDE),
    }
    return montar_insumos(**{**args, **kw})  # type: ignore[arg-type]


def test_verde_mapeia_fatura_para_mes_do_motor() -> None:
    insumos, premissas = montar([fatura()])

    mes = insumos.meses[0]
    assert insumos.modalidade_atual is Modalidade.VERDE
    assert insumos.dc_unica_kw == D("500") and insumos.dc_ponta_kw is None
    assert mes.referencia == "2026-01" and mes.horas == D(720)
    assert mes.pis_cofins == D("0.0925") and mes.icms == D("0.18")
    assert premissas == ()


def test_horas_usam_datas_de_leitura_quando_faltam_dias() -> None:
    f = fatura(
        dias_faturados=None, leitura_anterior=date(2026, 1, 1), leitura_atual=date(2026, 1, 31)
    )

    insumos, _ = montar([f])

    assert insumos.meses[0].horas == D(720)


def test_azul_usa_demandas_por_posto() -> None:
    f = fatura(modalidade="AZUL", dc_unica_kw=None, dc_ponta_kw=D("200"), dc_fora_ponta_kw=D("400"))

    insumos, _ = montar([f])

    assert insumos.dc_ponta_kw == D("200") and insumos.dc_fora_ponta_kw == D("400")
    assert insumos.dc_unica_kw is None


def test_contrato_completa_demanda_ausente_na_fatura() -> None:
    contrato = DadosContrato("VERDE", None, None, D("450"))

    insumos, _ = montar([fatura(dc_unica_kw=None)], contrato=contrato)

    assert insumos.dc_unica_kw == D("450")


def test_modalidade_vem_do_contrato_quando_fatura_nao_informa() -> None:
    contrato = DadosContrato("VERDE", None, None, D("450"))

    insumos, _ = montar([fatura(modalidade=None, dc_unica_kw=None)], contrato=contrato)

    assert insumos.modalidade_atual is Modalidade.VERDE


def test_dado_ausente_nao_e_estimado() -> None:
    with pytest.raises(InsumosInsuficientesError) as erro:
        montar([fatura(consumo_ponta_kwh=None, dias_faturados=None)])

    assert "2026-01: consumo ponta ausente" in erro.value.pendencias
    assert any("dias faturados" in p for p in erro.value.pendencias)


def test_sem_faturas_ou_sem_tarifa_da_modalidade_atual() -> None:
    with pytest.raises(InsumosInsuficientesError):
        montar([])
    with pytest.raises(InsumosInsuficientesError) as erro:
        montar([fatura()], tarifas=TarifasDisponiveis(azul=AZUL, verde=None))
    assert any("Verde" in p for p in erro.value.pendencias)


def test_multa_juros_e_historico_com_demanda_variavel() -> None:
    faturas = [fatura(1, dc_unica_kw=D("400")), fatura(2, multa_juros=D("12.30"))]

    insumos, premissas = montar(faturas)

    assert [m.referencia for m in insumos.meses] == ["2026-01", "2026-02"]
    assert insumos.meses[1].multa_juros == D("12.30")
    assert insumos.dc_unica_kw == D("500")
    assert any("variou" in p for p in premissas)


def test_faturas_de_outra_modalidade_sao_excluidas_com_premissa() -> None:
    antiga = fatura(
        1, modalidade="AZUL", dc_unica_kw=None, dc_ponta_kw=D("1"), dc_fora_ponta_kw=D("1")
    )

    insumos, premissas = montar([antiga, fatura(2)])

    assert [m.referencia for m in insumos.meses] == ["2026-02"]
    assert any("2026-01" in p for p in premissas)


def test_convencional_nao_exige_dados_e_motor_sinaliza_nao_suportada(
    parametros: ParametrosRegulatorios,
) -> None:
    f = fatura(modalidade="CONVENCIONAL", dm_ponta_kw=None, dm_fora_ponta_kw=None)

    insumos, _ = montar([f])
    resultado = diagnosticar(insumos, parametros)

    assert [a.codigo.value for a in resultado.achados] == ["MODALIDADE_NAO_SUPORTADA"]


def test_snapshot_reproduz_insumos_parametros_e_resultado(
    parametros: ParametrosRegulatorios,
) -> None:
    insumos, _ = montar([fatura(m) for m in range(1, 13)])
    resultado = diagnosticar(insumos, parametros)

    insumos_ida_volta = de_json(InsumosDiagnostico, para_json(insumos))
    parametros_ida_volta = de_json(ParametrosRegulatorios, para_json(parametros))

    assert insumos_ida_volta == insumos
    assert parametros_ida_volta == parametros
    assert para_json(diagnosticar(insumos_ida_volta, parametros_ida_volta)) == para_json(resultado)


def test_para_json_rejeita_tipo_desconhecido() -> None:
    with pytest.raises(TypeError):
        para_json(object())
