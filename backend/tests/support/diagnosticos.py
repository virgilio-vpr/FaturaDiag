from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

from app.db import SessionLocal
from app.db.models import Fatura, Tarifa, Usuario
from app.domain.energia.parametros import ParametrosRegulatorios
from sqlalchemy import select

D = Decimal

PARAMETROS = ParametrosRegulatorios(
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
    vigencia_referencia=date(2026, 1, 1),
    pendentes_validacao=("tolerancia_ultrapassagem",),
)

TARIFAS = [
    ("VERDE", "UNICO", "TUSD_DEMANDA", "RS_KW", "40"),
    ("VERDE", "PONTA", "TUSD_CONSUMO", "RS_MWH", "100"),
    ("VERDE", "PONTA", "TE_CONSUMO", "RS_MWH", "800"),
    ("VERDE", "FORA_PONTA", "TUSD_CONSUMO", "RS_MWH", "100"),
    ("VERDE", "FORA_PONTA", "TE_CONSUMO", "RS_MWH", "300"),
    ("AZUL", "PONTA", "TUSD_DEMANDA", "RS_KW", "60"),
    ("AZUL", "FORA_PONTA", "TUSD_DEMANDA", "RS_KW", "20"),
    ("AZUL", "PONTA", "TUSD_CONSUMO", "RS_MWH", "100"),
    ("AZUL", "PONTA", "TE_CONSUMO", "RS_MWH", "800"),
    ("AZUL", "FORA_PONTA", "TUSD_CONSUMO", "RS_MWH", "100"),
    ("AZUL", "FORA_PONTA", "TE_CONSUMO", "RS_MWH", "300"),
]


def semear_tarifas(distribuidora: UUID) -> None:
    with SessionLocal.begin() as session:
        for modalidade, posto, componente, unidade, valor in TARIFAS:
            session.add(
                Tarifa(
                    distribuidora_id=distribuidora,
                    subgrupo="A4",
                    modalidade=modalidade,
                    posto=posto,
                    componente=componente,
                    unidade=unidade,
                    valor=D(valor),
                    vigencia_inicio=date(2025, 1, 1),
                    fonte="teste sintético",
                )
            )


def usuario_id(org: UUID) -> UUID:
    with SessionLocal() as session:
        return session.scalars(  # type: ignore[return-value]
            select(Usuario.id).where(Usuario.organizacao_id == org, Usuario.papel == "ANALISTA")
        ).first()


def criar_fatura(env, mes: int, status: str = "VALIDADA", org: str = "a", **kw: object) -> UUID:  # type: ignore[no-untyped-def]
    org_id = env.org_a if org == "a" else env.org_b
    uc = env.unidade_a if org == "a" else env.unidade_b
    dados: dict[str, object] = {
        "modalidade": "VERDE",
        "dias_faturados": 30,
        "dc_unica_kw": D("500"),
        "dm_ponta_kw": D("280"),
        "dm_fora_ponta_kw": D("300"),
        "consumo_ponta_kwh": D("10000"),
        "consumo_fora_ponta_kwh": D("90000"),
        "icms_aliquota": D("0.18"),
        "pis_aliquota": D("0.0165"),
        "cofins_aliquota": D("0.076"),
    }
    fatura_id = uuid4()
    with SessionLocal.begin() as session:
        session.add(
            Fatura(
                id=fatura_id,
                organizacao_id=org_id,
                uc_id=uc,
                status=status,
                mes_referencia=date(2026, mes, 1),
                **{**dados, **kw},
            )
        )
    return fatura_id
