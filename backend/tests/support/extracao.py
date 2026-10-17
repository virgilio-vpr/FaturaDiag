from __future__ import annotations

from copy import deepcopy
from typing import Any


def campo(valor: Any, confianca: float = 0.95) -> dict[str, Any]:
    return {"valor": valor, "confianca": confianca, "evidencia": None, "pagina": 1}


def fatura_extraida_dict(**overrides: Any) -> dict[str, Any]:
    """Resposta sintética de extração (valores fictícios, não são tarifas reais)."""
    base: dict[str, Any] = {
        "distribuidora": campo("ENEL DISTRIBUIÇÃO SÃO PAULO"),
        "razao_social": campo("EMPRESA FICTICIA LTDA"),
        "cnpj": campo("00.000.000/0001-91"),
        "codigo_uc": campo("0012345678"),
        "uf": campo("SP"),
        "subgrupo": campo("A4"),
        "modalidade": campo("VERDE"),
        "tipo_rede": campo("AEREA"),
        "mes_referencia": campo("2026-03-01"),
        "leitura_anterior": campo("2026-02-03"),
        "leitura_atual": campo("2026-03-05"),
        "dias_faturados": campo(30),
        "vencimento": campo("2026-03-20"),
        "demanda_contratada_ponta_kw": campo(None, 0.0),
        "demanda_contratada_fora_ponta_kw": campo(None, 0.0),
        "demanda_contratada_unica_kw": campo("500.00"),
        "demanda_medida_ponta_kw": campo("300.00"),
        "demanda_medida_fora_ponta_kw": campo("450.00"),
        "consumo_ponta_kwh": campo("12000.000"),
        "consumo_fora_ponta_kwh": campo("90000.000"),
        "reativo_ponta_kvarh": campo("100.000"),
        "reativo_fora_ponta_kvarh": campo("500.000"),
        "fator_potencia": campo("0.9500"),
        "icms_aliquota_pct": campo("18.00"),
        "pis_aliquota_pct": campo("1.20"),
        "cofins_aliquota_pct": campo("5.50"),
        "bandeira": campo("VERDE"),
        "valor_total": campo("1000.00"),
        "itens": [
            {
                "descricao": "Demanda",
                "categoria": "DEMANDA",
                "posto": "UNICO",
                "unidade": "kW",
                "quantidade": "500.00",
                "tarifa_unitaria": "1.000000",
                "valor": "500.00",
            },
            {
                "descricao": "Consumo TUSD",
                "categoria": "CONSUMO_TUSD",
                "posto": "UNICO",
                "unidade": "kWh",
                "quantidade": "1000.000",
                "tarifa_unitaria": "0.500000",
                "valor": "500.00",
            },
        ],
        "observacoes_extrator": [],
    }
    resultado = deepcopy(base)
    resultado.update(overrides)
    return resultado
