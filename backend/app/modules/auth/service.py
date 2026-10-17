from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TypedDict
from uuid import UUID

from app.core.settings import Settings
from app.db.models import AuthSession, Usuario
from app.modules.auth.security import (
    DUMMY_PASSWORD_HASH,
    InvalidTokenError,
    create_token,
    decode_token,
    verify_password,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session


class AuthenticationError(Exception):
    pass


class TokenPair(TypedDict):
    access_token: str
    refresh_token: str
    expires_in: int


@dataclass(frozen=True)
class AuthContext:
    user: Usuario
    session_id: UUID
    token_version: int


def authenticate_user(session: Session, email: str, password: str, settings: Settings) -> Usuario:
    normalized_email = email.strip().casefold()
    user = session.execute(
        select(Usuario).where(func.lower(Usuario.email) == normalized_email).with_for_update()
    ).scalar_one_or_none()
    if user is None:
        verify_password(password, DUMMY_PASSWORD_HASH)
        raise AuthenticationError
    if not user.ativo:
        verify_password(password, user.senha_hash)
        raise AuthenticationError

    now = datetime.now(UTC)
    if user.bloqueado_ate is not None and user.bloqueado_ate > now:
        raise AuthenticationError

    if not verify_password(password, user.senha_hash):
        user.login_falhas_consecutivas += 1
        if user.login_falhas_consecutivas >= settings.auth_max_failed_attempts:
            excess_attempts = user.login_falhas_consecutivas - settings.auth_max_failed_attempts
            multiplier = 2 ** min(excess_attempts, 20)
            lockout_seconds = min(
                settings.auth_lockout_base_seconds * multiplier,
                settings.auth_lockout_max_seconds,
            )
            user.bloqueado_ate = now + timedelta(seconds=lockout_seconds)
        session.commit()
        raise AuthenticationError

    user.login_falhas_consecutivas = 0
    user.bloqueado_ate = None
    user.ultimo_login_em = now
    session.commit()
    return user


def create_auth_session(session: Session, user: Usuario, settings: Settings) -> AuthSession:
    auth_session = AuthSession(
        usuario_id=user.id,
        versao_token=0,
        expira_em=datetime.now(UTC) + timedelta(days=settings.refresh_token_days),
    )
    session.add(auth_session)
    session.commit()
    return auth_session


def issue_token_pair(user: Usuario, auth_session: AuthSession, settings: Settings) -> TokenPair:
    return {
        "access_token": create_token(
            user_id=user.id,
            session_id=auth_session.id,
            version=auth_session.versao_token,
            token_type="access",
            settings=settings,
        ),
        "refresh_token": create_token(
            user_id=user.id,
            session_id=auth_session.id,
            version=auth_session.versao_token,
            token_type="refresh",
            settings=settings,
            expires_at=auth_session.expira_em,
        ),
        "expires_in": settings.access_token_minutes * 60,
    }


def rotate_refresh_token(
    session: Session, token: str, settings: Settings
) -> tuple[Usuario, AuthSession]:
    claims = _decode_claims(token, "refresh", settings)
    user_id, session_id, version = _claim_identity(claims)
    auth_session = session.execute(
        select(AuthSession).where(AuthSession.id == session_id).with_for_update()
    ).scalar_one_or_none()
    now = datetime.now(UTC)
    if (
        auth_session is None
        or auth_session.usuario_id != user_id
        or auth_session.revogada_em is not None
        or auth_session.expira_em <= now
        or auth_session.versao_token != version
    ):
        raise AuthenticationError

    user = session.get(Usuario, user_id)
    if user is None or not user.ativo:
        raise AuthenticationError

    auth_session.versao_token += 1
    session.commit()
    return user, auth_session


def authenticate_access_token(session: Session, token: str, settings: Settings) -> AuthContext:
    claims = _decode_claims(token, "access", settings)
    user_id, session_id, version = _claim_identity(claims)
    auth_session = session.get(AuthSession, session_id)
    now = datetime.now(UTC)
    if (
        auth_session is None
        or auth_session.usuario_id != user_id
        or auth_session.revogada_em is not None
        or auth_session.expira_em <= now
        or auth_session.versao_token != version
    ):
        raise AuthenticationError

    user = session.get(Usuario, user_id)
    if user is None or not user.ativo:
        raise AuthenticationError
    return AuthContext(user=user, session_id=session_id, token_version=version)


def revoke_auth_session(session: Session, session_id: UUID) -> None:
    auth_session = session.get(AuthSession, session_id)
    if auth_session is not None and auth_session.revogada_em is None:
        auth_session.revogada_em = datetime.now(UTC)
        session.commit()


def _decode_claims(token: str, expected_type: str, settings: Settings) -> dict[str, object]:
    try:
        claims = decode_token(token, settings)
    except InvalidTokenError as error:
        raise AuthenticationError from error
    if claims.get("typ") != expected_type:
        raise AuthenticationError
    return claims


def _claim_identity(claims: dict[str, object]) -> tuple[UUID, UUID, int]:
    try:
        user_id = UUID(str(claims["sub"]))
        session_id = UUID(str(claims["sid"]))
        version = int(str(claims["ver"]))
    except (KeyError, TypeError, ValueError) as error:
        raise AuthenticationError from error
    return user_id, session_id, version
