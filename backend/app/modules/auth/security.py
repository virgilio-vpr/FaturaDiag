from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal, cast
from uuid import UUID

import jwt
from app.core.settings import Settings
from pwdlib import PasswordHash

TokenType = Literal["access", "refresh"]
PASSWORD_HASHER = PasswordHash.recommended()
DUMMY_PASSWORD_HASH = PASSWORD_HASHER.hash("faturadiag-invalid-user-password")


class InvalidTokenError(Exception):
    pass


def hash_password(password: str) -> str:
    return PASSWORD_HASHER.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return PASSWORD_HASHER.verify(password, password_hash)


def create_token(
    *,
    user_id: UUID,
    session_id: UUID,
    version: int,
    token_type: TokenType,
    settings: Settings,
    expires_at: datetime | None = None,
) -> str:
    now = datetime.now(UTC)
    if expires_at is None:
        lifetime = (
            timedelta(minutes=settings.access_token_minutes)
            if token_type == "access"
            else timedelta(days=settings.refresh_token_days)
        )
        expires_at = now + lifetime

    claims = {
        "sub": str(user_id),
        "sid": str(session_id),
        "ver": version,
        "typ": token_type,
        "iat": now,
        "exp": expires_at,
    }
    return jwt.encode(claims, settings.secret_key.get_secret_value(), algorithm="HS256")


def decode_token(token: str, settings: Settings) -> dict[str, object]:
    try:
        claims = jwt.decode(
            token,
            settings.secret_key.get_secret_value(),
            algorithms=["HS256"],
            options={"require": ["sub", "sid", "ver", "typ", "iat", "exp"]},
        )
    except jwt.PyJWTError as error:
        raise InvalidTokenError from error
    return cast(dict[str, object], claims)
