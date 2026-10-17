from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from typing import NamedTuple

import holidays
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Distribuidora, FeriadoNacional


class DistributorSeed(NamedTuple):
    sigla: str
    nome: str
    ufs: list[str]
    ponta_inicio: time | None = None
    ponta_fim: time | None = None


PRIORITY_DISTRIBUTORS = (
    DistributorSeed("ENEL_SP", "Enel Distribuição São Paulo", ["SP"], time(18), time(21)),
    DistributorSeed("ENEL_RJ", "Enel Distribuição Rio", ["RJ"]),
    DistributorSeed("EDP_SP", "EDP São Paulo", ["SP"], time(17, 30), time(20, 30)),
    DistributorSeed("EDP_ES", "EDP Espírito Santo", ["ES"]),
    DistributorSeed("CPFL_PAULISTA", "CPFL Paulista", ["SP"]),
    DistributorSeed("CPFL_PIRATININGA", "CPFL Piratininga", ["SP"]),
    DistributorSeed("ELEKTRO", "Elektro", ["SP", "MG"]),
)


@dataclass(frozen=True)
class CatalogSeedResult:
    distributors_created: int
    holidays_created: int


def seed_reference_catalog(
    session: Session,
    *,
    years: list[int] | None = None,
    today: date | None = None,
) -> CatalogSeedResult:
    seed_year = today or date.today()
    target_years = sorted(set(years if years is not None else [seed_year.year, seed_year.year + 1]))
    if not target_years:
        raise ValueError("Informe ao menos um ano para semear feriados.")

    distributors_created = _seed_distributors(session)
    holidays_created = _seed_national_holidays(session, target_years)
    return CatalogSeedResult(
        distributors_created=distributors_created,
        holidays_created=holidays_created,
    )


def _seed_distributors(session: Session) -> int:
    created = 0
    for distributor in PRIORITY_DISTRIBUTORS:
        existing = session.scalar(
            select(Distribuidora).where(Distribuidora.sigla == distributor.sigla)
        )
        if existing is not None:
            continue
        session.add(
            Distribuidora(
                sigla=distributor.sigla,
                nome=distributor.nome,
                ufs=distributor.ufs,
                ponta_inicio=distributor.ponta_inicio,
                ponta_fim=distributor.ponta_fim,
                ponta_status="VALIDAR",
                tem_hint=False,
            )
        )
        created += 1
    session.flush()
    return created


def _seed_national_holidays(session: Session, years: list[int]) -> int:
    federal_holidays = holidays.country_holidays("BR", years=years, observed=True)
    created = 0
    for holiday_date, description in federal_holidays.items():
        existing = session.scalar(
            select(FeriadoNacional).where(FeriadoNacional.data == holiday_date)
        )
        if existing is not None:
            continue
        session.add(
            FeriadoNacional(
                data=holiday_date,
                descricao=str(description),
                vale_para_ponta=False,
            )
        )
        created += 1
    session.flush()
    return created
