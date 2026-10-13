from app.db import Base, SessionLocal
from app.db.mixins import SoftDeleteMixin, TenantMixin, TimestampMixin
from sqlalchemy import String, text
from sqlalchemy.orm import Mapped, mapped_column


class ExampleTenantModel(TenantMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "example_tenant_model"

    nome: Mapped[str] = mapped_column(String(100), nullable=False)


def test_database_session_can_connect_to_postgres() -> None:
    with SessionLocal() as session:
        result = session.execute(text("SELECT 1")).scalar_one()

    assert result == 1


def test_tenant_and_soft_delete_mixins_expose_expected_columns() -> None:
    columns = {column.name for column in ExampleTenantModel.__table__.columns}
    index_names = {index.name for index in ExampleTenantModel.__table__.indexes}

    assert {
        "id",
        "organizacao_id",
        "criado_em",
        "atualizado_em",
        "deletado_em",
        "nome",
    }.issubset(columns)
    assert "ix_example_tenant_model_organizacao_id" in index_names
    assert "ix_example_tenant_model_deletado_em" in index_names
    assert ExampleTenantModel.__table__.c["organizacao_id"].foreign_keys
