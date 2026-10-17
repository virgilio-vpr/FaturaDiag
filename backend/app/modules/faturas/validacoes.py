from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from app.integrations.llm.schemas import CategoriaItem, FaturaExtraida

CONFIANCA_MINIMA = 0.80
DIAS_FATURADOS_MIN, DIAS_FATURADOS_MAX = 25, 35
LIMITE_ITEM_INCONSISTENTE = Decimal("0.01")
SUBGRUPOS_SOMENTE_AZUL = frozenset({"A1", "A2", "A3"})
HORARIO_PONTA_EDP = ((17, 30), (20, 30))

_CAMPOS_CHAVE = (
    "subgrupo",
    "modalidade",
    "codigo_uc",
    "mes_referencia",
    "demanda_contratada_ponta_kw",
    "demanda_contratada_fora_ponta_kw",
    "demanda_contratada_unica_kw",
    "demanda_medida_ponta_kw",
    "demanda_medida_fora_ponta_kw",
    "consumo_ponta_kwh",
    "consumo_fora_ponta_kwh",
    "fator_potencia",
    "valor_total",
)
_GRANDEZAS_NAO_NEGATIVAS = (
    "demanda_contratada_ponta_kw",
    "demanda_contratada_fora_ponta_kw",
    "demanda_contratada_unica_kw",
    "demanda_medida_ponta_kw",
    "demanda_medida_fora_ponta_kw",
    "consumo_ponta_kwh",
    "consumo_fora_ponta_kwh",
    "reativo_ponta_kvarh",
    "reativo_fora_ponta_kvarh",
)
_HORARIO = re.compile(
    r"ponta\D{0,40}?(\d{1,2})\s*h\s*(\d{2})?\s*(?:às|as|a|-|–|—)\s*(\d{1,2})\s*h\s*(\d{2})?",
    re.IGNORECASE,
)


class Severidade(StrEnum):
    INFO = "INFO"
    AVISO = "AVISO"
    BLOQUEANTE = "BLOQUEANTE"


@dataclass(frozen=True)
class Alerta:
    codigo: str
    severidade: Severidade
    mensagem: str
    campo: str | None = None

    def como_dict(self) -> dict[str, object]:
        return {
            "codigo": self.codigo,
            "severidade": self.severidade.value,
            "mensagem": self.mensagem,
            "campo": self.campo,
        }


@dataclass(frozen=True)
class ContextoValidacao:
    tolerancia_divergencia_rs: Decimal
    uc_codigo: str | None = None
    distribuidora_sigla: str | None = None
    hint_especifico: bool = True
    fatura_duplicada: bool = False


def validar_extracao(extraida: FaturaExtraida, contexto: ContextoValidacao) -> list[Alerta]:
    alertas: list[Alerta] = []
    alertas += _soma_e_itens(extraida, contexto)
    alertas += _grandezas(extraida)
    alertas += _contrato(extraida)
    alertas += _modalidade_e_rede(extraida)
    alertas += _uc(extraida, contexto)
    alertas += _confianca(extraida)
    if contexto.fatura_duplicada:
        alertas.append(
            Alerta("DUPLICADA", Severidade.BLOQUEANTE, "Já existe fatura desta UC para o mês.")
        )
    if not contexto.hint_especifico:
        alertas.append(
            Alerta(
                "HINT_AUSENTE",
                Severidade.INFO,
                "Distribuidora sem hint específico; foi usado o hint genérico.",
            )
        )
    alertas += _condicionais(extraida, contexto)
    return alertas


def tem_bloqueante(alertas: list[Alerta]) -> bool:
    return any(a.severidade is Severidade.BLOQUEANTE for a in alertas)


def _soma_e_itens(extraida: FaturaExtraida, contexto: ContextoValidacao) -> list[Alerta]:
    alertas: list[Alerta] = []
    total = extraida.valor_total.valor
    if total is not None and extraida.itens:
        soma = sum((item.valor for item in extraida.itens), Decimal(0))
        if abs(soma - total) > contexto.tolerancia_divergencia_rs:
            alertas.append(
                Alerta(
                    "SOMA_ITENS_DIVERGE",
                    Severidade.BLOQUEANTE,
                    f"A soma dos itens ({soma}) difere do valor total ({total}).",
                    "valor_total",
                )
            )
    for indice, item in enumerate(extraida.itens, start=1):
        if item.quantidade is None or item.tarifa_unitaria is None or item.valor == 0:
            continue
        diferenca = abs(item.quantidade * item.tarifa_unitaria - item.valor) / abs(item.valor)
        if diferenca > LIMITE_ITEM_INCONSISTENTE:
            alertas.append(
                Alerta(
                    "ITEM_VALOR_INCONSISTENTE",
                    Severidade.AVISO,
                    f"Item {indice}: quantidade × tarifa difere do valor em mais de 1%.",
                    f"itens[{indice - 1}]",
                )
            )
    return alertas


def _grandezas(extraida: FaturaExtraida) -> list[Alerta]:
    alertas: list[Alerta] = []
    fp = extraida.fator_potencia.valor
    if fp is not None and not Decimal(0) < fp <= Decimal(1):
        alertas.append(
            Alerta(
                "FP_FORA_FAIXA",
                Severidade.BLOQUEANTE,
                "Fator de potência fora do intervalo (0, 1].",
                "fator_potencia",
            )
        )
    for nome in _GRANDEZAS_NAO_NEGATIVAS:
        valor = getattr(extraida, nome).valor
        if valor is not None and valor < 0:
            alertas.append(
                Alerta("VALOR_NEGATIVO", Severidade.BLOQUEANTE, f"{nome} é negativo.", nome)
            )
    dias = extraida.dias_faturados.valor
    if dias is not None and not DIAS_FATURADOS_MIN <= dias <= DIAS_FATURADOS_MAX:
        alertas.append(
            Alerta(
                "DIAS_FATURADOS_ATIPICO",
                Severidade.AVISO,
                f"{dias} dias faturados está fora de {DIAS_FATURADOS_MIN}–{DIAS_FATURADOS_MAX}.",
                "dias_faturados",
            )
        )
    return alertas


def _contrato(extraida: FaturaExtraida) -> list[Alerta]:
    ponta = extraida.demanda_contratada_ponta_kw.valor
    fora = extraida.demanda_contratada_fora_ponta_kw.valor
    unica = extraida.demanda_contratada_unica_kw.valor
    modalidade = extraida.modalidade.valor
    if modalidade == "AZUL":
        ausente = ponta is None or fora is None
    elif modalidade == "VERDE":
        ausente = unica is None
    else:
        ausente = ponta is None and fora is None and unica is None
    if not ausente:
        return []
    return [
        Alerta(
            "CONTRATO_AUSENTE",
            Severidade.BLOQUEANTE,
            "Demanda contratada não encontrada para a modalidade.",
            "demanda_contratada",
        )
    ]


def _modalidade_e_rede(extraida: FaturaExtraida) -> list[Alerta]:
    alertas: list[Alerta] = []
    subgrupo = extraida.subgrupo.valor
    modalidade = extraida.modalidade.valor
    if subgrupo in SUBGRUPOS_SOMENTE_AZUL and modalidade in ("VERDE", "CONVENCIONAL"):
        alertas.append(
            Alerta(
                "MODALIDADE_INCOMPATIVEL",
                Severidade.BLOQUEANTE,
                f"O subgrupo {subgrupo} só admite a modalidade Azul.",
                "modalidade",
            )
        )
    if modalidade == "CONVENCIONAL":
        alertas.append(
            Alerta(
                "MODALIDADE_NAO_SUPORTADA",
                Severidade.INFO,
                "Modalidade Convencional (em extinção) não é suportada pelo motor.",
                "modalidade",
            )
        )
    if subgrupo == "AS" and extraida.tipo_rede.valor != "SUBTERRANEA":
        alertas.append(
            Alerta(
                "TIPO_REDE_AS_INCONSISTENTE",
                Severidade.AVISO,
                "Subgrupo AS sem indicação de rede subterrânea.",
                "tipo_rede",
            )
        )
    return alertas


def _normalizar_codigo(codigo: str) -> str:
    limpo = re.sub(r"[^0-9A-Za-z]", "", codigo).upper()
    return limpo.lstrip("0") or limpo


def _uc(extraida: FaturaExtraida, contexto: ContextoValidacao) -> list[Alerta]:
    extraido = extraida.codigo_uc.valor
    if contexto.uc_codigo is None or extraido is None:
        return []
    if _normalizar_codigo(extraido) == _normalizar_codigo(contexto.uc_codigo):
        return []
    return [
        Alerta(
            "UC_DIVERGE_CADASTRO",
            Severidade.BLOQUEANTE,
            "O código da UC na fatura difere da UC selecionada.",
            "codigo_uc",
        )
    ]


def _confianca(extraida: FaturaExtraida) -> list[Alerta]:
    alertas: list[Alerta] = []
    for nome in _CAMPOS_CHAVE:
        campo = getattr(extraida, nome)
        if campo.valor is not None and campo.confianca < CONFIANCA_MINIMA:
            prefixo = "FP" if nome == "fator_potencia" else nome.upper()
            alertas.append(
                Alerta(
                    f"{prefixo}_BAIXA_CONFIANCA",
                    Severidade.AVISO,
                    f"Confiança abaixo de {CONFIANCA_MINIMA:.2f} em {nome}.",
                    nome,
                )
            )
    return alertas


def _condicionais(extraida: FaturaExtraida, contexto: ContextoValidacao) -> list[Alerta]:
    sigla = contexto.distribuidora_sigla
    if sigla is None or extraida.distribuidora.confianca < CONFIANCA_MINIMA:
        return []
    observacoes = " ".join(extraida.observacoes_extrator)
    alertas: list[Alerta] = []
    if sigla == "ELEKTRO":
        itens_cobranca = [
            i for i in extraida.itens if i.categoria != CategoriaItem.TRIBUTO_INFORMATIVO
        ]
        if any("CCI" not in i.descricao.upper() for i in itens_cobranca):
            alertas.append(
                Alerta(
                    "ELEKTRO_CCI_AUSENTE",
                    Severidade.AVISO,
                    "CCI não extraído para itens de cobrança.",
                    "itens",
                )
            )
    if sigla.startswith("CPFL_") and re.search(r"modelo\s+\"?pre[cç]o", observacoes, re.IGNORECASE):
        alertas.append(
            Alerta(
                "CPFL_MODELO_PRECO",
                Severidade.INFO,
                "Fatura no modelo 'Preço': tributos embutidos nos valores unitários.",
            )
        )
    if sigla.startswith("ENEL_") and "agrupamento" in observacoes.casefold():
        alertas.append(
            Alerta(
                "ENEL_AGRUPAMENTO_MULTIPLO",
                Severidade.AVISO,
                "Indício de múltiplas UCs faturadas em conjunto (AGRUPAMENTO).",
            )
        )
    if sigla.startswith("EDP_") and _horario_ponta_diverge(observacoes):
        alertas.append(
            Alerta(
                "EDP_HORARIO_PONTA",
                Severidade.AVISO,
                "Horário de ponta informado difere de 17h30–20h30.",
            )
        )
    return alertas


def _horario_ponta_diverge(observacoes: str) -> bool:
    achado = _HORARIO.search(observacoes)
    if achado is None:
        return False
    h1, m1, h2, m2 = achado.groups()
    informado = ((int(h1), int(m1 or 0)), (int(h2), int(m2 or 0)))
    return informado != HORARIO_PONTA_EDP
