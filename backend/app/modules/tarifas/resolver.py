from __future__ import annotations

from datetime import date
from uuid import UUID

from app.db.models import Tarifa
from sqlalchemy import or_, select
from sqlalchemy.orm import Session


class TarifaNaoEncontrada(LookupError):
    pass


class TarifaAmbiguaError(LookupError):
    pass


def resolver_tarifa(
    session: Session,
    *,
    distribuidora_id: UUID,
    subgrupo: str,
    modalidade: str,
    posto: str,
    componente: str,
    data: date,
) -> Tarifa:
    statement = (
        select(Tarifa)
        .where(
            Tarifa.distribuidora_id == distribuidora_id,
            Tarifa.subgrupo == subgrupo,
            Tarifa.modalidade == modalidade,
            Tarifa.posto == posto,
            Tarifa.componente == componente,
            Tarifa.vigencia_inicio <= data,
            or_(Tarifa.vigencia_fim.is_(None), Tarifa.vigencia_fim > data),
        )
        .limit(2)
    )
    tariffs = session.scalars(statement).all()
    if not tariffs:
        raise TarifaNaoEncontrada(
            f"Tarifa não encontrada para os critérios informados na data {data.isoformat()}."
        )
    if len(tariffs) > 1:
        raise TarifaAmbiguaError(
            f"Mais de uma tarifa corresponde aos critérios informados na data {data.isoformat()}."
        )
    return tariffs[0]
