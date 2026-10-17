from datetime import date, time

from app.db import SessionLocal
from app.db.models import Distribuidora, FeriadoNacional
from app.scripts.seed_catalogs import seed_reference_catalog
from sqlalchemy import select

EXPECTED_DISTRIBUTOR_SIGLAS = {
    "ENEL_SP",
    "ENEL_RJ",
    "EDP_SP",
    "EDP_ES",
    "CPFL_PAULISTA",
    "CPFL_PIRATININGA",
    "ELEKTRO",
}


def test_catalog_seed_creates_prioritized_distributors_with_pending_peak_validation() -> None:
    with SessionLocal() as session:
        result = seed_reference_catalog(session, years=[2026])
        distributors = session.scalars(select(Distribuidora)).all()
        by_sigla = {distributor.sigla: distributor for distributor in distributors}

        assert EXPECTED_DISTRIBUTOR_SIGLAS.issubset(by_sigla)
        assert by_sigla["ENEL_SP"].ponta_inicio == time(18, 0)
        assert by_sigla["ENEL_SP"].ponta_fim == time(21, 0)
        assert by_sigla["EDP_SP"].ponta_inicio == time(17, 30)
        assert by_sigla["EDP_SP"].ponta_fim == time(20, 30)
        assert by_sigla["EDP_ES"].ponta_inicio is None
        assert by_sigla["EDP_ES"].ponta_fim is None
        assert all(
            by_sigla[sigla].ponta_status == "VALIDAR" for sigla in EXPECTED_DISTRIBUTOR_SIGLAS
        )
        assert by_sigla["ELEKTRO"].ponta_inicio is None
        assert result.distributors_created == len(EXPECTED_DISTRIBUTOR_SIGLAS)
        session.rollback()


def test_catalog_seed_creates_national_holidays_and_is_idempotent() -> None:
    with SessionLocal() as session:
        first_result = seed_reference_catalog(session, years=[2026])
        holidays = session.scalars(
            select(FeriadoNacional).where(
                FeriadoNacional.data >= date(2026, 1, 1),
                FeriadoNacional.data < date(2027, 1, 1),
            )
        ).all()
        second_result = seed_reference_catalog(session, years=[2026])

        assert any(holiday.data == date(2026, 1, 1) for holiday in holidays)
        assert all(holiday.vale_para_ponta is False for holiday in holidays)
        assert first_result.holidays_created > 0
        assert second_result.distributors_created == 0
        assert second_result.holidays_created == 0
        session.rollback()


def test_catalog_seed_preserves_human_edits() -> None:
    with SessionLocal() as session:
        seed_reference_catalog(session, years=[2026])
        distributor = session.scalar(select(Distribuidora).where(Distribuidora.sigla == "ENEL_SP"))
        national_holiday = session.scalar(
            select(FeriadoNacional).where(FeriadoNacional.data == date(2026, 1, 1))
        )
        assert distributor is not None
        assert national_holiday is not None
        distributor.ponta_inicio = time(19, 0)
        distributor.ponta_status = "VALIDADO"
        national_holiday.vale_para_ponta = True

        seed_reference_catalog(session, years=[2026])

        assert distributor.ponta_inicio == time(19, 0)
        assert distributor.ponta_status == "VALIDADO"
        assert national_holiday.vale_para_ponta is True
        session.rollback()
