import csv
from datetime import date
from decimal import Decimal

import pytest
from app.db import SessionLocal
from app.db.models import Distribuidora, Tarifa
from app.modules.tarifas.importer import TariffImportError, import_aneel_tariffs
from app.scripts.seed_catalogs import seed_reference_catalog
from sqlalchemy import select

CSV_COLUMNS = [
    "DatGeracaoConjuntoDados",
    "DscREH",
    "SigAgente",
    "NumCNPJDistribuidora",
    "DatInicioVigencia",
    "DatFimVigencia",
    "DscBaseTarifaria",
    "DscSubGrupo",
    "DscModalidadeTarifaria",
    "DscClasse",
    "DscSubClasse",
    "DscDetalhe",
    "NomPostoTarifario",
    "DscUnidadeTerciaria",
    "SigAgenteAcessante",
    "VlrTUSD",
    "VlrTE",
]


def _csv_row(**overrides: str) -> dict[str, str]:
    row = {
        "DatGeracaoConjuntoDados": "2026-10-16",
        "DscREH": "RESOLUÇÃO HOMOLOGATÓRIA DE TESTE",
        "SigAgente": "CPFL-PAULISTA",
        "NumCNPJDistribuidora": "33050196000188",
        "DatInicioVigencia": "2024-01-01",
        "DatFimVigencia": "2024-06-30",
        "DscBaseTarifaria": "Tarifa de Aplicação",
        "DscSubGrupo": "A4",
        "DscModalidadeTarifaria": "Verde",
        "DscClasse": "Não se aplica",
        "DscSubClasse": "Não se aplica",
        "DscDetalhe": "Não se aplica",
        "NomPostoTarifario": "Não se aplica",
        "DscUnidadeTerciaria": "kW",
        "SigAgenteAcessante": "Não se aplica",
        "VlrTUSD": "3,25",
        "VlrTE": ",00",
    }
    row.update(overrides)
    return row


def _write_csv(path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=CSV_COLUMNS, delimiter=";")
        writer.writeheader()
        writer.writerows(rows)


def test_aneel_import_filters_maps_deduplicates_and_is_idempotent(tmp_path) -> None:
    with SessionLocal() as session:
        seed_reference_catalog(session, years=[2026])
        distributor = session.scalar(
            select(Distribuidora).where(Distribuidora.sigla == "CPFL_PAULISTA")
        )
        assert distributor is not None

        path = tmp_path / "aneel.csv"
        fora_ponta = _csv_row(
            NomPostoTarifario="Fora ponta",
            DscUnidadeTerciaria="MWh",
            VlrTUSD="10,25",
            VlrTE="200,50",
        )
        conflicting = _csv_row(
            NomPostoTarifario="Fora ponta",
            DscUnidadeTerciaria="MWh",
            VlrTUSD="10,26",
            VlrTE="200,50",
        )
        _write_csv(
            path,
            [
                _csv_row(),
                fora_ponta,
                fora_ponta,
                conflicting,
                _csv_row(DscBaseTarifaria="Base Econômica"),
                _csv_row(NomPostoTarifario="Intermediário"),
                _csv_row(DscClasse="Rural"),
                _csv_row(NumCNPJDistribuidora="00000000000000", SigAgente="Outra"),
            ],
        )

        report = import_aneel_tariffs(session, path)
        tariffs = session.scalars(
            select(Tarifa).where(Tarifa.distribuidora_id == distributor.id)
        ).all()
        by_component = {tariff.componente: tariff for tariff in tariffs}
        second_report = import_aneel_tariffs(session, path)

        assert report.csv_rows == 8
        assert report.eligible_source_rows == 4
        assert report.tariffs_inserted == 2
        assert report.tariffs_updated == 0
        assert report.tariffs_unchanged == 0
        assert report.duplicate_tariffs_in_source == 3
        assert report.conflicting_tariffs == 1
        assert dict(report.skipped_rows) == {
            "base_tarifaria_nao_aplicacao": 1,
            "distribuidora_fora_do_escopo": 1,
            "posto_nao_suportado": 1,
            "tarifa_por_classe_ou_detalhe": 1,
        }
        assert report.unmapped_distributors == ("Outra (00000000000000)",)
        assert by_component["TUSD_DEMANDA"].valor == Decimal("3.25")
        assert by_component["TUSD_DEMANDA"].unidade == "RS_KW"
        assert by_component["TUSD_DEMANDA"].vigencia_fim == date(2024, 7, 1)
        assert by_component["TE_CONSUMO"].valor == Decimal("200.50")
        assert by_component["TE_CONSUMO"].unidade == "RS_MWH"
        assert by_component["TE_CONSUMO"].posto == "FORA_PONTA"
        assert "TUSD_CONSUMO" not in by_component
        assert second_report.tariffs_inserted == 0
        assert second_report.tariffs_updated == 0
        assert second_report.tariffs_unchanged == 2

        corrected_path = tmp_path / "aneel-corrigido.csv"
        _write_csv(corrected_path, [_csv_row(VlrTUSD="3,50")])
        corrected_report = import_aneel_tariffs(session, corrected_path)
        corrected_tariff = session.scalar(
            select(Tarifa).where(
                Tarifa.distribuidora_id == distributor.id,
                Tarifa.componente == "TUSD_DEMANDA",
            )
        )
        assert corrected_report.tariffs_inserted == 0
        assert corrected_report.tariffs_updated == 1
        assert corrected_tariff is not None
        assert corrected_tariff.valor == Decimal("3.50")

        invalid_path = tmp_path / "aneel-invalido.csv"
        _write_csv(invalid_path, [_csv_row(DscBaseTarifaria="")])
        with pytest.raises(TariffImportError, match="DscBaseTarifaria vazio"):
            import_aneel_tariffs(session, invalid_path)

        session.rollback()
