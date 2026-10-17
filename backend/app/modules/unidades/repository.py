from __future__ import annotations

from uuid import UUID

from app.db.models import ContratoDemanda, UnidadeConsumidora
from app.db.repository import BaseRepository
from sqlalchemy import select
from sqlalchemy.orm import Session


class UnidadeRepository(BaseRepository[UnidadeConsumidora]):
    def __init__(self, session: Session, organizacao_id: UUID) -> None:
        super().__init__(session, UnidadeConsumidora, organizacao_id)

    def get_active(self, unidade_id: UUID) -> UnidadeConsumidora | None:
        statement = self.statement().where(
            UnidadeConsumidora.id == unidade_id,
            UnidadeConsumidora.deletado_em.is_(None),
        )
        return self.session.scalars(statement).one_or_none()

    def code_in_use(
        self,
        *,
        distribuidora_id: UUID,
        codigo_uc: str,
        excluding_id: UUID | None = None,
    ) -> bool:
        statement = select(UnidadeConsumidora.id).where(
            UnidadeConsumidora.organizacao_id == self.organizacao_id,
            UnidadeConsumidora.distribuidora_id == distribuidora_id,
            UnidadeConsumidora.codigo_uc == codigo_uc,
        )
        if excluding_id is not None:
            statement = statement.where(UnidadeConsumidora.id != excluding_id)
        return self.session.scalar(statement.limit(1)) is not None

    def list_for_customer(
        self,
        *,
        cliente_id: UUID,
        limit: int,
        cursor: UUID | None,
    ) -> tuple[list[UnidadeConsumidora], UUID | None]:
        statement = self.statement().where(
            UnidadeConsumidora.cliente_id == cliente_id,
            UnidadeConsumidora.deletado_em.is_(None),
        )
        if cursor is not None:
            statement = statement.where(UnidadeConsumidora.id > cursor)
        page = list(
            self.session.scalars(statement.order_by(UnidadeConsumidora.id).limit(limit + 1)).all()
        )
        has_more = len(page) > limit
        items = page[:limit]
        return items, items[-1].id if has_more and items else None


class ContratoRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_for_unit(self, unidade_id: UUID) -> list[ContratoDemanda]:
        statement = (
            select(ContratoDemanda)
            .where(ContratoDemanda.uc_id == unidade_id)
            .order_by(ContratoDemanda.vigencia_inicio.desc(), ContratoDemanda.id)
        )
        return list(self.session.scalars(statement).all())
