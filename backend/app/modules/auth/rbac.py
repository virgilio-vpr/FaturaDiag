from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from typing import Annotated

from app.modules.auth.dependencies import get_current_auth
from app.modules.auth.service import AuthContext
from fastapi import Depends, HTTPException, status


class Papel(StrEnum):
    ADMIN = "ADMIN"
    ANALISTA = "ANALISTA"
    CLIENTE = "CLIENTE"
    PARCEIRO = "PARCEIRO"


AuthDependency = Callable[..., AuthContext]


def requer_papel(*papeis: Papel | str) -> AuthDependency:
    if not papeis:
        raise ValueError("Informe ao menos um papel permitido.")

    allowed_roles = frozenset(str(papel) for papel in papeis)
    known_roles = frozenset(papel.value for papel in Papel)
    unknown_roles = allowed_roles - known_roles
    if unknown_roles:
        raise ValueError(f"Papéis desconhecidos: {', '.join(sorted(unknown_roles))}.")

    def authorize(
        auth: Annotated[AuthContext, Depends(get_current_auth)],
    ) -> AuthContext:
        if auth.user.papel not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Papel sem permissão para esta operação.",
            )
        return auth

    return authorize
