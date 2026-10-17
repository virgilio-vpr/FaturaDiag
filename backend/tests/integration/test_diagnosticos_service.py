from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from app.db import SessionLocal
from app.db.models import (
    AuditLog,
    ContratoDemanda,
    Diagnostico,
    DiagnosticoAchado,
    Fatura,
    FaturaItem,
    Tarifa,
)
from app.domain.energia.parametros import ParametrosRegulatorios
from app.modules.diagnosticos import service
from app.modules.diagnosticos.insumos import InsumosInsuficientesError
from app.modules.diagnosticos.service import criar_diagnostico, recalcular_snapshot
from app.modules.diagnosticos.snapshot import para_json
from sqlalchemy import delete, select
from tests.support.diagnosticos import PARAMETROS, TARIFAS

D = Decimal


@pytest.fixture
def env(faturas_env, monkeypatch: pytest.MonkeyPatch) -> Iterator[object]:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(service, "carregar_parametros_regulatorios", lambda *_a, **_k: PARAMETROS)
    with SessionLocal.begin() as session:
        for modalidade, posto, componente, unidade, valor in TARIFAS:
            session.add(
                Tarifa(
                    distribuidora_id=faturas_env.distribuidora,
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
    yield faturas_env
    orgs = [faturas_env.org_a, faturas_env.org_b]
    with SessionLocal.begin() as session:
        session.execute(delete(DiagnosticoAchado).where(DiagnosticoAchado.organizacao_id.in_(orgs)))
        session.execute(delete(Diagnostico).where(Diagnostico.organizacao_id.in_(orgs)))
        session.execute(
            delete(ContratoDemanda).where(
                ContratoDemanda.uc_id.in_([faturas_env.unidade_a, faturas_env.unidade_b])
            )
        )
        session.execute(delete(Tarifa).where(Tarifa.distribuidora_id == faturas_env.distribuidora))


def _usuario(env, org: UUID) -> UUID:  # type: ignore[no-untyped-def]
    with SessionLocal() as session:
        from app.db.models import Usuario

        return session.scalars(
            select(Usuario.id).where(Usuario.organizacao_id == org, Usuario.papel == "ANALISTA")
        ).first()  # type: ignore[return-value]


def _fatura(env, mes: int, status: str = "VALIDADA", org: str = "a", **kw: object) -> UUID:  # type: ignore[no-untyped-def]
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


def test_fatura_unica_grava_snapshot_achados_e_marca_fatura(env) -> None:  # type: ignore[no-untyped-def]
    fatura_id = _fatura(env, 3)
    usuario = _usuario(env, env.org_a)

    with SessionLocal() as session:
        diag = criar_diagnostico(
            session,
            organizacao_id=env.org_a,
            usuario_id=usuario,
            uc_id=env.unidade_a,
            escopo="FATURA_UNICA",
            fatura_id=fatura_id,
        )
        assert diag.status == "RASCUNHO" and diag.escopo == "FATURA_UNICA"
        assert diag.periodo_inicio == diag.periodo_fim == date(2026, 3, 1)
        assert diag.versao_motor
        assert diag.insumos_snapshot["fontes"]["faturas"] == [str(fatura_id)]  # type: ignore[index]
        assert len(diag.insumos_snapshot["fontes"]["tarifas"]) == 11  # type: ignore[index]
        assert diag.resultado["parametros_pendentes"] == ["tolerancia_ultrapassagem"]
        achados = session.scalars(
            select(DiagnosticoAchado).where(DiagnosticoAchado.diagnostico_id == diag.id)
        ).all()
        codigos = {a.codigo for a in achados}
        assert {"DADOS_INSUFICIENTES", "DEMANDA_SUPERDIMENSIONADA"} <= codigos
        assert all(a.trace["versao_motor"] for a in achados)
        assert session.get(Fatura, fatura_id).status == "DIAGNOSTICADA"  # type: ignore[union-attr]
        acoes = session.scalars(
            select(AuditLog.acao).where(AuditLog.organizacao_id == env.org_a)
        ).all()
        assert "DIAGNOSTICO_CRIADO" in acoes and "FATURA_STATUS" in acoes


def test_historico_12_meses_e_reprodutivel_pelo_snapshot(env) -> None:  # type: ignore[no-untyped-def]
    for mes in range(1, 13):
        _fatura(env, mes)
    usuario = _usuario(env, env.org_a)

    with SessionLocal() as session:
        diag = criar_diagnostico(
            session,
            organizacao_id=env.org_a,
            usuario_id=usuario,
            uc_id=env.unidade_a,
            escopo="HISTORICO",
            periodo_inicio=date(2026, 1, 1),
            periodo_fim=date(2026, 12, 1),
        )
        codigos = {
            a.codigo
            for a in session.scalars(
                select(DiagnosticoAchado).where(DiagnosticoAchado.diagnostico_id == diag.id)
            )
        }
        assert "DADOS_INSUFICIENTES" not in codigos
        assert diag.resultado["meses"] == 12 and diag.resultado["indicativo"] is False
        assert diag.economia_anual_estimada > 0
        assert diag.economia_mensal_estimada == (diag.economia_anual_estimada / 12).quantize(
            D("0.01")
        )
        refeito = para_json(recalcular_snapshot(diag))
        gravado = {k: diag.resultado[k] for k in refeito}  # type: ignore[union-attr]
        assert refeito == gravado


def test_historico_ignora_faturas_nao_validadas_com_premissa(env) -> None:  # type: ignore[no-untyped-def]
    _fatura(env, 1)
    _fatura(env, 2, status="EM_REVISAO")
    usuario = _usuario(env, env.org_a)

    with SessionLocal() as session:
        diag = criar_diagnostico(
            session,
            organizacao_id=env.org_a,
            usuario_id=usuario,
            uc_id=env.unidade_a,
            escopo="HISTORICO",
            periodo_inicio=date(2026, 1, 1),
            periodo_fim=date(2026, 2, 1),
        )
        assert diag.resultado["meses"] == 1
        assert any("ignorada" in p for p in diag.resultado["premissas_montagem"])  # type: ignore[union-attr]


def test_fatura_nao_validada_ou_de_outro_tenant_nao_e_aceita(env) -> None:  # type: ignore[no-untyped-def]
    pendente = _fatura(env, 4, status="EM_REVISAO")
    de_b = _fatura(env, 4, org="b")
    usuario = _usuario(env, env.org_a)

    with SessionLocal() as session:
        with pytest.raises(service.FaturaNaoValidadaError):
            criar_diagnostico(
                session,
                organizacao_id=env.org_a,
                usuario_id=usuario,
                uc_id=env.unidade_a,
                escopo="FATURA_UNICA",
                fatura_id=pendente,
            )
        with pytest.raises(service.FaturaDiagnosticoNaoEncontrada):
            criar_diagnostico(
                session,
                organizacao_id=env.org_a,
                usuario_id=usuario,
                uc_id=env.unidade_a,
                escopo="FATURA_UNICA",
                fatura_id=de_b,
            )
        with pytest.raises(service.UnidadeDiagnosticoNaoEncontrada):
            criar_diagnostico(
                session,
                organizacao_id=env.org_a,
                usuario_id=usuario,
                uc_id=env.unidade_b,
                escopo="FATURA_UNICA",
                fatura_id=de_b,
            )
        assert session.scalars(select(Diagnostico)).all() == []


def test_escopos_e_insumos_invalidos(env) -> None:  # type: ignore[no-untyped-def]
    usuario = _usuario(env, env.org_a)
    base = {"organizacao_id": env.org_a, "usuario_id": usuario, "uc_id": env.unidade_a}

    with SessionLocal() as session:
        with pytest.raises(service.EscopoDiagnosticoInvalido):
            criar_diagnostico(session, escopo="FATURA_UNICA", **base)
        with pytest.raises(service.EscopoDiagnosticoInvalido):
            criar_diagnostico(session, escopo="OUTRO", **base)
        with pytest.raises(service.EscopoDiagnosticoInvalido):
            criar_diagnostico(
                session,
                escopo="HISTORICO",
                periodo_inicio=date(2020, 1, 1),
                periodo_fim=date(2026, 1, 1),
                **base,
            )
        with pytest.raises(InsumosInsuficientesError):
            criar_diagnostico(
                session,
                escopo="HISTORICO",
                periodo_inicio=date(2026, 1, 1),
                periodo_fim=date(2026, 2, 1),
                **base,
            )
    incompleta = _fatura(env, 5, consumo_ponta_kwh=None)
    with SessionLocal() as session, pytest.raises(InsumosInsuficientesError):
        criar_diagnostico(session, escopo="FATURA_UNICA", fatura_id=incompleta, **base)
    with SessionLocal() as session:
        assert session.get(Fatura, incompleta).status == "VALIDADA"  # type: ignore[union-attr]


def test_tarifa_ausente_da_modalidade_atual_bloqueia(env) -> None:  # type: ignore[no-untyped-def]
    fatura_id = _fatura(env, 6)
    with SessionLocal.begin() as session:
        session.execute(
            delete(Tarifa).where(
                Tarifa.distribuidora_id == env.distribuidora, Tarifa.modalidade == "VERDE"
            )
        )

    with SessionLocal() as session, pytest.raises(InsumosInsuficientesError) as erro:
        criar_diagnostico(
            session,
            organizacao_id=env.org_a,
            usuario_id=_usuario(env, env.org_a),
            uc_id=env.unidade_a,
            escopo="FATURA_UNICA",
            fatura_id=fatura_id,
        )
    assert any("Verde" in p for p in erro.value.pendencias)


def test_multas_dos_itens_e_idempotencia(env) -> None:  # type: ignore[no-untyped-def]
    fatura_id = _fatura(env, 7)
    with SessionLocal.begin() as session:
        session.add(
            FaturaItem(
                organizacao_id=env.org_a,
                fatura_id=fatura_id,
                ordem=1,
                descricao="Multa",
                categoria="MULTA_JUROS",
                valor=D("50.00"),
            )
        )
    args = {
        "organizacao_id": env.org_a,
        "usuario_id": _usuario(env, env.org_a),
        "uc_id": env.unidade_a,
        "escopo": "FATURA_UNICA",
        "fatura_id": fatura_id,
        "idempotency_key": "chave-1",
    }

    with SessionLocal() as session:
        primeiro = criar_diagnostico(session, **args)
        codigos = {
            a.codigo
            for a in session.scalars(
                select(DiagnosticoAchado).where(DiagnosticoAchado.diagnostico_id == primeiro.id)
            )
        }
        assert "MULTA_JUROS_ATRASO" in codigos
        segundo = criar_diagnostico(session, **args)
        assert segundo.id == primeiro.id
        assert len(session.scalars(select(Diagnostico)).all()) == 1


def test_parametros_ausentes_sao_reportados(env, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    from app.modules.tarifas.parametros import ParametroRegulatorioNaoEncontrado

    def falha(*_a: object, **_k: object) -> ParametrosRegulatorios:
        raise ParametroRegulatorioNaoEncontrado("sem parâmetros")

    monkeypatch.setattr(service, "carregar_parametros_regulatorios", falha)
    fatura_id = _fatura(env, 8)

    with SessionLocal() as session, pytest.raises(service.ParametrosDiagnosticoIndisponiveis):
        criar_diagnostico(
            session,
            organizacao_id=env.org_a,
            usuario_id=_usuario(env, env.org_a),
            uc_id=env.unidade_a,
            escopo="FATURA_UNICA",
            fatura_id=fatura_id,
        )
