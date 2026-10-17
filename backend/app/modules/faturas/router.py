from __future__ import annotations

from functools import lru_cache
from typing import Annotated
from uuid import UUID

from app.core.errors import problem_response
from app.core.settings import Settings
from app.db import SessionLocal, get_session
from app.db.models import Arquivo
from app.integrations.llm.extrator import ExtratorLLM
from app.integrations.llm.factory import criar_extrator
from app.integrations.storage import ObjetoNaoEncontrado, StorageBackend, criar_storage
from app.modules.auth.rbac import Papel, requer_papel
from app.modules.auth.service import AuthContext
from app.modules.faturas.arquivos import ArquivoInvalidoError
from app.modules.faturas.estados import TransicaoInvalidaError
from app.modules.faturas.pipeline import processar_extracao
from app.modules.faturas.revisao import (
    FaturaComBloqueantesError,
    FaturaDuplicadaError,
    FaturaNaoEncontradaError,
    atualizar_dados,
    listar_faturas,
    listar_itens,
    obter_fatura,
    preparar_reextracao,
    validar_fatura,
)
from app.modules.faturas.schemas import (
    DadosFaturaUpdate,
    FaturaItemResponse,
    FaturaResponse,
    FaturaResumo,
    FaturaUploadResponse,
)
from app.modules.faturas.service import UnidadeNotFoundError, registrar_upload
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

router = APIRouter(tags=["faturas"])
FaturaWriter = Annotated[AuthContext, Depends(requer_papel(Papel.ADMIN, Papel.ANALISTA))]
FaturaReader = Annotated[
    AuthContext, Depends(requer_papel(Papel.ADMIN, Papel.ANALISTA, Papel.CLIENTE))
]


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def _storage_singleton() -> StorageBackend:
    return criar_storage(get_settings())


def get_storage() -> StorageBackend:
    return _storage_singleton()


@lru_cache
def _extrator_singleton() -> ExtratorLLM:
    return criar_extrator(get_settings())


def get_extrator() -> ExtratorLLM:
    return _extrator_singleton()


def _job_extracao(
    storage: StorageBackend,
    extrator: ExtratorLLM,
    settings: Settings,
    fatura_id: UUID,
    organizacao_id: UUID,
    usuario_id: UUID,
) -> None:
    with SessionLocal() as session:
        processar_extracao(
            session,
            storage,
            extrator,
            settings,
            fatura_id=fatura_id,
            organizacao_id=organizacao_id,
            usuario_id=usuario_id,
        )


def _ip(request: Request) -> str | None:
    return request.client.host if request.client is not None else None


@router.post(
    "/faturas",
    response_model=FaturaUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_fatura(
    request: Request,
    background: BackgroundTasks,
    auth: FaturaWriter,
    session: Annotated[Session, Depends(get_session)],
    storage: Annotated[StorageBackend, Depends(get_storage)],
    settings: Annotated[Settings, Depends(get_settings)],
    extrator: Annotated[ExtratorLLM, Depends(get_extrator)],
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
    if fatura.status == "ENVIADA":
        background.add_task(
            _job_extracao,
            storage,
            extrator,
            settings,
            fatura.id,
            auth.user.organizacao_id,
            auth.user.id,
        )
    return FaturaUploadResponse(id=fatura.id, status=fatura.status)


def _detalhe(session: Session, fatura_id: UUID, auth: AuthContext) -> FaturaResponse:
    try:
        fatura = obter_fatura(session, auth.user.organizacao_id, fatura_id)
    except FaturaNaoEncontradaError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    resposta = FaturaResponse.model_validate(fatura)
    resposta.itens = [
        FaturaItemResponse.model_validate(item) for item in listar_itens(session, fatura)
    ]
    return resposta


@router.get("/faturas", response_model=list[FaturaResumo])
def listar(
    auth: FaturaReader,
    session: Annotated[Session, Depends(get_session)],
    status_fatura: Annotated[str | None, Query(alias="status")] = None,
    uc_id: UUID | None = None,
    limite: Annotated[int, Query(ge=1, le=200)] = 50,
    deslocamento: Annotated[int, Query(ge=0)] = 0,
) -> list[FaturaResumo]:
    faturas = listar_faturas(
        session,
        auth.user.organizacao_id,
        status=status_fatura,
        uc_id=uc_id,
        limite=limite,
        deslocamento=deslocamento,
    )
    return [FaturaResumo.model_validate(f) for f in faturas]


@router.get("/faturas/{fatura_id}", response_model=FaturaResponse)
def detalhar(
    fatura_id: UUID,
    auth: FaturaReader,
    session: Annotated[Session, Depends(get_session)],
) -> FaturaResponse:
    return _detalhe(session, fatura_id, auth)


@router.get("/faturas/{fatura_id}/arquivo")
def baixar_arquivo(
    fatura_id: UUID,
    auth: FaturaReader,
    session: Annotated[Session, Depends(get_session)],
    storage: Annotated[StorageBackend, Depends(get_storage)],
) -> Response:
    try:
        fatura = obter_fatura(session, auth.user.organizacao_id, fatura_id)
    except FaturaNaoEncontradaError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    arquivo = session.get(Arquivo, fatura.arquivo_id) if fatura.arquivo_id else None
    if arquivo is None or arquivo.organizacao_id != auth.user.organizacao_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Arquivo não encontrado.")
    try:
        conteudo = storage.get(arquivo.storage_key)
    except ObjetoNaoEncontrado as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Arquivo não encontrado.") from error
    return Response(
        conteudo,
        media_type=arquivo.mime,
        headers={"X-Content-Type-Options": "nosniff", "Content-Disposition": "inline"},
    )


@router.put("/faturas/{fatura_id}/dados", response_model=FaturaResponse)
def revisar_dados(
    fatura_id: UUID,
    payload: DadosFaturaUpdate,
    request: Request,
    auth: FaturaWriter,
    session: Annotated[Session, Depends(get_session)],
) -> FaturaResponse:
    valores = {nome: getattr(payload, nome) for nome in payload.model_fields_set if nome != "itens"}
    itens = (
        [item.model_dump(mode="python") for item in payload.itens]
        if payload.itens is not None
        else None
    )
    if itens is not None:
        for item in itens:
            item["categoria"] = item["categoria"].value
    try:
        atualizar_dados(
            session,
            organizacao_id=auth.user.organizacao_id,
            usuario_id=auth.user.id,
            fatura_id=fatura_id,
            valores=valores,
            itens=itens,
            ip=_ip(request),
        )
    except FaturaNaoEncontradaError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except UnidadeNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except (TransicaoInvalidaError, FaturaDuplicadaError) as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
    return _detalhe(session, fatura_id, auth)


@router.post("/faturas/{fatura_id}/validar", response_model=FaturaResponse)
def validar(
    fatura_id: UUID,
    request: Request,
    auth: FaturaWriter,
    session: Annotated[Session, Depends(get_session)],
) -> FaturaResponse | JSONResponse:
    try:
        validar_fatura(
            session,
            organizacao_id=auth.user.organizacao_id,
            usuario_id=auth.user.id,
            fatura_id=fatura_id,
            ip=_ip(request),
        )
    except FaturaNaoEncontradaError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except TransicaoInvalidaError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
    except FaturaComBloqueantesError as error:
        return problem_response(
            request,
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            title="Fatura com alertas bloqueantes",
            detail=str(error),
            errors=[
                {"field": a.campo or "", "message": a.mensagem, "code": a.codigo}
                for a in error.alertas
            ],
        )
    return _detalhe(session, fatura_id, auth)


@router.post(
    "/faturas/{fatura_id}/reextrair",
    response_model=FaturaUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def reextrair(
    fatura_id: UUID,
    request: Request,
    background: BackgroundTasks,
    auth: FaturaWriter,
    session: Annotated[Session, Depends(get_session)],
    storage: Annotated[StorageBackend, Depends(get_storage)],
    settings: Annotated[Settings, Depends(get_settings)],
    extrator: Annotated[ExtratorLLM, Depends(get_extrator)],
) -> FaturaUploadResponse:
    try:
        fatura = preparar_reextracao(
            session,
            organizacao_id=auth.user.organizacao_id,
            usuario_id=auth.user.id,
            fatura_id=fatura_id,
            ip=_ip(request),
        )
    except FaturaNaoEncontradaError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except TransicaoInvalidaError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
    background.add_task(
        _job_extracao,
        storage,
        extrator,
        settings,
        fatura.id,
        auth.user.organizacao_id,
        auth.user.id,
    )
    return FaturaUploadResponse(id=fatura.id, status=fatura.status)
