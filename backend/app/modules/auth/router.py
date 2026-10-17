from __future__ import annotations

from typing import Annotated

from app.core.errors import problem_response
from app.core.settings import Settings
from app.db import get_session
from app.modules.auth.dependencies import get_current_auth, unauthorized_exception
from app.modules.auth.schemas import (
    LoginRequest,
    RefreshRequest,
    TokenResponse,
    UserResponse,
)
from app.modules.auth.service import (
    AuthContext,
    AuthenticationError,
    authenticate_user,
    create_auth_session,
    issue_token_pair,
    revoke_auth_session,
    rotate_refresh_token,
)
from fastapi import APIRouter, Depends, Request, status
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session
from starlette.responses import Response

limiter = Limiter(key_func=get_remote_address)
router = APIRouter(prefix="/auth", tags=["autenticacao"])
settings = Settings()


@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute")
def login(
    request: Request,
    credentials: LoginRequest,
    session: Annotated[Session, Depends(get_session)],
) -> TokenResponse:
    try:
        user = authenticate_user(session, credentials.email, credentials.senha, settings)
    except AuthenticationError as error:
        raise unauthorized_exception() from error
    auth_session = create_auth_session(session, user, settings)
    return TokenResponse(**issue_token_pair(user, auth_session, settings))


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit("30/minute")
def refresh(
    request: Request,
    credentials: RefreshRequest,
    session: Annotated[Session, Depends(get_session)],
) -> TokenResponse:
    try:
        user, auth_session = rotate_refresh_token(session, credentials.refresh_token, settings)
    except AuthenticationError as error:
        raise unauthorized_exception() from error
    return TokenResponse(**issue_token_pair(user, auth_session, settings))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    auth: Annotated[AuthContext, Depends(get_current_auth)],
    session: Annotated[Session, Depends(get_session)],
) -> Response:
    revoke_auth_session(session, auth.session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UserResponse)
def me(auth: Annotated[AuthContext, Depends(get_current_auth)]) -> UserResponse:
    return UserResponse.model_validate(auth.user)


def rate_limit_problem(request: Request, _error: Exception) -> Response:
    return problem_response(
        request,
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        title="Too Many Requests",
        detail="Limite de solicitações excedido. Tente novamente mais tarde.",
    )
