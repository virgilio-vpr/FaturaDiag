from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from app.domain.energia.parametros import ParametrosRegulatorios

D = Decimal


@pytest.fixture
def parametros() -> ParametrosRegulatorios:
    """Parâmetros de teste alinhados aos valores iniciais da §3.5 da spec."""
    return ParametrosRegulatorios(
        tolerancia_ultrapassagem=D("0.05"),
        multiplicador_ultrapassagem=D("2"),
        fator_potencia_referencia=D("0.92"),
        intervalo_apuracao_fp_min=60,
        janela_indutiva="06:00-24:00",
        janela_capacitiva="00:00-06:00",
        demanda_minima_contratada_kw=D("30"),
        modalidades_verde_elegiveis=("A3a", "A4", "AS"),
        modalidades_azul_obrigatorias=("A1", "A2", "A3"),
        subgrupos_prioritarios=("A4", "AS"),
        carga_minima_as_kw=D("75"),
        limite_varejista_kw=D("500"),
        prazo_notificacao_migracao_acl_dias=90,
        feriados_nacionais_ponta=(),
        limiar_subutilizacao=D("0.85"),
        tolerancia_divergencia_item_rs=D("0.05"),
        distribuidoras_suportadas=(),
        vigencia_referencia=date(2026, 10, 10),
        pendentes_validacao=(),
    )
