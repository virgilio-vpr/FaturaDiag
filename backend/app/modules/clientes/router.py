from __future__ import annotations

from typing import Annotated
from uuid import UUID

from app.db import get_session
from app.modules.auth.rbac import Papel, requer_papel
from app.modules.auth.service import AuthContext
from app.modules.clientes.schemas import ClienteCreate, ClientePage, ClienteResponse, ClienteUpdate
from app.modules.clientes.service import (
    ClienteConflictError,
    ClienteNotFoundError,
    atualizar_cliente,
    criar_cliente,
    excluir_cliente,
    listar_clientes,
    obter_cliente,
)
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.orm import Session

router = APIRouter(prefix="/clientes", tags=["clientes"])
ClienteActor = Annotated[AuthContext, Depends(requer_papel(Papel.ADMIN, Papel.ANALISTA))]


@router.get("", response_model=ClientePage)
def list_clients(
    auth: ClienteActor,
    session: Annotated[Session, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: UUID | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
) -> ClientePage:
    clientes, next_cursor = listar_clientes(
        session,
        organizacao_id=auth.user.organizacao_id,
        query=q,
        limit=limit,
        cursor=cursor,
    )
    return ClientePage(
        items=[ClienteResponse.model_validate(cliente) for cliente in clientes],
        limit=limit,
        next_cursor=next_cursor,
    )


@router.post("", response_model=ClienteResponse, status_code=status.HTTP_201_CREATED)
def create_client(
    request: Request,
    payload: ClienteCreate,
    auth: ClienteActor,
    session: Annotated[Session, Depends(get_session)],
) -> ClienteResponse:
    try:
        cliente = criar_cliente(
            session,
            organizacao_id=auth.user.organizacao_id,
            usuario_id=auth.user.id,
            payload=payload,
            ip=_request_ip(request),
        )
    except ClienteConflictError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return ClienteResponse.model_validate(cliente)


@router.get("/{cliente_id}", response_model=ClienteResponse)
def get_client(
    cliente_id: UUID,
    auth: ClienteActor,
    session: Annotated[Session, Depends(get_session)],
) -> ClienteResponse:
    try:
        cliente = obter_cliente(
            session,
            organizacao_id=auth.user.organizacao_id,
            cliente_id=cliente_id,
        )
    except ClienteNotFoundError as error:
        raise _not_found() from error
    return ClienteResponse.model_validate(cliente)


@router.patch("/{cliente_id}", response_model=ClienteResponse)
def patch_client(
    cliente_id: UUID,
    request: Request,
    payload: ClienteUpdate,
    auth: ClienteActor,
    session: Annotated[Session, Depends(get_session)],
) -> ClienteResponse:
    try:
        cliente = atualizar_cliente(
            session,
            organizacao_id=auth.user.organizacao_id,
            usuario_id=auth.user.id,
            cliente_id=cliente_id,
            payload=payload,
            ip=_request_ip(request),
        )
    except ClienteNotFoundError as error:
        raise _not_found() from error
    except ClienteConflictError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return ClienteResponse.model_validate(cliente)


@router.delete("/{cliente_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_client(
    cliente_id: UUID,
    request: Request,
    auth: ClienteActor,
    session: Annotated[Session, Depends(get_session)],
) -> Response:
    try:
        excluir_cliente(
            session,
            organizacao_id=auth.user.organizacao_id,
            usuario_id=auth.user.id,
            cliente_id=cliente_id,
            ip=_request_ip(request),
        )
    except ClienteNotFoundError as error:
        raise _not_found() from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _request_ip(request: Request) -> str | None:
    return request.client.host if request.client is not None else None


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cliente não encontrado.")
