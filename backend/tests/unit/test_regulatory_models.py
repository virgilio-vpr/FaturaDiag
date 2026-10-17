from decimal import Decimal

from app.db.models import BandeiraTarifaria, HintDistribuidora, ParametroRegulatorio, Tarifa
from sqlalchemy.dialects.postgresql import JSONB


def test_tariff_model_uses_decimal_precision_and_specified_version_key() -> None:
    table = Tarifa.__table__
    unique_constraints = {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if constraint.name == "uq_tarifa_versao"
    }

    assert table.c.valor.type.precision == 18
    assert table.c.valor.type.scale == 6
    assert table.c.valor.type.python_type is Decimal
    assert unique_constraints == {
        (
            "distribuidora_id",
            "subgrupo",
            "modalidade",
            "posto",
            "componente",
            "vigencia_inicio",
        )
    }


def test_regulatory_tables_expose_versioning_and_validation_fields() -> None:
    parameter_columns = set(ParametroRegulatorio.__table__.c.keys())
    hint_columns = set(HintDistribuidora.__table__.c.keys())
    banner_columns = set(BandeiraTarifaria.__table__.c.keys())

    assert isinstance(ParametroRegulatorio.__table__.c.valor.type, JSONB)
    assert {
        "chave",
        "valor",
        "vigencia_inicio",
        "vigencia_fim",
        "status",
        "validado_por",
        "validado_em",
    }.issubset(parameter_columns)
    assert {
        "distribuidora_id",
        "versao",
        "arquivo_md",
        "vigencia_inicio",
        "vigencia_fim",
        "ativo",
    }.issubset(hint_columns)
    assert {"mes_referencia", "bandeira", "adicional_rs_mwh", "fonte"}.issubset(banner_columns)
