from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from app.db import SessionLocal
from app.db.models import Distribuidora, Tarifa
from app.modules.tarifas.resolver import (
    TarifaAmbiguaError,
    TarifaNaoEncontrada,
    resolver_tarifa,
)


def test_tariff_resolver_observes_half_open_validity_and_open_end() -> None:
    with SessionLocal() as session:
        distributor = Distribuidora(
            sigla=f"TESTE_{uuid4().hex[:8]}",
            nome="Distribuidora de teste",
            ufs=["SP"],
        )
        session.add(distributor)
        session.flush()

        first_period = Tarifa(
            distribuidora_id=distributor.id,
            subgrupo="A4",
            modalidade="VERDE",
            posto="UNICO",
            componente="TUSD_DEMANDA",
            unidade="RS_KW",
            valor=Decimal("10.000000"),
            vigencia_inicio=date(2024, 1, 1),
            vigencia_fim=date(2024, 7, 1),
            fonte="teste",
        )
        second_period = Tarifa(
            distribuidora_id=distributor.id,
            subgrupo="A4",
            modalidade="VERDE",
            posto="UNICO",
            componente="TUSD_DEMANDA",
            unidade="RS_KW",
            valor=Decimal("12.000000"),
            vigencia_inicio=date(2024, 7, 1),
            vigencia_fim=None,
            fonte="teste",
        )
        session.add_all([first_period, second_period])
        session.flush()

        def resolve(on: date, *, componente: str = "TUSD_DEMANDA") -> Tarifa:
            return resolver_tarifa(
                session,
                distribuidora_id=distributor.id,
                subgrupo="A4",
                modalidade="VERDE",
                posto="UNICO",
                componente=componente,
                data=on,
            )

        assert resolve(date(2024, 1, 1)) is first_period
        assert resolve(date(2024, 6, 30)) is first_period
        assert resolve(date(2024, 7, 1)) is second_period
        assert resolve(date(2050, 1, 1)) is second_period
        with pytest.raises(TarifaNaoEncontrada, match="2023-12-31"):
            resolve(date(2023, 12, 31))
        with pytest.raises(TarifaNaoEncontrada):
            resolve(date(2024, 7, 1), componente="TE_CONSUMO")

        overlapping_period = Tarifa(
            distribuidora_id=distributor.id,
            subgrupo="A4",
            modalidade="VERDE",
            posto="UNICO",
            componente="TUSD_DEMANDA",
            unidade="RS_KW",
            valor=Decimal("11.000000"),
            vigencia_inicio=date(2024, 6, 1),
            vigencia_fim=date(2024, 8, 1),
            fonte="teste",
        )
        session.add(overlapping_period)
        session.flush()
        with pytest.raises(TarifaAmbiguaError):
            resolve(date(2024, 6, 15))
