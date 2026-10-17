from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from app.core.settings import Settings
from app.db import SessionLocal
from app.db.models import (
    Arquivo,
    AuditLog,
    AuthSession,
    Cliente,
    Distribuidora,
    Extracao,
    Fatura,
    FaturaItem,
    MedicaoIntervalo,
    Organizacao,
    UnidadeConsumidora,
    Usuario,
)
from app.integrations.llm.base import LLMError, LLMPermanentError
from app.integrations.llm.extrator import Alvo, ExtratorLLM
from app.integrations.llm.fake import FakeProvider
from app.integrations.storage import LocalStorage
from app.main import app
from app.modules.auth.security import create_token
from app.modules.faturas import pipeline, revisao
from app.modules.faturas.router import get_extrator, get_storage
from sqlalchemy import delete


@dataclass
class FaturasEnv:
    org_a: UUID
    org_b: UUID
    unidade_a: UUID
    unidade_b: UUID
    distribuidora: UUID
    headers: dict[str, dict[str, str]]
    storage: LocalStorage
    llm: dict[str, dict[str, Any] | LLMError]


@pytest.fixture
def faturas_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[FaturasEnv]:
    parametros = SimpleNamespace(tolerancia_divergencia_item_rs=Decimal("0.05"))
    for modulo in (pipeline, revisao):
        monkeypatch.setattr(
            modulo, "carregar_parametros_regulatorios", lambda *_a, **_k: parametros
        )
    org_a, org_b, distribuidora = uuid4(), uuid4(), uuid4()
    cliente_a, cliente_b = uuid4(), uuid4()
    unidade_a, unidade_b = uuid4(), uuid4()
    roles = {
        "analista_a": (org_a, "ANALISTA"),
        "cliente_a": (org_a, "CLIENTE"),
        "analista_b": (org_b, "ANALISTA"),
    }
    users = {name: uuid4() for name in roles}
    sessions = {name: uuid4() for name in roles}
    with SessionLocal.begin() as session:
        session.add_all(
            [Organizacao(id=org_a, nome=f"FA {org_a}"), Organizacao(id=org_b, nome=f"FB {org_b}")]
        )
        session.flush()
        session.add_all(
            [
                Usuario(
                    id=users[name],
                    organizacao_id=org,
                    email=f"{users[name].hex}@example.com",
                    nome=name,
                    senha_hash="unused",
                    papel=papel,
                )
                for name, (org, papel) in roles.items()
            ]
            + [
                Distribuidora(
                    id=distribuidora,
                    sigla=f"FAT_{distribuidora.hex[:8]}",
                    nome="Distribuidora de teste",
                    ufs=["SP"],
                ),
                Cliente(id=cliente_a, organizacao_id=org_a, razao_social="Cliente A"),
                Cliente(id=cliente_b, organizacao_id=org_b, razao_social="Cliente B"),
            ]
        )
        session.flush()
        for uid, org, cid in ((unidade_a, org_a, cliente_a), (unidade_b, org_b, cliente_b)):
            session.add(
                UnidadeConsumidora(
                    id=uid,
                    organizacao_id=org,
                    cliente_id=cid,
                    distribuidora_id=distribuidora,
                    codigo_uc=f"UC-{uid.hex[:10]}",
                    uf="SP",
                    municipio="Campinas",
                    subgrupo="A4",
                    tipo_rede="AEREA",
                    ambiente="CATIVO",
                )
            )
        session.add_all(
            [
                AuthSession(
                    id=sessions[name],
                    usuario_id=users[name],
                    expira_em=datetime.now(UTC) + timedelta(days=1),
                )
                for name in roles
            ]
        )
    settings = Settings()
    headers = {
        name: {
            "Authorization": "Bearer "
            + create_token(
                user_id=users[name],
                session_id=sessions[name],
                version=0,
                token_type="access",
                settings=settings,
            )
        }
        for name in roles
    }
    storage = LocalStorage(tmp_path)
    llm: dict[str, dict[str, Any] | LLMError] = {"resposta": LLMPermanentError("sem resposta")}
    extrator = ExtratorLLM(Alvo(FakeProvider(lambda _texto: llm["resposta"]), "fake-model"))
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[get_extrator] = lambda: extrator
    yield FaturasEnv(org_a, org_b, unidade_a, unidade_b, distribuidora, headers, storage, llm)
    app.dependency_overrides.pop(get_storage, None)
    app.dependency_overrides.pop(get_extrator, None)

    orgs = [org_a, org_b]
    with SessionLocal.begin() as session:
        for model in (
            Extracao,
            FaturaItem,
            Fatura,
            Arquivo,
            MedicaoIntervalo,
            AuditLog,
            UnidadeConsumidora,
            Cliente,
        ):
            session.execute(delete(model).where(model.organizacao_id.in_(orgs)))
        session.execute(delete(AuthSession).where(AuthSession.id.in_(list(sessions.values()))))
        session.execute(delete(Usuario).where(Usuario.id.in_(list(users.values()))))
        session.execute(delete(Distribuidora).where(Distribuidora.id == distribuidora))
        session.execute(delete(Organizacao).where(Organizacao.id.in_(orgs)))
