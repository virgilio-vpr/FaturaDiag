from __future__ import annotations

from typing import Annotated
from uuid import UUID

from app.db import get_session
from app.db.models import Relatorio
from app.integrations.storage import StorageBackend
from app.modules.auth.rbac import Papel, requer_papel
from app.modules.auth.service import AuthContext
from app.modules.diagnosticos.revisao import DiagnosticoNaoEncontrado, TransicaoDiagnosticoInvalida
from app.modules.faturas.router import get_storage
from app.modules.relatorios.schemas import RelatorioResponse
from app.modules.relatorios.service import RelatorioNaoEncontrado, baixar_relatorio, gerar_relatorio
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from starlette.responses import Response

router = APIRouter(tags=["relatorios"])
Escritor = Annotated[AuthContext, Depends(requer_papel(Papel.ADMIN, Papel.ANALISTA))]
Leitor = Annotated[AuthContext, Depends(requer_papel(Papel.ADMIN, Papel.ANALISTA, Papel.CLIENTE))]
DbSession = Annotated[Session, Depends(get_session)]
Storage = Annotated[StorageBackend, Depends(get_storage)]


def _resposta(relatorio: Relatorio) -> RelatorioResponse:
    return RelatorioResponse(
        id=relatorio.id,
        diagnostico_id=relatorio.diagnostico_id,
        versao=relatorio.versao,
        template=relatorio.template,
        gerado_por=relatorio.gerado_por,
        gerado_em=relatorio.gerado_em,
        download_url=f"/relatorios/{relatorio.id}/download",
    )


@router.post(
    "/diagnosticos/{diagnostico_id}/relatorio", response_model=RelatorioResponse, status_code=202
)
def post_relatorio(
    diagnostico_id: UUID,
    request: Request,
    auth: Escritor,
    session: DbSession,
    storage: Storage,
) -> RelatorioResponse:
    try:
        relatorio = gerar_relatorio(
            session,
            storage,
            organizacao_id=auth.user.organizacao_id,
            usuario_id=auth.user.id,
            diagnostico_id=diagnostico_id,
            ip=request.client.host if request.client else None,
        )
    except DiagnosticoNaoEncontrado as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except TransicaoDiagnosticoInvalida as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return _resposta(relatorio)


@router.get("/relatorios/{relatorio_id}/download")
def get_download(
    relatorio_id: UUID, auth: Leitor, session: DbSession, storage: Storage
) -> Response:
    try:
        baixado = baixar_relatorio(
            session,
            storage,
            organizacao_id=auth.user.organizacao_id,
            relatorio_id=relatorio_id,
            somente_publicados=auth.user.papel == Papel.CLIENTE,
        )
    except RelatorioNaoEncontrado as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return Response(
        baixado.conteudo,
        media_type="application/pdf",
        headers={
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": f'attachment; filename="{baixado.nome}"',
        },
    )
