"""Gera um PDF de exemplo (`make report-sample`) com dados FICTÍCIOS, só para inspeção visual.

Nenhuma tarifa ou parâmetro aqui é regulatório: servem apenas para exercitar o layout.
"""

from __future__ import annotations

import sys
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from app.domain.energia.acl import CenarioPreco, EntradaACL
from app.domain.energia.diagnostico import InsumosDiagnostico, MesFatura, diagnosticar
from app.domain.energia.modalidade import TarifasAzul, TarifasVerde
from app.domain.energia.parametros import ParametrosRegulatorios
from app.domain.energia.tipos import Modalidade, Subgrupo
from app.domain.energia.trace import VERSAO_MOTOR
from app.modules.diagnosticos.snapshot import para_json
from app.reports.builder import DadosRelatorio, MarcaOrganizacao, renderizar_pdf

D = Decimal
SAIDA_PADRAO = Path("/tmp/faturadiag-relatorio-amostra.pdf")  # noqa: S108


def parametros_ficticios() -> ParametrosRegulatorios:
    return ParametrosRegulatorios(
        tolerancia_ultrapassagem=D("0.05"),
        multiplicador_ultrapassagem=D("2"),
        fator_potencia_referencia=D("0.92"),
        intervalo_apuracao_fp_min=60,
        janela_indutiva="06:00-24:00",
        janela_capacitiva="00:00-06:00",
        demanda_minima_contratada_kw=D("30"),
        modalidades_verde_elegiveis=("A3a", "A4", "AS"),
        modalidades_azul_obrigatorias=("A1", "A2", "A3"),
        subgrupos_prioritarios=("A4", "AS"),
        carga_minima_as_kw=D("75"),
        limite_varejista_kw=D("500"),
        prazo_notificacao_migracao_acl_dias=90,
        feriados_nacionais_ponta=(),
        limiar_subutilizacao=D("0.85"),
        tolerancia_divergencia_item_rs=D("0.05"),
        distribuidoras_suportadas=(),
        vigencia_referencia=date(2026, 1, 1),
        pendentes_validacao=("tolerancia_ultrapassagem",),
    )


def dados_amostra(marca: MarcaOrganizacao | None = None, versao: int = 1) -> DadosRelatorio:
    meses = tuple(
        MesFatura(
            referencia=f"2026-{m:02d}",
            horas=D("720"),
            dm_ponta_kw=D(250 + 5 * m),
            dm_fora_ponta_kw=D(300 + 8 * m),
            consumo_ponta_kwh=D("10000"),
            consumo_fora_ponta_kwh=D("90000"),
        )
        for m in range(1, 13)
    )
    insumos = InsumosDiagnostico(
        subgrupo=Subgrupo.A4,
        modalidade_atual=Modalidade.VERDE,
        meses=meses,
        dc_unica_kw=D("500"),
        tarifas_verde=TarifasVerde(D("40"), D("0.9"), D("0.4")),
        tarifas_azul=TarifasAzul(D("60"), D("20"), D("0.9"), D("0.4")),
        acl=EntradaACL(
            consumo_mwh_mes=D("100"),
            te_cativa_rs_mwh=D("300"),
            encargos_rs_mwh=D("20"),
            custos_fixos_mes=D("1000"),
        ),
        cenarios_acl=(
            CenarioPreco("conservador", D("280")),
            CenarioPreco("base", D("230")),
            CenarioPreco("otimista", D("200")),
        ),
    )
    parametros = parametros_ficticios()
    resultado = diagnosticar(insumos, parametros)
    resultado_json = {
        **cast(dict[str, Any], para_json(resultado)),
        "premissas_montagem": ["Dados fictícios de demonstração."],
        "parametros_pendentes": list(parametros.pendentes_validacao),
    }
    return DadosRelatorio(
        diagnostico_id="00000000-0000-0000-0000-000000000000",
        escopo="HISTORICO",
        periodo_inicio="2026-01-01",
        periodo_fim="2026-12-01",
        status="REVISADO",
        versao_motor=VERSAO_MOTOR,
        economia_anual_estimada=str(resultado.economia_anual_estimada),
        economia_mensal_estimada=str((resultado.economia_anual_estimada / 12).quantize(D("0.01"))),
        insumos=cast(dict[str, Any], para_json(insumos)),
        resultado=resultado_json,
        parametros=cast(dict[str, Any], para_json(parametros)),
        marca=marca
        or MarcaOrganizacao(
            nome="Consultoria Exemplo Ltda.",
            cnpj="00.000.000/0001-00",
            responsavel_tecnico_nome="Fulano de Tal",
            responsavel_tecnico_crea="CREA-XX 000000",
        ),
        versao_relatorio=versao,
        gerado_em=datetime(2026, 10, 18, 12, 0, tzinfo=UTC),
        cliente="Cliente Fictício S.A.",
        unidade="UC 0000000-0",
    )


def main() -> None:
    destino = Path(sys.argv[1]) if len(sys.argv) > 1 else SAIDA_PADRAO
    destino.write_bytes(renderizar_pdf(dados_amostra()))
    print(f"Relatório de amostra gravado em {destino}")


if __name__ == "__main__":
    main()
