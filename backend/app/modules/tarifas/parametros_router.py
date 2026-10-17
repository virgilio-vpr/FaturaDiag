from __future__ import annotations

from datetime import date
from typing import Annotated

from app.db import get_session
from app.modules.auth.rbac import Papel, requer_papel
from app.modules.auth.service import AuthContext
from app.modules.tarifas.parametros import (
    ParametroRegulatorioConflitante,
    ParametroRegulatorioInvalido,
    ParametroRegulatorioNaoEncontrado,
    carregar_parametros_regulatorios,
    gravar_parametro_regulatorio,
    listar_parametros_regulatorios,
)
from app.modules.tarifas.parametros_schemas import (
    ParametroRegulatorioResponse,
    ParametroRegulatorioUpdate,
    ParametrosRegulatoriosResponse,
)
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

router = APIRouter(prefix="/admin/parametros", tags=["parâmetros regulatórios"])
AdminActor = Annotated[AuthContext, Depends(requer_papel(Papel.ADMIN))]


@router.get("", response_model=ParametrosRegulatoriosResponse)
def get_regulatory_parameters(
    auth: AdminActor,
    session: Annotated[Session, Depends(get_session)],
    data: date | None = None,
) -> ParametrosRegulatoriosResponse:
    reference_date = data or date.today()
    try:
        records = listar_parametros_regulatorios(session, data=reference_date)
        parameters = carregar_parametros_regulatorios(session, data=reference_date)
    except ParametroRegulatorioConflitante as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except ParametroRegulatorioNaoEncontrado as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except ParametroRegulatorioInvalido as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error
    return ParametrosRegulatoriosResponse(
        data_referencia=reference_date,
        itens=[ParametroRegulatorioResponse.model_validate(record) for record in records],
        pendentes_validacao=list(parameters.pendentes_validacao),
    )


@router.put("", response_model=ParametroRegulatorioResponse)
def put_regulatory_parameter(
    request: Request,
    payload: ParametroRegulatorioUpdate,
    auth: AdminActor,
    session: Annotated[Session, Depends(get_session)],
) -> ParametroRegulatorioResponse:
    try:
        record = gravar_parametro_regulatorio(
            session,
            chave=payload.chave,
            valor=payload.valor,
            vigencia_inicio=payload.vigencia_inicio,
            vigencia_fim=payload.vigencia_fim,
            fonte=payload.fonte,
            status=payload.status,
            usuario_id=auth.user.id,
            organizacao_id=auth.user.organizacao_id,
            ip=request.client.host if request.client is not None else None,
        )
    except ParametroRegulatorioInvalido as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error
    except ParametroRegulatorioConflitante as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return ParametroRegulatorioResponse.model_validate(record)
