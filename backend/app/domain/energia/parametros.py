from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class ParametrosRegulatorios:
    tolerancia_ultrapassagem: Decimal
    multiplicador_ultrapassagem: Decimal
    fator_potencia_referencia: Decimal
    intervalo_apuracao_fp_min: int
    janela_indutiva: str
    janela_capacitiva: str
    demanda_minima_contratada_kw: Decimal
    modalidades_verde_elegiveis: tuple[str, ...]
    modalidades_azul_obrigatorias: tuple[str, ...]
    subgrupos_prioritarios: tuple[str, ...]
    carga_minima_as_kw: Decimal
    limite_varejista_kw: Decimal
    prazo_notificacao_migracao_acl_dias: int
    feriados_nacionais_ponta: tuple[date, ...]
    limiar_subutilizacao: Decimal
    tolerancia_divergencia_item_rs: Decimal
    distribuidoras_suportadas: tuple[str, ...]
    vigencia_referencia: date
    pendentes_validacao: tuple[str, ...]
