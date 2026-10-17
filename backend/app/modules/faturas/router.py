from __future__ import annotations

from functools import lru_cache
from typing import Annotated
from uuid import UUID

from app.core.settings import Settings
from app.db import get_session
from app.integrations.storage import StorageBackend, criar_storage
from app.modules.auth.rbac import Papel, requer_papel
from app.modules.auth.service import AuthContext
from app.modules.faturas.arquivos import ArquivoInvalidoError
from app.modules.faturas.schemas import FaturaUploadResponse
from app.modules.faturas.service import UnidadeNotFoundError, registrar_upload
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from sqlalchemy.orm import Session

router = APIRouter(tags=["faturas"])
FaturaWriter = Annotated[AuthContext, Depends(requer_papel(Papel.ADMIN, Papel.ANALISTA))]


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def _storage_singleton() -> StorageBackend:
    return criar_storage(get_settings())


def get_storage() -> StorageBackend:
    return _storage_singleton()


@router.post(
    "/faturas",
    response_model=FaturaUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_fatura(
    request: Request,
    auth: FaturaWriter,
    session: Annotated[Session, Depends(get_session)],
    storage: Annotated[StorageBackend, Depends(get_storage)],
    settings: Annotated[Settings, Depends(get_settings)],
    arquivo: Annotated[UploadFile, File()],
    unidade_id: Annotated[UUID | None, Form()] = None,
    idempotency_key: Annotated[str | None, Header(max_length=128)] = None,
) -> FaturaUploadResponse:
    max_bytes = settings.max_upload_mb * 1024 * 1024
    conteudo = await arquivo.read(max_bytes + 1)
    try:
        fatura = registrar_upload(
            session,
            storage,
            organizacao_id=auth.user.organizacao_id,
            usuario_id=auth.user.id,
            conteudo=conteudo,
            unidade_id=unidade_id,
            idempotency_key=idempotency_key,
            max_bytes=max_bytes,
            max_paginas=settings.max_pdf_pages,
            ip=request.client.host if request.client is not None else None,
        )
    except UnidadeNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except ArquivoInvalidoError as error:
        raise HTTPException(error.status_code, str(error)) from error
    return FaturaUploadResponse(id=fatura.id, status=fatura.status)
