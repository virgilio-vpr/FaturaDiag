from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from app.core.audit import registrar_evento_auditoria
from app.db.models import SimulacaoACL
from app.domain.energia.acl import CenarioPreco, EntradaACL, ResultadoACL, simular_acl
from app.domain.energia.demanda_otima import otimizar_azul, otimizar_verde
from app.domain.energia.parametros import ParametrosRegulatorios
from app.modules.diagnosticos import service
from app.modules.diagnosticos.revisao import (
    STATUS_STALE,
    TransicaoDiagnosticoInvalida,
    obter_diagnostico,
)
from app.modules.diagnosticos.snapshot import de_json, para_json
from sqlalchemy.orm import Session

CENARIOS_PERSISTIVEIS = ("CONSERVADOR", "BASE", "OTIMISTA")


class CenarioACLInvalido(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class EntradaDemanda:
    modalidade: str
    dm_ponta_kw: Sequence[Decimal]
    dm_fora_ponta_kw: Sequence[Decimal]
    tarifa_unica_rs_kw: Decimal | None = None
    tarifa_ponta_rs_kw: Decimal | None = None
    tarifa_fora_ponta_rs_kw: Decimal | None = None
    dc_atual_kw: Decimal | None = None
    dc_atual_ponta_kw: Decimal | None = None
    dc_atual_fora_ponta_kw: Decimal | None = None


def simular_demanda(
    session: Session, entrada: EntradaDemanda, data_referencia: date
) -> dict[str, Any]:
    """Otimiza a demanda sem persistir; tolerância e multiplicador vêm dos parâmetros."""
    parametros = service.carregar_parametros(session, data_referencia)
    tol = parametros.tolerancia_ultrapassagem
    mult = parametros.multiplicador_ultrapassagem
    minima = parametros.demanda_minima_contratada_kw
    if entrada.modalidade == "VERDE":
        if entrada.tarifa_unica_rs_kw is None:
            raise ValueError("Informe tarifa_unica_rs_kw para a modalidade Verde.")
        resultado: object = otimizar_verde(
            entrada.dm_ponta_kw,
            entrada.dm_fora_ponta_kw,
            entrada.tarifa_unica_rs_kw,
            tol,
            mult,
            minima,
            entrada.dc_atual_kw,
        )
    elif entrada.modalidade == "AZUL":
        if entrada.tarifa_ponta_rs_kw is None or entrada.tarifa_fora_ponta_rs_kw is None:
            raise ValueError(
                "Informe tarifa_ponta_rs_kw e tarifa_fora_ponta_rs_kw para a modalidade Azul."
            )
        resultado = otimizar_azul(
            entrada.dm_ponta_kw,
            entrada.dm_fora_ponta_kw,
            entrada.tarifa_ponta_rs_kw,
            entrada.tarifa_fora_ponta_rs_kw,
            tol,
            mult,
            minima,
            entrada.dc_atual_ponta_kw,
            entrada.dc_atual_fora_ponta_kw,
        )
    else:
        raise ValueError("Modalidade deve ser VERDE ou AZUL.")
    return {
        "modalidade": entrada.modalidade,
        "resultado": para_json(resultado),
        "parametros_pendentes": list(parametros.pendentes_validacao),
    }


def simular_acl_sem_persistir(
    session: Session,
    entrada: EntradaACL,
    cenarios: Sequence[CenarioPreco],
    data_referencia: date,
) -> dict[str, Any]:
    parametros = service.carregar_parametros(session, data_referencia)
    resultado = simular_acl(entrada, cenarios, parametros)
    return _serializar(resultado, parametros)


def persistir_simulacao_acl(
    session: Session,
    *,
    organizacao_id: UUID,
    usuario_id: UUID,
    diagnostico_id: UUID,
    entrada: EntradaACL,
    cenarios: Sequence[CenarioPreco],
    ip: str | None = None,
) -> list[SimulacaoACL]:
    """Persiste um registro por cenário, usando os parâmetros congelados no diagnóstico (P6)."""
    diagnostico = obter_diagnostico(
        session, organizacao_id=organizacao_id, diagnostico_id=diagnostico_id
    )
    if diagnostico.status == STATUS_STALE:
        raise TransicaoDiagnosticoInvalida(
            "Diagnóstico desatualizado (STALE); gere um novo diagnóstico."
        )
    nomes = [c.nome.upper() for c in cenarios]
    if len(set(nomes)) != len(nomes) or any(n not in CENARIOS_PERSISTIVEIS for n in nomes):
        raise CenarioACLInvalido(
            "Cenários persistidos devem ser únicos e ser: conservador, base ou otimista."
        )
    parametros = de_json(ParametrosRegulatorios, diagnostico.parametros_snapshot)
    resultado = simular_acl(entrada, cenarios, parametros)
    serializado = _serializar(resultado, parametros)
    premissas_base = cast(dict[str, Any], para_json(entrada))
    registros: list[SimulacaoACL] = []
    for cenario, calculado in zip(cenarios, resultado.cenarios, strict=True):
        registro = SimulacaoACL(
            organizacao_id=organizacao_id,
            diagnostico_id=diagnostico.id,
            cenario=cenario.nome.upper(),
            premissas={
                "entrada": premissas_base,
                "preco_rs_mwh": str(cenario.preco_rs_mwh),
                "parametros_pendentes": serializado["parametros_pendentes"],
            },
            resultado={
                "cenario": para_json(calculado),
                "break_even_rs_mwh": serializado["break_even_rs_mwh"],
                "sensibilidade": serializado["sensibilidade"],
                "checklist": serializado["checklist"],
                "trace": serializado["trace"],
            },
        )
        session.add(registro)
        registros.append(registro)
    session.flush()
    registrar_evento_auditoria(
        session,
        organizacao_id=organizacao_id,
        usuario_id=usuario_id,
        acao="SIMULACAO_ACL_CRIADA",
        entidade="diagnostico",
        entidade_id=str(diagnostico.id),
        depois={"cenarios": nomes},
        ip=ip,
    )
    session.commit()
    return registros


def _serializar(resultado: ResultadoACL, parametros: ParametrosRegulatorios) -> dict[str, Any]:
    dados = cast(dict[str, Any], para_json(resultado))
    dados["parametros_pendentes"] = list(parametros.pendentes_validacao)
    return dados
