from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import UUID as SQLAlchemyUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    __abstract__ = True

    id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        nullable=False,
    )
