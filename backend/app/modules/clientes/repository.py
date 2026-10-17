from __future__ import annotations

from uuid import UUID

from app.db.models import Cliente
from app.db.repository import BaseRepository
from sqlalchemy import or_, select
from sqlalchemy.orm import Session


class ClienteRepository(BaseRepository[Cliente]):
    def __init__(self, session: Session, organizacao_id: UUID) -> None:
        super().__init__(session, Cliente, organizacao_id)

    def get_active(self, cliente_id: UUID) -> Cliente | None:
        statement = self.statement().where(
            Cliente.id == cliente_id,
            Cliente.deletado_em.is_(None),
        )
        return self.session.scalars(statement).one_or_none()

    def cnpj_in_use(self, cnpj: str, *, excluding_id: UUID | None = None) -> bool:
        statement = select(Cliente.id).where(
            Cliente.organizacao_id == self.organizacao_id,
            Cliente.cnpj == cnpj,
        )
        if excluding_id is not None:
            statement = statement.where(Cliente.id != excluding_id)
        return self.session.scalar(statement.limit(1)) is not None

    def search_page(
        self,
        *,
        query: str | None,
        limit: int,
        cursor: UUID | None,
    ) -> tuple[list[Cliente], UUID | None]:
        statement = self.statement().where(Cliente.deletado_em.is_(None))
        if cursor is not None:
            statement = statement.where(Cliente.id > cursor)
        if query:
            escaped_query = (
                query.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            )
            pattern = f"%{escaped_query}%"
            statement = statement.where(
                or_(
                    Cliente.razao_social.ilike(pattern, escape="\\"),
                    Cliente.nome_fantasia.ilike(pattern, escape="\\"),
                    Cliente.cnpj.ilike(pattern, escape="\\"),
                )
            )

        statement = statement.order_by(Cliente.id).limit(limit + 1)
        page = list(self.session.scalars(statement).all())
        has_more = len(page) > limit
        items = page[:limit]
        next_cursor = items[-1].id if has_more and items else None
        return items, next_cursor
