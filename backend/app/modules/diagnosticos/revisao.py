from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from app.core.audit import registrar_evento_auditoria
from app.db.models import Diagnostico, DiagnosticoAchado, SimulacaoACL
from sqlalchemy import select
from sqlalchemy.orm import Session

STATUS_RASCUNHO = "RASCUNHO"
STATUS_REVISADO = "REVISADO"
STATUS_PUBLICADO = "PUBLICADO"
STATUS_STALE = "STALE"


class DiagnosticoNaoEncontrado(LookupError):
    pass


class TransicaoDiagnosticoInvalida(ValueError):
    pass


def obter_diagnostico(
    session: Session,
    *,
    organizacao_id: UUID,
    diagnostico_id: UUID,
    somente_publicados: bool = False,
) -> Diagnostico:
    """Busca no tenant; perfis de leitura (CLIENTE) só enxergam diagnósticos publicados."""
    diagnostico = session.scalar(
        select(Diagnostico).where(
            Diagnostico.id == diagnostico_id, Diagnostico.organizacao_id == organizacao_id
        )
    )
    if diagnostico is None or (somente_publicados and diagnostico.status != STATUS_PUBLICADO):
        raise DiagnosticoNaoEncontrado("Diagnóstico não encontrado.")
    return diagnostico


def listar_achados(session: Session, diagnostico: Diagnostico) -> list[DiagnosticoAchado]:
    return list(
        session.scalars(
            select(DiagnosticoAchado)
            .where(
                DiagnosticoAchado.diagnostico_id == diagnostico.id,
                DiagnosticoAchado.organizacao_id == diagnostico.organizacao_id,
            )
            .order_by(DiagnosticoAchado.ordem)
        )
    )


def listar_simulacoes_acl(session: Session, diagnostico: Diagnostico) -> list[SimulacaoACL]:
    return list(
        session.scalars(
            select(SimulacaoACL)
            .where(
                SimulacaoACL.diagnostico_id == diagnostico.id,
                SimulacaoACL.organizacao_id == diagnostico.organizacao_id,
            )
            .order_by(SimulacaoACL.criado_em, SimulacaoACL.id)
        )
    )


def atualizar_notas(
    session: Session,
    *,
    organizacao_id: UUID,
    usuario_id: UUID,
    diagnostico_id: UUID,
    notas: str | None,
    ip: str | None = None,
) -> Diagnostico:
    diagnostico = obter_diagnostico(
        session, organizacao_id=organizacao_id, diagnostico_id=diagnostico_id
    )
    if diagnostico.status == STATUS_PUBLICADO:
        raise TransicaoDiagnosticoInvalida("Diagnóstico publicado não pode ser alterado.")
    antes = diagnostico.notas
    diagnostico.notas = notas
    registrar_evento_auditoria(
        session,
        organizacao_id=organizacao_id,
        usuario_id=usuario_id,
        acao="DIAGNOSTICO_NOTAS",
        entidade="diagnostico",
        entidade_id=str(diagnostico.id),
        antes={"notas": antes},
        depois={"notas": notas},
        ip=ip,
    )
    session.commit()
    return diagnostico


def revisar_diagnostico(
    session: Session,
    *,
    organizacao_id: UUID,
    usuario_id: UUID,
    diagnostico_id: UUID,
    ip: str | None = None,
) -> Diagnostico:
    diagnostico = obter_diagnostico(
        session, organizacao_id=organizacao_id, diagnostico_id=diagnostico_id
    )
    if diagnostico.status != STATUS_RASCUNHO:
        raise TransicaoDiagnosticoInvalida(
            f"Somente diagnósticos em RASCUNHO podem ser revisados (status atual: "
            f"{diagnostico.status})."
        )
    diagnostico.status = STATUS_REVISADO
    diagnostico.revisado_por = usuario_id
    diagnostico.revisado_em = datetime.now(UTC)
    registrar_evento_auditoria(
        session,
        organizacao_id=organizacao_id,
        usuario_id=usuario_id,
        acao="DIAGNOSTICO_REVISADO",
        entidade="diagnostico",
        entidade_id=str(diagnostico.id),
        antes={"status": STATUS_RASCUNHO},
        depois={"status": STATUS_REVISADO},
        ip=ip,
    )
    session.commit()
    return diagnostico
