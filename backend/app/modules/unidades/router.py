from __future__ import annotations

from typing import Annotated
from uuid import UUID

from app.db import get_session
from app.modules.auth.rbac import Papel, requer_papel
from app.modules.auth.service import AuthContext
from app.modules.unidades.schemas import (
    ContratoCreate,
    ContratoResponse,
    UnidadeCreate,
    UnidadePage,
    UnidadeResponse,
    UnidadeUpdate,
)
from app.modules.unidades.service import (
    CadastroValidationError,
    UnidadeConflictError,
    UnidadeNotFoundError,
    atualizar_unidade,
    criar_contrato,
    criar_unidade,
    listar_contratos,
    listar_unidades,
    obter_unidade,
)
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

router = APIRouter(tags=["unidades"])
UnidadeActor = Annotated[AuthContext, Depends(requer_papel(Papel.ADMIN, Papel.ANALISTA))]


@router.get("/clientes/{cliente_id}/unidades", response_model=UnidadePage)
def list_customer_units(
    cliente_id: UUID,
    auth: UnidadeActor,
    session: Annotated[Session, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: UUID | None = None,
) -> UnidadePage:
    try:
        units, next_cursor = listar_unidades(
            session,
            organizacao_id=auth.user.organizacao_id,
            cliente_id=cliente_id,
            limit=limit,
            cursor=cursor,
        )
    except UnidadeNotFoundError as error:
        raise _not_found(str(error)) from error
    return UnidadePage(
        items=[UnidadeResponse.model_validate(unit) for unit in units],
        limit=limit,
        next_cursor=next_cursor,
    )


@router.post(
    "/clientes/{cliente_id}/unidades",
    response_model=UnidadeResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_customer_unit(
    cliente_id: UUID,
    request: Request,
    payload: UnidadeCreate,
    auth: UnidadeActor,
    session: Annotated[Session, Depends(get_session)],
) -> UnidadeResponse:
    try:
        unit = criar_unidade(
            session,
            organizacao_id=auth.user.organizacao_id,
            usuario_id=auth.user.id,
            cliente_id=cliente_id,
            payload=payload,
            ip=_request_ip(request),
        )
    except UnidadeNotFoundError as error:
        raise _not_found(str(error)) from error
    except UnidadeConflictError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except CadastroValidationError as error:
        raise _unprocessable(str(error)) from error
    return UnidadeResponse.model_validate(unit)


@router.get("/unidades/{unidade_id}", response_model=UnidadeResponse)
def get_unit(
    unidade_id: UUID,
    auth: UnidadeActor,
    session: Annotated[Session, Depends(get_session)],
) -> UnidadeResponse:
    try:
        unit = obter_unidade(
            session,
            organizacao_id=auth.user.organizacao_id,
            unidade_id=unidade_id,
        )
    except UnidadeNotFoundError as error:
        raise _not_found(str(error)) from error
    return UnidadeResponse.model_validate(unit)


@router.patch("/unidades/{unidade_id}", response_model=UnidadeResponse)
def patch_unit(
    unidade_id: UUID,
    request: Request,
    payload: UnidadeUpdate,
    auth: UnidadeActor,
    session: Annotated[Session, Depends(get_session)],
) -> UnidadeResponse:
    try:
        unit = atualizar_unidade(
            session,
            organizacao_id=auth.user.organizacao_id,
            usuario_id=auth.user.id,
            unidade_id=unidade_id,
            payload=payload,
            ip=_request_ip(request),
        )
    except UnidadeNotFoundError as error:
        raise _not_found(str(error)) from error
    except UnidadeConflictError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except CadastroValidationError as error:
        raise _unprocessable(str(error)) from error
    return UnidadeResponse.model_validate(unit)


@router.get("/unidades/{unidade_id}/contratos", response_model=list[ContratoResponse])
def list_unit_contracts(
    unidade_id: UUID,
    auth: UnidadeActor,
    session: Annotated[Session, Depends(get_session)],
) -> list[ContratoResponse]:
    try:
        contracts = listar_contratos(
            session,
            organizacao_id=auth.user.organizacao_id,
            unidade_id=unidade_id,
        )
    except UnidadeNotFoundError as error:
        raise _not_found(str(error)) from error
    return [ContratoResponse.model_validate(contract) for contract in contracts]


@router.post(
    "/unidades/{unidade_id}/contratos",
    response_model=ContratoResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_unit_contract(
    unidade_id: UUID,
    request: Request,
    payload: ContratoCreate,
    auth: UnidadeActor,
    session: Annotated[Session, Depends(get_session)],
) -> ContratoResponse:
    try:
        contract = criar_contrato(
            session,
            organizacao_id=auth.user.organizacao_id,
            usuario_id=auth.user.id,
            unidade_id=unidade_id,
            payload=payload,
            ip=_request_ip(request),
        )
    except UnidadeNotFoundError as error:
        raise _not_found(str(error)) from error
    except CadastroValidationError as error:
        raise _unprocessable(str(error)) from error
    return ContratoResponse.model_validate(contract)


def _request_ip(request: Request) -> str | None:
    return request.client.host if request.client is not None else None


def _not_found(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


def _unprocessable(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detail)
