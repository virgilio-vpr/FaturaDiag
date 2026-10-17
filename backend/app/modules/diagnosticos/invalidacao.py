from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from uuid import UUID

from app.core.audit import registrar_evento_auditoria
from app.db.models import Diagnostico
from app.modules.diagnosticos.revisao import STATUS_STALE
from sqlalchemy import ColumnElement, or_, select
from sqlalchemy.orm import Session

# Qualquer diagnóstico já gerado (inclusive publicado) perde validade se seus insumos mudarem.
STATUS_INVALIDAVEIS = ("RASCUNHO", "REVISADO", "PUBLICADO")


def invalidar_por_fatura(
    session: Session,
    *,
    organizacao_id: UUID,
    fatura_id: UUID,
    usuario_id: UUID | None,
    ip: str | None = None,
) -> list[Diagnostico]:
    """Marca STALE os diagnósticos cujo snapshot cita a fatura (`fontes.faturas`)."""
    diagnosticos = session.scalars(
        select(Diagnostico).where(
            Diagnostico.organizacao_id == organizacao_id,
            Diagnostico.status.in_(STATUS_INVALIDAVEIS),
            Diagnostico.insumos_snapshot["fontes"]["faturas"].contains([str(fatura_id)]),
        )
    ).all()
    return _marcar(session, diagnosticos, f"fatura:{fatura_id}", usuario_id, ip)


def invalidar_por_unidade(
    session: Session,
    *,
    organizacao_id: UUID,
    uc_id: UUID,
    motivo: str,
    usuario_id: UUID | None,
    inicio: date | None = None,
    fim: date | None = None,
    ip: str | None = None,
) -> list[Diagnostico]:
    """Invalida diagnósticos da UC; com `inicio`, só os que se sobrepõem a [inicio, fim].

    `fim=None` significa vigência em aberto.
    """
    consulta = select(Diagnostico).where(
        Diagnostico.organizacao_id == organizacao_id,
        Diagnostico.uc_id == uc_id,
        Diagnostico.status.in_(STATUS_INVALIDAVEIS),
    )
    if inicio is not None:
        consulta = consulta.where(Diagnostico.periodo_fim >= inicio)
        if fim is not None:
            consulta = consulta.where(Diagnostico.periodo_inicio <= fim)
    return _marcar(session, session.scalars(consulta).all(), motivo, usuario_id, ip)


def invalidar_por_parametro(
    session: Session,
    *,
    chave: str,
    vigencias: Sequence[tuple[date, date | None]],
) -> list[Diagnostico]:
    """Invalida, em todas as organizações, diagnósticos cuja data de referência cai nas vigências.

    A referência é `periodo_fim`, data usada ao congelar os parâmetros. Parâmetros são
    globais; por isso a ação é de sistema e a auditoria não registra usuário.
    """
    condicoes: list[ColumnElement[bool]] = []
    for inicio, fim in vigencias:
        dentro = Diagnostico.periodo_fim >= inicio
        condicoes.append(dentro if fim is None else dentro & (Diagnostico.periodo_fim < fim))
    if not condicoes:
        return []
    diagnosticos = session.scalars(
        select(Diagnostico).where(Diagnostico.status.in_(STATUS_INVALIDAVEIS), or_(*condicoes))
    ).all()
    return _marcar(session, diagnosticos, f"parametro:{chave}", None, None)


def _marcar(
    session: Session,
    diagnosticos: Sequence[Diagnostico],
    motivo: str,
    usuario_id: UUID | None,
    ip: str | None,
) -> list[Diagnostico]:
    for diagnostico in diagnosticos:
        antes = diagnostico.status
        diagnostico.status = STATUS_STALE
        registrar_evento_auditoria(
            session,
            organizacao_id=diagnostico.organizacao_id,
            usuario_id=usuario_id,
            acao="DIAGNOSTICO_STALE",
            entidade="diagnostico",
            entidade_id=str(diagnostico.id),
            antes={"status": antes},
            depois={"status": STATUS_STALE, "motivo": motivo},
            ip=ip,
        )
    return list(diagnosticos)
