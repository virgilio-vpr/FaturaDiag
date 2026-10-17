from __future__ import annotations

from collections.abc import AsyncIterator
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from app.db import SessionLocal
from app.db.models import MedicaoIntervalo
from app.main import app
from app.modules.medicoes import service as medicoes_service
from httpx import ASGITransport
from sqlalchemy import select


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as test_client:
        yield test_client


def _csv_file() -> tuple[str, bytes, str]:
    contents = (
        "Data/Hora;Energia Ativa (kWh);Reativo Indutivo (kvarh);"
        "Reativo Capacitivo (kvarh)\n"
        "05/01/2026 00:00;10;0;0\n"
        "05/01/2026 00:15;10;0;0\n"
        "05/01/2026 00:30;10;0;0\n"
        "05/01/2026 00:45;10;0;0\n"
    )
    return "medicoes.csv", contents.encode(), "text/csv"


@pytest.mark.anyio
async def test_upload_em_lote_e_idempotente_por_uc_e_horario(
    client: httpx.AsyncClient, faturas_env
) -> None:  # type: ignore[no-untyped-def]
    filename, content, mime = _csv_file()
    url = f"/api/v1/unidades/{faturas_env.unidade_a}/medicoes"
    headers = faturas_env.headers["analista_a"]

    first = await client.post(url, headers=headers, files={"arquivo": (filename, content, mime)})
    second = await client.post(url, headers=headers, files={"arquivo": (filename, content, mime)})

    assert first.status_code == 201
    assert first.json()["registros"] == 4
    assert first.json()["registros_afetados"] == 4
    assert first.json()["completude_pct"] == "100.00"
    assert second.status_code == 201
    assert second.json()["registros_afetados"] == 4
    with SessionLocal() as session:
        stored = session.scalars(
            select(MedicaoIntervalo).where(
                MedicaoIntervalo.organizacao_id == faturas_env.org_a,
                MedicaoIntervalo.uc_id == faturas_env.unidade_a,
            )
        ).all()
    assert len(stored) == 4


@pytest.mark.anyio
async def test_importacao_nao_permite_acessar_uc_de_outro_tenant(
    client: httpx.AsyncClient, faturas_env
) -> None:  # type: ignore[no-untyped-def]
    filename, content, mime = _csv_file()
    response = await client.post(
        f"/api/v1/unidades/{faturas_env.unidade_b}/medicoes",
        headers=faturas_env.headers["analista_a"],
        files={"arquivo": (filename, content, mime)},
    )

    assert response.status_code == 404


@pytest.mark.anyio
async def test_cliente_nao_pode_importar_ou_consultar_memoria_de_massa(
    client: httpx.AsyncClient, faturas_env
) -> None:  # type: ignore[no-untyped-def]
    filename, content, mime = _csv_file()
    headers = faturas_env.headers["cliente_a"]
    upload = await client.post(
        f"/api/v1/unidades/{faturas_env.unidade_a}/medicoes",
        headers=headers,
        files={"arquivo": (filename, content, mime)},
    )
    summary = await client.get(
        f"/api/v1/unidades/{faturas_env.unidade_a}/medicoes/resumo",
        headers=headers,
        params={"inicio": "2026-01-05", "fim": "2026-01-05"},
    )

    assert upload.status_code == 403
    assert summary.status_code == 403


@pytest.mark.anyio
async def test_upload_rejeita_colunas_nao_mapeadas_sem_persistir(
    client: httpx.AsyncClient, faturas_env
) -> None:  # type: ignore[no-untyped-def]
    response = await client.post(
        f"/api/v1/unidades/{faturas_env.unidade_a}/medicoes",
        headers=faturas_env.headers["analista_a"],
        files={"arquivo": ("unknown.csv", b"Data local,Carga X\n01/01/2026,1\n", "text/csv")},
    )

    assert response.status_code == 422
    assert response.json()["errors"][0]["message"] == "Data local, Carga X"
    with SessionLocal() as session:
        count = session.scalar(
            select(MedicaoIntervalo.id).where(MedicaoIntervalo.uc_id == faturas_env.unidade_a)
        )
    assert count is None


@pytest.mark.anyio
async def test_resumo_expõe_series_e_alertas_sem_vazar_outra_uc(
    client: httpx.AsyncClient,
    faturas_env,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # type: ignore[no-untyped-def]
    filename, content, mime = _csv_file()
    await client.post(
        f"/api/v1/unidades/{faturas_env.unidade_a}/medicoes",
        headers=faturas_env.headers["analista_a"],
        files={"arquivo": (filename, content, mime)},
    )
    monkeypatch.setattr(
        medicoes_service,
        "carregar_parametros_regulatorios",
        lambda *_args, **_kwargs: SimpleNamespace(
            fator_potencia_referencia=Decimal("0.92"),
            janela_indutiva="06:00-24:00",
            janela_capacitiva="00:00-06:00",
            tolerancia_ultrapassagem=Decimal("0.05"),
            pendentes_validacao=(),
        ),
    )
    summary = await client.get(
        f"/api/v1/unidades/{faturas_env.unidade_a}/medicoes/resumo",
        headers=faturas_env.headers["analista_a"],
        params={"inicio": "2026-01-05", "fim": "2026-01-05"},
    )
    other_tenant = await client.get(
        f"/api/v1/unidades/{faturas_env.unidade_b}/medicoes/resumo",
        headers=faturas_env.headers["analista_a"],
        params={"inicio": "2026-01-05", "fim": "2026-01-05"},
    )

    assert summary.status_code == 200
    assert summary.json()["registros"] == 4
    assert summary.json()["fator_de_carga_por_mes"][0]["fator_de_carga"] == "1"
    assert "JANELA_PONTA_NAO_VALIDADA" in summary.json()["alertas"]
    assert other_tenant.status_code == 404
