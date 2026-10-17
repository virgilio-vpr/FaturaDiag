from __future__ import annotations

from datetime import date
from typing import Annotated, Any
from uuid import UUID

from app.core.errors import problem_response
from app.db import get_session
from app.db.models import Diagnostico
from app.domain.energia.acl import CenarioPreco, EntradaACL
from app.modules.auth.rbac import Papel, requer_papel
from app.modules.auth.service import AuthContext
from app.modules.diagnosticos import simulacoes
from app.modules.diagnosticos.insumos import InsumosInsuficientesError
from app.modules.diagnosticos.revisao import (
    DiagnosticoNaoEncontrado,
    TransicaoDiagnosticoInvalida,
    atualizar_notas,
    listar_achados,
    listar_simulacoes_acl,
    obter_diagnostico,
    revisar_diagnostico,
)
from app.modules.diagnosticos.schemas import (
    AchadoResponse,
    DiagnosticoCreate,
    DiagnosticoPatch,
    DiagnosticoResponse,
    SimulacaoACLPuraRequest,
    SimulacaoACLRequest,
    SimulacaoACLResponse,
    SimulacaoDemandaRequest,
    SimulacaoPuraResponse,
)
from app.modules.diagnosticos.service import (
    EscopoDiagnosticoInvalido,
    FaturaDiagnosticoNaoEncontrada,
    FaturaNaoValidadaError,
    ParametrosDiagnosticoIndisponiveis,
    TarifasDiagnosticoInvalidas,
    UnidadeDiagnosticoNaoEncontrada,
    criar_diagnostico,
)
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session
from starlette.responses import Response

router = APIRouter(tags=["diagnosticos"])
Escritor = Annotated[AuthContext, Depends(requer_papel(Papel.ADMIN, Papel.ANALISTA))]
Leitor = Annotated[AuthContext, Depends(requer_papel(Papel.ADMIN, Papel.ANALISTA, Papel.CLIENTE))]
DbSession = Annotated[Session, Depends(get_session)]


def _ip(request: Request) -> str | None:
    return request.client.host if request.client is not None else None


def _entrada_acl(corpo: SimulacaoACLRequest) -> tuple[EntradaACL, tuple[CenarioPreco, ...]]:
    entrada = EntradaACL(**corpo.entrada.model_dump())
    cenarios = tuple(CenarioPreco(c.nome, c.preco_rs_mwh) for c in corpo.cenarios)
    return entrada, cenarios


def _resposta(session: Session, diagnostico: Diagnostico) -> DiagnosticoResponse:
    snapshot: dict[str, Any] = diagnostico.insumos_snapshot
    resultado: dict[str, Any] = diagnostico.resultado
    return DiagnosticoResponse(
        id=diagnostico.id,
        uc_id=diagnostico.uc_id,
        escopo=diagnostico.escopo,
        periodo_inicio=diagnostico.periodo_inicio,
        periodo_fim=diagnostico.periodo_fim,
        status=diagnostico.status,
        versao_motor=diagnostico.versao_motor,
        economia_mensal_estimada=diagnostico.economia_mensal_estimada,
        economia_anual_estimada=diagnostico.economia_anual_estimada,
        notas=diagnostico.notas,
        criado_por=diagnostico.criado_por,
        revisado_por=diagnostico.revisado_por,
        revisado_em=diagnostico.revisado_em,
        criado_em=diagnostico.criado_em,
        resultado=resultado,
        fontes=snapshot.get("fontes", {}),
        premissas_montagem=resultado.get("premissas_montagem", []),
        parametros_pendentes=resultado.get("parametros_pendentes", []),
        achados=[AchadoResponse.model_validate(a) for a in listar_achados(session, diagnostico)],
        simulacoes_acl=[
            SimulacaoACLResponse.model_validate(s)
            for s in listar_simulacoes_acl(session, diagnostico)
        ],
    )


def _nao_encontrado(error: Exception) -> HTTPException:
    return HTTPException(status_code=404, detail=str(error))


@router.post("/diagnosticos", response_model=DiagnosticoResponse, status_code=201)
def post_diagnostico(
    corpo: DiagnosticoCreate,
    request: Request,
    auth: Escritor,
    session: DbSession,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key", max_length=128)] = None,
) -> DiagnosticoResponse | Response:
    acl, cenarios = (None, ()) if corpo.acl is None else _entrada_acl(corpo.acl)
    try:
        diagnostico = criar_diagnostico(
            session,
            organizacao_id=auth.user.organizacao_id,
            usuario_id=auth.user.id,
            uc_id=corpo.uc_id,
            escopo=corpo.escopo,
            fatura_id=corpo.fatura_id,
            periodo_inicio=corpo.periodo_inicio,
            periodo_fim=corpo.periodo_fim,
            idempotency_key=idempotency_key,
            acl=acl,
            cenarios_acl=cenarios,
            ip=_ip(request),
        )
    except InsumosInsuficientesError as error:
        return problem_response(
            request,
            status_code=422,
            title="Unprocessable Entity",
            detail=str(error),
            errors=[
                {"field": "insumos", "message": pendencia, "code": "insumos_insuficientes"}
                for pendencia in error.pendencias
            ],
        )
    except (UnidadeDiagnosticoNaoEncontrada, FaturaDiagnosticoNaoEncontrada) as error:
        raise _nao_encontrado(error) from error
    except (FaturaNaoValidadaError, ParametrosDiagnosticoIndisponiveis) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except (EscopoDiagnosticoInvalido, TarifasDiagnosticoInvalidas, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return _resposta(session, diagnostico)


@router.get("/diagnosticos/{diagnostico_id}", response_model=DiagnosticoResponse)
def get_diagnostico(diagnostico_id: UUID, auth: Leitor, session: DbSession) -> DiagnosticoResponse:
    try:
        diagnostico = obter_diagnostico(
            session,
            organizacao_id=auth.user.organizacao_id,
            diagnostico_id=diagnostico_id,
            somente_publicados=auth.user.papel == Papel.CLIENTE,
        )
    except DiagnosticoNaoEncontrado as error:
        raise _nao_encontrado(error) from error
    return _resposta(session, diagnostico)


@router.patch("/diagnosticos/{diagnostico_id}", response_model=DiagnosticoResponse)
def patch_diagnostico(
    diagnostico_id: UUID,
    corpo: DiagnosticoPatch,
    request: Request,
    auth: Escritor,
    session: DbSession,
) -> DiagnosticoResponse:
    try:
        diagnostico = atualizar_notas(
            session,
            organizacao_id=auth.user.organizacao_id,
            usuario_id=auth.user.id,
            diagnostico_id=diagnostico_id,
            notas=corpo.notas,
            ip=_ip(request),
        )
    except DiagnosticoNaoEncontrado as error:
        raise _nao_encontrado(error) from error
    except TransicaoDiagnosticoInvalida as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return _resposta(session, diagnostico)


@router.post("/diagnosticos/{diagnostico_id}/revisar", response_model=DiagnosticoResponse)
def post_revisar(
    diagnostico_id: UUID, request: Request, auth: Escritor, session: DbSession
) -> DiagnosticoResponse:
    try:
        diagnostico = revisar_diagnostico(
            session,
            organizacao_id=auth.user.organizacao_id,
            usuario_id=auth.user.id,
            diagnostico_id=diagnostico_id,
            ip=_ip(request),
        )
    except DiagnosticoNaoEncontrado as error:
        raise _nao_encontrado(error) from error
    except TransicaoDiagnosticoInvalida as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return _resposta(session, diagnostico)


@router.post(
    "/diagnosticos/{diagnostico_id}/simulacoes-acl",
    response_model=list[SimulacaoACLResponse],
    status_code=201,
)
def post_simulacao_acl_persistida(
    diagnostico_id: UUID,
    corpo: SimulacaoACLRequest,
    request: Request,
    auth: Escritor,
    session: DbSession,
) -> list[SimulacaoACLResponse]:
    entrada, cenarios = _entrada_acl(corpo)
    try:
        registros = simulacoes.persistir_simulacao_acl(
            session,
            organizacao_id=auth.user.organizacao_id,
            usuario_id=auth.user.id,
            diagnostico_id=diagnostico_id,
            entrada=entrada,
            cenarios=cenarios,
            ip=_ip(request),
        )
    except DiagnosticoNaoEncontrado as error:
        raise _nao_encontrado(error) from error
    except TransicaoDiagnosticoInvalida as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return [SimulacaoACLResponse.model_validate(r) for r in registros]


@router.post("/simulacoes/demanda", response_model=SimulacaoPuraResponse)
def post_simulacao_demanda(
    corpo: SimulacaoDemandaRequest, auth: Escritor, session: DbSession
) -> SimulacaoPuraResponse:
    del auth
    try:
        resultado = simulacoes.simular_demanda(
            session,
            simulacoes.EntradaDemanda(**corpo.model_dump(exclude={"data_referencia"})),
            corpo.data_referencia or date.today(),
        )
    except ParametrosDiagnosticoIndisponiveis as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return SimulacaoPuraResponse(resultado=resultado)


@router.post("/simulacoes/acl", response_model=SimulacaoPuraResponse)
def post_simulacao_acl(
    corpo: SimulacaoACLPuraRequest, auth: Escritor, session: DbSession
) -> SimulacaoPuraResponse:
    del auth
    entrada, cenarios = _entrada_acl(corpo)
    try:
        resultado = simulacoes.simular_acl_sem_persistir(
            session, entrada, cenarios, corpo.data_referencia or date.today()
        )
    except ParametrosDiagnosticoIndisponiveis as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return SimulacaoPuraResponse(resultado=resultado)
