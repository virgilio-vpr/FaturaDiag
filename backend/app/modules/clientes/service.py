from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from app.core.audit import registrar_evento_auditoria
from app.db.models import Cliente
from app.modules.clientes.repository import ClienteRepository
from app.modules.clientes.schemas import ClienteCreate, ClienteUpdate
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


class ClienteNotFoundError(LookupError):
    pass


class ClienteConflictError(ValueError):
    pass


def listar_clientes(
    session: Session,
    *,
    organizacao_id: UUID,
    query: str | None,
    limit: int,
    cursor: UUID | None,
) -> tuple[list[Cliente], UUID | None]:
    repository = ClienteRepository(session, organizacao_id)
    return repository.search_page(query=query, limit=limit, cursor=cursor)


def obter_cliente(session: Session, *, organizacao_id: UUID, cliente_id: UUID) -> Cliente:
    customer = ClienteRepository(session, organizacao_id).get_active(cliente_id)
    if customer is None:
        raise ClienteNotFoundError
    return customer


def criar_cliente(
    session: Session,
    *,
    organizacao_id: UUID,
    usuario_id: UUID,
    payload: ClienteCreate,
    ip: str | None,
) -> Cliente:
    repository = ClienteRepository(session, organizacao_id)
    if payload.cnpj is not None and repository.cnpj_in_use(payload.cnpj):
        raise ClienteConflictError("Já existe cliente com este CNPJ na organização.")

    customer = Cliente(organizacao_id=organizacao_id, **payload.model_dump())
    repository.add(customer)
    session.flush()
    registrar_evento_auditoria(
        session,
        organizacao_id=organizacao_id,
        usuario_id=usuario_id,
        acao="CLIENTE_CRIADO",
        entidade="cliente",
        entidade_id=str(customer.id),
        depois=_snapshot(customer),
        ip=ip,
    )
    _commit(session)
    return customer


def atualizar_cliente(
    session: Session,
    *,
    organizacao_id: UUID,
    usuario_id: UUID,
    cliente_id: UUID,
    payload: ClienteUpdate,
    ip: str | None,
) -> Cliente:
    repository = ClienteRepository(session, organizacao_id)
    customer = repository.get_active(cliente_id)
    if customer is None:
        raise ClienteNotFoundError

    changes = payload.model_dump(exclude_unset=True)
    if "cnpj" in changes and changes["cnpj"] is not None:
        if repository.cnpj_in_use(cast(str, changes["cnpj"]), excluding_id=cliente_id):
            raise ClienteConflictError("Já existe cliente com este CNPJ na organização.")

    before = _snapshot(customer)
    for field, value in changes.items():
        setattr(customer, field, value)
    session.flush()
    registrar_evento_auditoria(
        session,
        organizacao_id=organizacao_id,
        usuario_id=usuario_id,
        acao="CLIENTE_ATUALIZADO",
        entidade="cliente",
        entidade_id=str(customer.id),
        antes=before,
        depois=_snapshot(customer),
        ip=ip,
    )
    _commit(session)
    return customer


def excluir_cliente(
    session: Session,
    *,
    organizacao_id: UUID,
    usuario_id: UUID,
    cliente_id: UUID,
    ip: str | None,
) -> None:
    customer = ClienteRepository(session, organizacao_id).get_active(cliente_id)
    if customer is None:
        raise ClienteNotFoundError

    before = _snapshot(customer)
    customer.deletado_em = datetime.now(UTC)
    session.flush()
    registrar_evento_auditoria(
        session,
        organizacao_id=organizacao_id,
        usuario_id=usuario_id,
        acao="CLIENTE_EXCLUIDO",
        entidade="cliente",
        entidade_id=str(customer.id),
        antes=before,
        depois=_snapshot(customer),
        ip=ip,
    )
    _commit(session)


def _snapshot(customer: Cliente) -> dict[str, object]:
    return {
        "id": customer.id,
        "organizacao_id": customer.organizacao_id,
        "razao_social": customer.razao_social,
        "nome_fantasia": customer.nome_fantasia,
        "cnpj": customer.cnpj,
        "segmento": customer.segmento,
        "observacoes": customer.observacoes,
        "deletado_em": customer.deletado_em,
    }


def _commit(session: Session) -> None:
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        constraint_name = getattr(getattr(error.orig, "diag", None), "constraint_name", None)
        if constraint_name == "uq_cliente_organizacao_cnpj":
            raise ClienteConflictError("Já existe cliente com este CNPJ na organização.") from error
        raise
