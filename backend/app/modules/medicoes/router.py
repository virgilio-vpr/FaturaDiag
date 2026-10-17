from __future__ import annotations

from datetime import date
from functools import lru_cache
from typing import Annotated
from uuid import UUID

from app.core.errors import problem_response
from app.core.settings import Settings
from app.db import get_session
from app.modules.auth.rbac import Papel, requer_papel
from app.modules.auth.service import AuthContext
from app.modules.medicoes.importacao import (
    ErroImportacaoMedicao,
    PerfilImportacao,
    parsear_memoria,
)
from app.modules.medicoes.schemas import ImportacaoMedicoesResponse, ResumoMedicoesResponse
from app.modules.medicoes.service import (
    ArquivoMedicoesComErros,
    ParametrosAnaliseIndisponiveis,
    PeriodoMedicoesInvalido,
    UnidadeMedicoesNaoEncontrada,
    importar_medicoes,
    obter_resumo_medicoes,
)
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from sqlalchemy.orm import Session
from starlette.responses import Response

router = APIRouter(tags=["medicoes"])
MedicaoWriter = Annotated[AuthContext, Depends(requer_papel(Papel.ADMIN, Papel.ANALISTA))]
MedicaoReader = Annotated[AuthContext, Depends(requer_papel(Papel.ADMIN, Papel.ANALISTA))]


@lru_cache
def get_settings() -> Settings:
    return Settings()


@router.post(
    "/unidades/{uc_id}/medicoes",
    response_model=ImportacaoMedicoesResponse,
    status_code=201,
)
async def upload_medicoes(
    uc_id: UUID,
    request: Request,
    auth: MedicaoWriter,
    session: Annotated[Session, Depends(get_session)],
    arquivo: Annotated[UploadFile, File()],
    perfil: Annotated[str | None, Form()] = None,
) -> ImportacaoMedicoesResponse | Response:
    max_bytes = get_settings().max_upload_mb * 1024 * 1024
    if perfil is not None and len(perfil) > 10_000:
        raise HTTPException(status_code=422, detail="Perfil de importação excede o limite.")
    contents = await arquivo.read(max_bytes + 1)
    if len(contents) > max_bytes:
        raise HTTPException(status_code=413, detail="Arquivo excede o limite de tamanho.")
    try:
        import_profile = PerfilImportacao.model_validate_json(perfil) if perfil else None
        parsed = parsear_memoria(contents, perfil=import_profile)
        affected = importar_medicoes(
            session,
            organizacao_id=auth.user.organizacao_id,
            usuario_id=auth.user.id,
            uc_id=uc_id,
            resultado=parsed,
            ip=request.client.host if request.client is not None else None,
        )
    except ErroImportacaoMedicao as error:
        return problem_response(
            request,
            status_code=422,
            title="Unprocessable Entity",
            detail=str(error),
            errors=(
                [
                    {
                        "field": "colunas_encontradas",
                        "message": ", ".join(error.colunas_encontradas),
                        "code": "mapping_required",
                    }
                ]
                if error.colunas_encontradas
                else []
            ),
        )
    except ArquivoMedicoesComErros as error:
        result = error.result
        return problem_response(
            request,
            status_code=422,
            title="Unprocessable Entity",
            detail=str(error),
            errors=[
                {
                    "field": "validacao",
                    "message": erro,
                    "code": "invalid_measurements",
                }
                for erro in result.erros_bloqueantes
            ],
        )
    except UnidadeMedicoesNaoEncontrada as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if parsed.perfil.intervalo_min is None:
        raise HTTPException(status_code=422, detail="Intervalo não pôde ser determinado.")
    return ImportacaoMedicoesResponse(
        uc_id=uc_id,
        registros=len(parsed.registros),
        registros_afetados=affected,
        intervalo_min=parsed.perfil.intervalo_min,
        fonte=parsed.perfil.fonte,
        completude_pct=parsed.completude_pct,
        lacunas=parsed.lacunas,
        alertas=list(parsed.alertas),
    )


@router.get(
    "/unidades/{uc_id}/medicoes/resumo",
    response_model=ResumoMedicoesResponse,
)
def resumo_medicoes(
    uc_id: UUID,
    auth: MedicaoReader,
    session: Annotated[Session, Depends(get_session)],
    inicio: Annotated[date, Query()],
    fim: Annotated[date, Query()],
) -> ResumoMedicoesResponse:
    try:
        summary = obter_resumo_medicoes(
            session,
            organizacao_id=auth.user.organizacao_id,
            uc_id=uc_id,
            inicio=inicio,
            fim=fim,
        )
    except UnidadeMedicoesNaoEncontrada as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ParametrosAnaliseIndisponiveis as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except PeriodoMedicoesInvalido as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return ResumoMedicoesResponse.model_validate(summary)
