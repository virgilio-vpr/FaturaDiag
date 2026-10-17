from __future__ import annotations

import csv
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import UUID

from app.db.models import Distribuidora, Tarifa
from sqlalchemy import func, or_, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

ANEEL_TARIFF_DATASET_SOURCE = (
    "https://dadosabertos.aneel.gov.br/dataset/5a583f3e-1646-4f67-bf0f-69db4203e89e"
)

ANEEL_DISTRIBUTOR_CNPJ_TO_SIGLA = {
    "33050196000188": "CPFL_PAULISTA",
    "04172213000151": "CPFL_PIRATININGA",
    "02328280000197": "ELEKTRO",
    "61695227000193": "ENEL_SP",
    "33050071000158": "ENEL_RJ",
    "02302100000106": "EDP_SP",
    "28152650000171": "EDP_ES",
}

REQUIRED_COLUMNS = {
    "DscREH",
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
    "SigAgente",
    "VlrTUSD",
    "VlrTE",
}

SUBGROUPS_A = {"A1", "A2", "A3", "A3a", "A4", "AS"}
MODALITIES = {
    "Azul": "AZUL",
    "Verde": "VERDE",
    "Convencional": "CONVENCIONAL",
}
POSTS = {
    "Ponta": "PONTA",
    "Fora ponta": "FORA_PONTA",
    "Não se aplica": "UNICO",
}
UNITS = {
    "kW": ("RS_KW", "TUSD_DEMANDA"),
    "MWh": ("RS_MWH", "TUSD_CONSUMO"),
}
CLASSIFICATION_COLUMNS = (
    "DscBaseTarifaria",
    "DscSubGrupo",
    "DscModalidadeTarifaria",
    "DscClasse",
    "DscSubClasse",
    "DscDetalhe",
    "NomPostoTarifario",
    "DscUnidadeTerciaria",
)


class TariffImportError(ValueError):
    pass


@dataclass(frozen=True)
class TariffImportReport:
    csv_rows: int
    eligible_source_rows: int
    tariffs_inserted: int
    tariffs_updated: int
    tariffs_unchanged: int
    duplicate_tariffs_in_source: int
    conflicting_tariffs: int
    skipped_rows: tuple[tuple[str, int], ...]
    unmapped_distributors: tuple[str, ...]


@dataclass(frozen=True)
class _TariffEntry:
    distribuidora_id: UUID
    subgrupo: str
    modalidade: str
    posto: str
    componente: str
    unidade: str
    valor: Decimal
    vigencia_inicio: date
    vigencia_fim: date | None
    resolucao_homologatoria: str | None
    fonte: str

    @property
    def key(self) -> tuple[UUID, str, str, str, str, date]:
        return (
            self.distribuidora_id,
            self.subgrupo,
            self.modalidade,
            self.posto,
            self.componente,
            self.vigencia_inicio,
        )

    def as_mapping(self) -> dict[str, object]:
        return {
            "distribuidora_id": self.distribuidora_id,
            "subgrupo": self.subgrupo,
            "modalidade": self.modalidade,
            "posto": self.posto,
            "componente": self.componente,
            "unidade": self.unidade,
            "valor": self.valor,
            "vigencia_inicio": self.vigencia_inicio,
            "vigencia_fim": self.vigencia_fim,
            "resolucao_homologatoria": self.resolucao_homologatoria,
            "fonte": self.fonte,
        }

    def matches(self, tariff: Tarifa) -> bool:
        return (
            self.unidade == tariff.unidade
            and self.valor == tariff.valor
            and self.vigencia_fim == tariff.vigencia_fim
            and self.resolucao_homologatoria == tariff.resolucao_homologatoria
            and self.fonte == tariff.fonte
        )


def import_aneel_tariffs(
    session: Session,
    csv_path: Path,
    *,
    batch_size: int = 500,
) -> TariffImportReport:
    if batch_size < 1:
        raise ValueError("batch_size deve ser maior que zero.")

    distributors = session.scalars(
        select(Distribuidora).where(
            Distribuidora.sigla.in_(set(ANEEL_DISTRIBUTOR_CNPJ_TO_SIGLA.values()))
        )
    ).all()
    distributor_ids = {distributor.sigla: distributor.id for distributor in distributors}
    missing_distributors = set(ANEEL_DISTRIBUTOR_CNPJ_TO_SIGLA.values()) - set(distributor_ids)
    if missing_distributors:
        missing = ", ".join(sorted(missing_distributors))
        raise TariffImportError(
            "Catálogo de distribuidoras incompleto; execute o seed de catálogos antes da "
            f"importação. Ausentes: {missing}."
        )

    entries: dict[tuple[UUID, str, str, str, str, date], _TariffEntry] = {}
    conflicting_keys: set[tuple[UUID, str, str, str, str, date]] = set()
    skipped: Counter[str] = Counter()
    unmapped_distributors: set[str] = set()
    duplicate_tariffs = 0
    csv_rows = 0
    eligible_source_rows = 0

    with csv_path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source, delimiter=";")
        _validate_headers(reader.fieldnames, csv_path)
        for row in reader:
            csv_rows += 1
            line_number = reader.line_num
            _validate_row_shape(row, line_number)
            reason = _skip_reason(row)
            if reason is not None:
                skipped[reason] += 1
                continue

            cnpj = _field(row, "NumCNPJDistribuidora", line_number)
            sigla = ANEEL_DISTRIBUTOR_CNPJ_TO_SIGLA.get(cnpj)
            if sigla is None:
                name = _field(row, "SigAgente", line_number)
                unmapped_distributors.add(f"{name} ({cnpj})")
                skipped["distribuidora_fora_do_escopo"] += 1
                continue

            eligible_source_rows += 1
            distributor_id = distributor_ids[sigla]
            start = _parse_date(row, "DatInicioVigencia", line_number)
            end_inclusive = _parse_optional_date(row, "DatFimVigencia", line_number)
            end_exclusive = end_inclusive + timedelta(days=1) if end_inclusive is not None else None
            if end_exclusive is not None and end_exclusive <= start:
                raise TariffImportError(
                    f"Vigência final anterior ao início na linha {line_number}."
                )

            subgroup = _field(row, "DscSubGrupo", line_number)
            modality = MODALITIES[_field(row, "DscModalidadeTarifaria", line_number)]
            post = POSTS[_field(row, "NomPostoTarifario", line_number)]
            unit, demand_component = UNITS[_field(row, "DscUnidadeTerciaria", line_number)]
            resolution = _field(row, "DscREH", line_number) or None
            values = [("VlrTUSD", demand_component)]
            if unit == "RS_MWH":
                values.append(("VlrTE", "TE_CONSUMO"))

            for value_column, component in values:
                value = _parse_decimal(row, value_column, line_number)
                entry = _TariffEntry(
                    distribuidora_id=distributor_id,
                    subgrupo=subgroup,
                    modalidade=modality,
                    posto=post,
                    componente=component,
                    unidade=unit,
                    valor=value,
                    vigencia_inicio=start,
                    vigencia_fim=end_exclusive,
                    resolucao_homologatoria=resolution,
                    fonte=ANEEL_TARIFF_DATASET_SOURCE,
                )
                if entry.key in conflicting_keys:
                    continue
                previous = entries.get(entry.key)
                if previous is None:
                    entries[entry.key] = entry
                elif previous == entry:
                    duplicate_tariffs += 1
                else:
                    del entries[entry.key]
                    conflicting_keys.add(entry.key)

    mappings = [entry.as_mapping() for key, entry in entries.items() if key not in conflicting_keys]
    existing = _load_existing_tariffs(session, entries)
    tariffs_inserted = sum(1 for entry in entries.values() if entry.key not in existing)
    updated_keys = {
        entry.key
        for entry in entries.values()
        if entry.key in existing and not entry.matches(existing[entry.key])
    }
    tariffs_updated = len(updated_keys)
    tariffs_unchanged = len(entries) - tariffs_inserted - tariffs_updated

    for offset in range(0, len(mappings), batch_size):
        batch = mappings[offset : offset + batch_size]
        statement = insert(Tarifa).values(batch)
        excluded = statement.excluded
        session.execute(
            statement.on_conflict_do_update(
                constraint="uq_tarifa_versao",
                set_={
                    "unidade": excluded.unidade,
                    "valor": excluded.valor,
                    "vigencia_fim": excluded.vigencia_fim,
                    "resolucao_homologatoria": excluded.resolucao_homologatoria,
                    "fonte": excluded.fonte,
                    "importado_em": func.now(),
                    "atualizado_em": func.now(),
                },
                where=or_(
                    Tarifa.unidade.is_distinct_from(excluded.unidade),
                    Tarifa.valor.is_distinct_from(excluded.valor),
                    Tarifa.vigencia_fim.is_distinct_from(excluded.vigencia_fim),
                    Tarifa.resolucao_homologatoria.is_distinct_from(
                        excluded.resolucao_homologatoria
                    ),
                    Tarifa.fonte.is_distinct_from(excluded.fonte),
                ),
            )
        )

    for key in updated_keys:
        session.expire(existing[key])

    return TariffImportReport(
        csv_rows=csv_rows,
        eligible_source_rows=eligible_source_rows,
        tariffs_inserted=tariffs_inserted,
        tariffs_updated=tariffs_updated,
        tariffs_unchanged=tariffs_unchanged,
        duplicate_tariffs_in_source=duplicate_tariffs,
        conflicting_tariffs=len(conflicting_keys),
        skipped_rows=tuple(sorted(skipped.items())),
        unmapped_distributors=tuple(sorted(unmapped_distributors)),
    )


def _load_existing_tariffs(
    session: Session,
    entries: dict[tuple[UUID, str, str, str, str, date], _TariffEntry],
) -> dict[tuple[UUID, str, str, str, str, date], Tarifa]:
    keys = list(entries)
    existing: dict[tuple[UUID, str, str, str, str, date], Tarifa] = {}
    for offset in range(0, len(keys), 500):
        batch = keys[offset : offset + 500]
        tariffs = session.scalars(
            select(Tarifa).where(
                tuple_(
                    Tarifa.distribuidora_id,
                    Tarifa.subgrupo,
                    Tarifa.modalidade,
                    Tarifa.posto,
                    Tarifa.componente,
                    Tarifa.vigencia_inicio,
                ).in_(batch)
            )
        ).all()
        for tariff in tariffs:
            key = (
                tariff.distribuidora_id,
                tariff.subgrupo,
                tariff.modalidade,
                tariff.posto,
                tariff.componente,
                tariff.vigencia_inicio,
            )
            existing[key] = tariff
    return existing


def _validate_headers(fieldnames: Sequence[str] | None, csv_path: Path) -> None:
    actual = set(fieldnames or ())
    missing = sorted(REQUIRED_COLUMNS - actual)
    if missing:
        missing_columns = ", ".join(missing)
        raise TariffImportError(
            f"CSV {csv_path} não contém as colunas ANEEL necessárias: {missing_columns}."
        )


def _validate_row_shape(row: dict[str | None, str | None], line_number: int) -> None:
    if None in row:
        raise TariffImportError(f"A linha {line_number} tem mais campos que o cabeçalho CSV.")
    for name in CLASSIFICATION_COLUMNS:
        value = row.get(name)
        if value is None or not value.strip():
            raise TariffImportError(f"Campo {name} vazio na linha {line_number}.")


def _skip_reason(row: dict[str, str | None]) -> str | None:
    if row.get("DscBaseTarifaria") != "Tarifa de Aplicação":
        return "base_tarifaria_nao_aplicacao"
    if row.get("DscSubGrupo") not in SUBGROUPS_A:
        return "subgrupo_fora_do_grupo_a"
    if row.get("DscModalidadeTarifaria") not in MODALITIES:
        return "modalidade_nao_suportada"
    if (
        row.get("DscClasse") != "Não se aplica"
        or row.get("DscSubClasse") != "Não se aplica"
        or row.get("DscDetalhe") != "Não se aplica"
    ):
        return "tarifa_por_classe_ou_detalhe"
    if row.get("NomPostoTarifario") not in POSTS:
        return "posto_nao_suportado"
    if row.get("DscUnidadeTerciaria") not in UNITS:
        return "unidade_nao_suportada"
    return None


def _field(row: dict[str, str | None], name: str, line_number: int) -> str:
    value = row.get(name)
    if value is None:
        raise TariffImportError(f"Campo {name} ausente na linha {line_number}.")
    return value.strip()


def _parse_date(row: dict[str, str | None], name: str, line_number: int) -> date:
    value = _field(row, name, line_number)
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise TariffImportError(
            f"Data inválida no campo {name}, linha {line_number}: {value!r}."
        ) from error


def _parse_optional_date(row: dict[str, str | None], name: str, line_number: int) -> date | None:
    value = _field(row, name, line_number)
    return None if not value else _parse_date(row, name, line_number)


def _parse_decimal(row: dict[str, str | None], name: str, line_number: int) -> Decimal:
    value = _field(row, name, line_number)
    normalized = value.replace(".", "").replace(",", ".") if "," in value else value
    try:
        parsed = Decimal(normalized)
    except InvalidOperation as error:
        raise TariffImportError(
            f"Valor decimal inválido no campo {name}, linha {line_number}: {value!r}."
        ) from error
    if not parsed.is_finite():
        raise TariffImportError(f"Valor decimal não finito no campo {name}, linha {line_number}.")
    exponent = parsed.as_tuple().exponent
    if not isinstance(exponent, int):
        raise TariffImportError(f"Expoente decimal inválido no campo {name}, linha {line_number}.")
    if max(0, -exponent) > 6:
        raise TariffImportError(
            f"Valor decimal excede 6 casas no campo {name}, linha {line_number}."
        )
    integer_digits = max(0, len(parsed.as_tuple().digits) + exponent)
    if integer_digits > 12:
        raise TariffImportError(
            f"Valor decimal excede a precisão da tarifa no campo {name}, linha {line_number}."
        )
    return parsed
