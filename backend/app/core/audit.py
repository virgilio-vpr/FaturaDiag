from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AuditLog, Usuario

REDACTED = "[REDACTED]"
_SENSITIVE_KEY_MARKERS = ("senha", "password", "secret", "token", "apikey", "authorization")


class AuditEventError(ValueError):
    pass


def registrar_evento_auditoria(
    session: Session,
    *,
    organizacao_id: UUID,
    usuario_id: UUID | None,
    acao: str,
    entidade: str,
    entidade_id: str | None = None,
    antes: Mapping[str, object] | None = None,
    depois: Mapping[str, object] | None = None,
    ip: str | None = None,
) -> AuditLog:
    action = acao.strip()
    entity = entidade.strip()
    if not action or len(action) > 255:
        raise AuditEventError("acao deve conter de 1 a 255 caracteres.")
    if not entity or len(entity) > 120:
        raise AuditEventError("entidade deve conter de 1 a 120 caracteres.")
    if entidade_id is not None and len(entidade_id) > 64:
        raise AuditEventError("entidade_id deve conter no máximo 64 caracteres.")
    if ip is not None and len(ip) > 45:
        raise AuditEventError("ip deve conter no máximo 45 caracteres.")

    if usuario_id is not None:
        actor_organization_id = session.scalar(
            select(Usuario.organizacao_id).where(Usuario.id == usuario_id)
        )
        if actor_organization_id != organizacao_id:
            raise AuditEventError("usuario_id deve pertencer à organizacao_id informada.")

    event = AuditLog(
        organizacao_id=organizacao_id,
        usuario_id=usuario_id,
        acao=action,
        entidade=entity,
        entidade_id=entidade_id,
        antes=_normalize_snapshot(antes),
        depois=_normalize_snapshot(depois),
        ip=ip,
    )
    session.add(event)
    session.flush()
    return event


def _normalize_snapshot(snapshot: Mapping[str, object] | None) -> dict[str, object] | None:
    if snapshot is None:
        return None
    try:
        safe_snapshot = _redact_sensitive_values(snapshot)
        serialized = json.dumps(
            safe_snapshot,
            default=_serialize_json_value,
            ensure_ascii=False,
            allow_nan=False,
        )
        return cast(dict[str, object], json.loads(serialized))
    except (TypeError, ValueError) as error:
        raise AuditEventError("Snapshot de auditoria deve conter valores JSON válidos.") from error


def _redact_sensitive_values(value: object) -> object:
    if isinstance(value, Mapping):
        redacted: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("Chaves de snapshots devem ser strings.")
            normalized_key = "".join(
                character for character in key.casefold() if character.isalnum()
            )
            is_sensitive = any(marker in normalized_key for marker in _SENSITIVE_KEY_MARKERS)
            redacted[key] = REDACTED if is_sensitive else _redact_sensitive_values(item)
        return redacted
    if isinstance(value, (list, tuple)):
        return [_redact_sensitive_values(item) for item in value]
    return value


def _serialize_json_value(value: object) -> str:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return str(value.value)
    raise TypeError(f"Valor de snapshot não serializável: {type(value).__name__}.")
