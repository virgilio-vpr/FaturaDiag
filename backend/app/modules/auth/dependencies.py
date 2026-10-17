from __future__ import annotations

from typing import Annotated

from app.core.settings import Settings
from app.db import get_session
from app.modules.auth.service import AuthContext, AuthenticationError, authenticate_access_token
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

bearer_scheme = HTTPBearer(auto_error=False)
settings = Settings()


def get_current_auth(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    session: Annotated[Session, Depends(get_session)],
) -> AuthContext:
    if credentials is None or credentials.scheme.casefold() != "bearer":
        raise unauthorized_exception()
    try:
        return authenticate_access_token(session, credentials.credentials, settings)
    except AuthenticationError as error:
        raise unauthorized_exception() from error


def unauthorized_exception() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Credenciais inválidas.",
        headers={"WWW-Authenticate": "Bearer"},
    )
