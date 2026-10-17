from __future__ import annotations

import io
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from app.modules.medicoes.importacao import (
    ErroImportacaoMedicao,
    PerfilImportacao,
    parsear_memoria,
)
from openpyxl import Workbook


def test_detecta_cabecalho_e_interpreta_decimal_com_virgula() -> None:
    parsed = parsear_memoria(
        b"Data/Hora;Energia Ativa (kWh);Reativo Indutivo (kvarh)\n"
        b"01/02/2026 00:00;1,25;0,10\n"
        b"01/02/2026 00:15;1,50;0,20\n"
    )

    assert parsed.perfil.intervalo_min == 15
    assert parsed.registros[0].ts_inicio == datetime(2026, 2, 1, 3, tzinfo=UTC)
    assert parsed.registros[0].kwh_ativo == Decimal("1.25")
    assert parsed.registros[0].kvarh_indutivo == Decimal("0.10")
    assert parsed.completude_pct == Decimal("100")
    assert parsed.lacunas == 0


def test_perfil_converte_kw_medio_em_kwh_por_intervalo() -> None:
    perfil = PerfilImportacao(
        colunas={"ts": "timestamp", "kw": "potencia"},
        unidade="KW_MEDIO",
        intervalo_min=15,
        formato_data_hora="%Y-%m-%d %H:%M",
    )
    parsed = parsear_memoria(
        b"timestamp,potencia\n2026-01-01 00:00,12\n",
        perfil=perfil,
    )

    assert parsed.registros[0].kwh_ativo == Decimal("3")


def test_cabecalho_sem_mapeamento_retorna_colunas_encontradas() -> None:
    with pytest.raises(ErroImportacaoMedicao) as exc:
        parsear_memoria(b"Data da coleta,Carga X\n2026-01-01 00:00,1\n")

    assert exc.value.colunas_encontradas == ("Data da coleta", "Carga X")


def test_duplicatas_e_valores_negativos_sao_bloqueantes() -> None:
    parsed = parsear_memoria(
        b"timestamp,kwh_ativo\n2026-01-01 00:00,1\n2026-01-01 00:00,2\n2026-01-01 00:15,-1\n"
    )

    assert parsed.duplicatas == 1
    assert parsed.valores_negativos == 1
    assert parsed.erros_bloqueantes
    assert len(parsed.registros) == 1


def test_lacunas_calculam_completude_e_alerta_abaixo_de_95_pct() -> None:
    parsed = parsear_memoria(
        b"timestamp,kwh_ativo\n"
        b"2026-01-01 00:00,1\n"
        b"2026-01-01 00:15,1\n"
        b"2026-01-01 01:00,1\n"
        b"2026-01-01 01:15,1\n"
    )

    assert parsed.lacunas == 2
    assert parsed.completude_pct == Decimal("66.67")
    assert "DADOS_INSUFICIENTES" in parsed.alertas


def test_intervalos_irregulares_sao_bloqueantes() -> None:
    parsed = parsear_memoria(
        b"timestamp,kwh_ativo\n2026-01-01 00:00,1\n2026-01-01 00:15,1\n2026-01-01 00:35,1\n"
    )

    assert parsed.intervalos_irregulares == 1
    assert "INTERVALO_IRREGULAR" in parsed.erros_bloqueantes


def test_arquivo_vazio_e_perfil_invalido_sao_rejeitados() -> None:
    with pytest.raises(ErroImportacaoMedicao):
        parsear_memoria(b"")
    with pytest.raises(ValueError):
        PerfilImportacao(intervalo_min=10)


def test_le_planilha_xlsx_com_celulas_de_data_e_numero() -> None:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.append(["timestamp", "kwh_ativo"])
    sheet.append([datetime(2026, 1, 1, 0, 0), 10])
    sheet.append([datetime(2026, 1, 1, 0, 15), 12])
    stream = io.BytesIO()
    workbook.save(stream)

    parsed = parsear_memoria(stream.getvalue())

    assert parsed.perfil.intervalo_min == 15
    assert parsed.registros[0].kwh_ativo == Decimal("10")
