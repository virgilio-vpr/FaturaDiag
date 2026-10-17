from __future__ import annotations

import argparse
from pathlib import Path

import structlog

from app.core.logging import configure_logging
from app.core.settings import Settings
from app.db import SessionLocal
from app.modules.tarifas.importer import TariffImportError, import_aneel_tariffs

logger = structlog.get_logger(__name__)
DEFAULT_CSV_PATH = (
    Path(__file__).resolve().parents[3] / "tarifas-homologadas-distribuidoras-energia-eletrica.csv"
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Importa tarifas de aplicação do CSV da ANEEL.")
    parser.add_argument(
        "csv_path",
        nargs="?",
        type=Path,
        default=DEFAULT_CSV_PATH,
        help=f"CSV ANEEL (padrão: {DEFAULT_CSV_PATH})",
    )
    args = parser.parse_args()
    configure_logging(Settings().log_level)

    try:
        with SessionLocal.begin() as session:
            report = import_aneel_tariffs(session, args.csv_path)
    except TariffImportError as error:
        logger.error("aneel_tariff_import_failed", reason=str(error))
        raise SystemExit(2) from error

    logger.info(
        "aneel_tariff_import_completed",
        csv_path=str(args.csv_path),
        csv_rows=report.csv_rows,
        eligible_source_rows=report.eligible_source_rows,
        tariffs_inserted=report.tariffs_inserted,
        tariffs_updated=report.tariffs_updated,
        tariffs_unchanged=report.tariffs_unchanged,
        duplicate_tariffs_in_source=report.duplicate_tariffs_in_source,
        conflicting_tariffs=report.conflicting_tariffs,
        skipped_rows=dict(report.skipped_rows),
        unmapped_distributors=report.unmapped_distributors,
    )


if __name__ == "__main__":
    main()
