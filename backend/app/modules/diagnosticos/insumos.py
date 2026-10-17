from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.domain.energia.diagnostico import InsumosDiagnostico, MesFatura
from app.domain.energia.modalidade import TarifasAzul, TarifasVerde
from app.domain.energia.tipos import Modalidade, Subgrupo

ZERO = Decimal(0)
HORAS_POR_DIA = 24


class InsumosInsuficientesError(ValueError):
    """Dados necessários ao motor ausentes; nada é estimado ou inventado (§17.4)."""

    def __init__(self, pendencias: Sequence[str]) -> None:
        super().__init__("Insumos insuficientes para o diagnóstico.")
        self.pendencias = tuple(pendencias)


@dataclass(frozen=True, slots=True)
class DadosFatura:
    referencia: date
    modalidade: str | None
    dias_faturados: int | None
    leitura_anterior: date | None
    leitura_atual: date | None
    dc_ponta_kw: Decimal | None
    dc_fora_ponta_kw: Decimal | None
    dc_unica_kw: Decimal | None
    dm_ponta_kw: Decimal | None
    dm_fora_ponta_kw: Decimal | None
    consumo_ponta_kwh: Decimal | None
    consumo_fora_ponta_kwh: Decimal | None
    icms_aliquota: Decimal | None
    pis_aliquota: Decimal | None
    cofins_aliquota: Decimal | None
    multa_juros: Decimal = ZERO


@dataclass(frozen=True, slots=True)
class DadosContrato:
    modalidade: str
    dc_ponta_kw: Decimal | None
    dc_fora_ponta_kw: Decimal | None
    dc_unica_kw: Decimal | None


@dataclass(frozen=True, slots=True)
class TarifasDisponiveis:
    azul: TarifasAzul | None
    verde: TarifasVerde | None


def _horas(f: DadosFatura) -> Decimal | None:
    if f.dias_faturados is not None and f.dias_faturados > 0:
        return Decimal(f.dias_faturados * HORAS_POR_DIA)
    if f.leitura_anterior is not None and f.leitura_atual is not None:
        dias = (f.leitura_atual - f.leitura_anterior).days
        if dias > 0:
            return Decimal(dias * HORAS_POR_DIA)
    return None


def _modalidade(
    faturas: Sequence[DadosFatura], contrato: DadosContrato | None
) -> Modalidade | None:
    for origem in (faturas[-1].modalidade, contrato.modalidade if contrato else None):
        if origem is not None:
            return Modalidade(origem)
    return None


def _mes(f: DadosFatura, modalidade: Modalidade, pendencias: list[str]) -> MesFatura:
    ref = f.referencia.strftime("%Y-%m")
    verde = modalidade is Modalidade.VERDE
    convencional = modalidade is Modalidade.CONVENCIONAL
    dm_p, dm_f = f.dm_ponta_kw, f.dm_fora_ponta_kw
    if verde:
        dm_p = dm_p if dm_p is not None else dm_f
        dm_f = dm_f if dm_f is not None else dm_p
    exigidos = {
        "demanda medida ponta": dm_p,
        "demanda medida fora de ponta": dm_f,
        "consumo ponta": f.consumo_ponta_kwh,
        "consumo fora de ponta": f.consumo_fora_ponta_kwh,
    }
    horas = _horas(f)
    if horas is None:
        horas = ZERO
        if not convencional:
            pendencias.append(f"{ref}: dias faturados ou datas de leitura ausentes")
    for nome, valor in exigidos.items():
        if valor is None and not convencional:
            pendencias.append(f"{ref}: {nome} ausente")
    pis_cofins = (
        f.pis_aliquota + f.cofins_aliquota
        if f.pis_aliquota is not None and f.cofins_aliquota is not None
        else None
    )
    return MesFatura(
        referencia=ref,
        horas=horas,
        dm_ponta_kw=dm_p if dm_p is not None else ZERO,
        dm_fora_ponta_kw=dm_f if dm_f is not None else ZERO,
        consumo_ponta_kwh=f.consumo_ponta_kwh if f.consumo_ponta_kwh is not None else ZERO,
        consumo_fora_ponta_kwh=(
            f.consumo_fora_ponta_kwh if f.consumo_fora_ponta_kwh is not None else ZERO
        ),
        multa_juros=f.multa_juros,
        pis_cofins=pis_cofins,
        icms=f.icms_aliquota if pis_cofins is not None else None,
    )


def montar_insumos(
    *,
    subgrupo: str,
    tipo_rede: str,
    faturas: Sequence[DadosFatura],
    contrato: DadosContrato | None,
    tarifas: TarifasDisponiveis,
) -> tuple[InsumosDiagnostico, tuple[str, ...]]:
    """Traduz faturas validadas, contrato e tarifas vigentes nos insumos do motor (§3.4)."""
    if not faturas:
        raise InsumosInsuficientesError(["Nenhuma fatura validada no período"])
    ordenadas = sorted(faturas, key=lambda f: f.referencia)
    modalidade = _modalidade(ordenadas, contrato)
    if modalidade is None:
        raise InsumosInsuficientesError(
            ["Modalidade tarifária não informada na fatura nem no contrato"]
        )

    premissas: list[str] = []
    mantidas = [f for f in ordenadas if f.modalidade in (None, modalidade.value)]
    excluidas = [f.referencia.strftime("%Y-%m") for f in ordenadas if f not in mantidas]
    if excluidas:
        premissas.append(
            f"Faturas de outra modalidade excluídas do cálculo: {', '.join(excluidas)}"
        )

    pendencias: list[str] = []
    meses = tuple(_mes(f, modalidade, pendencias) for f in mantidas)
    ultima = mantidas[-1]
    usar_contrato = contrato if contrato and contrato.modalidade == modalidade.value else None

    def _dc(nome: str) -> Decimal | None:
        valor = getattr(ultima, nome)
        if valor is None and usar_contrato is not None:
            valor = getattr(usar_contrato, nome)
        return valor  # type: ignore[no-any-return]

    dc_p, dc_f, dc_u = _dc("dc_ponta_kw"), _dc("dc_fora_ponta_kw"), _dc("dc_unica_kw")
    if len({(f.dc_ponta_kw, f.dc_fora_ponta_kw, f.dc_unica_kw) for f in mantidas}) > 1:
        premissas.append(
            "Demanda contratada variou no período; o motor usa a da fatura mais recente"
        )
    if modalidade is Modalidade.VERDE:
        if dc_u is None:
            pendencias.append("Demanda contratada única ausente")
        if tarifas.verde is None:
            pendencias.append("Tarifas da modalidade Verde indisponíveis na vigência")
    elif modalidade is Modalidade.AZUL:
        if dc_p is None or dc_f is None:
            pendencias.append("Demandas contratadas de ponta e fora de ponta ausentes")
        if tarifas.azul is None:
            pendencias.append("Tarifas da modalidade Azul indisponíveis na vigência")
    if pendencias:
        raise InsumosInsuficientesError(pendencias)

    insumos = InsumosDiagnostico(
        subgrupo=Subgrupo(subgrupo),
        modalidade_atual=modalidade,
        meses=meses,
        dc_unica_kw=dc_u if modalidade is Modalidade.VERDE else None,
        dc_ponta_kw=dc_p if modalidade is Modalidade.AZUL else None,
        dc_fora_ponta_kw=dc_f if modalidade is Modalidade.AZUL else None,
        tarifas_verde=tarifas.verde,
        tarifas_azul=tarifas.azul,
        tipo_rede=tipo_rede,
    )
    return insumos, tuple(premissas)
