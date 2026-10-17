from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from app.db import get_session
from app.modules.auth.rbac import Papel, requer_papel
from app.modules.auth.service import AuthContext
from app.modules.tarifas.hints import (
    HintAmbiguoError,
    HintConflitanteError,
    HintInvalidoError,
    HintNaoEncontrado,
    atualizar_hint,
    listar_hints,
    versionar_hint,
)
from app.modules.tarifas.hints_schemas import (
    HintDistribuidoraList,
    HintDistribuidoraResponse,
    HintDistribuidoraUpdate,
    HintDistribuidoraVersionCreate,
)
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

router = APIRouter(prefix="/admin/hints", tags=["hints"])
AdminActor = Annotated[AuthContext, Depends(requer_papel(Papel.ADMIN))]


@router.get("", response_model=HintDistribuidoraList)
def get_hints(
    auth: AdminActor,
    session: Annotated[Session, Depends(get_session)],
    distribuidora_id: UUID | None = None,
    data: date | None = None,
) -> HintDistribuidoraList:
    del auth
    try:
        hints = listar_hints(session, distribuidora_id=distribuidora_id, data=data)
    except HintAmbiguoError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return HintDistribuidoraList(
        itens=[HintDistribuidoraResponse.model_validate(hint) for hint in hints]
    )


@router.put("", response_model=HintDistribuidoraResponse)
def put_hint(
    request: Request,
    payload: HintDistribuidoraUpdate,
    auth: AdminActor,
    session: Annotated[Session, Depends(get_session)],
) -> HintDistribuidoraResponse:
    try:
        hint = atualizar_hint(
            session,
            distribuidora_id=payload.distribuidora_id,
            versao=payload.versao,
            arquivo_md=payload.arquivo_md,
            usuario_id=auth.user.id,
            organizacao_id=auth.user.organizacao_id,
            ip=request.client.host if request.client is not None else None,
        )
    except HintNaoEncontrado as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except HintInvalidoError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error
    return HintDistribuidoraResponse.model_validate(hint)


@router.post(
    "/{distribuidora_id}/versionar",
    response_model=HintDistribuidoraResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_hint_version(
    distribuidora_id: UUID,
    request: Request,
    payload: HintDistribuidoraVersionCreate,
    auth: AdminActor,
    session: Annotated[Session, Depends(get_session)],
) -> HintDistribuidoraResponse:
    try:
        hint = versionar_hint(
            session,
            distribuidora_id=distribuidora_id,
            versao=payload.versao,
            arquivo_md=payload.arquivo_md,
            vigencia_inicio=payload.vigencia_inicio,
            usuario_id=auth.user.id,
            organizacao_id=auth.user.organizacao_id,
            ip=request.client.host if request.client is not None else None,
        )
    except HintNaoEncontrado as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except HintInvalidoError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error
    except HintConflitanteError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return HintDistribuidoraResponse.model_validate(hint)
