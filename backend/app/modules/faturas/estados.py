from __future__ import annotations

from uuid import UUID

from app.core.audit import registrar_evento_auditoria
from app.db.models import Fatura
from app.modules.diagnosticos.invalidacao import invalidar_por_fatura
from sqlalchemy.orm import Session

ENVIADA = "ENVIADA"
EXTRAINDO = "EXTRAINDO"
EXTRAIDA = "EXTRAIDA"
EM_REVISAO = "EM_REVISAO"
VALIDADA = "VALIDADA"
DIAGNOSTICADA = "DIAGNOSTICADA"
FALHA_EXTRACAO = "FALHA_EXTRACAO"

# Máquina de estados da fatura (§4.4).
TRANSICOES: dict[str, frozenset[str]] = {
    ENVIADA: frozenset({EXTRAINDO}),
    EXTRAINDO: frozenset({EXTRAIDA, FALHA_EXTRACAO}),
    EXTRAIDA: frozenset({EM_REVISAO, VALIDADA, EXTRAINDO}),
    EM_REVISAO: frozenset({VALIDADA, EXTRAINDO}),
    VALIDADA: frozenset({EM_REVISAO, DIAGNOSTICADA}),
    DIAGNOSTICADA: frozenset({EM_REVISAO}),
    FALHA_EXTRACAO: frozenset({EXTRAINDO, EM_REVISAO}),
}
EDITAVEIS = frozenset({EXTRAIDA, EM_REVISAO, VALIDADA, DIAGNOSTICADA, FALHA_EXTRACAO})


class TransicaoInvalidaError(Exception):
    def __init__(self, origem: str, destino: str) -> None:
        super().__init__(f"Transição de status inválida: {origem} → {destino}.")
        self.origem = origem
        self.destino = destino


def transicionar(
    session: Session,
    fatura: Fatura,
    destino: str,
    *,
    usuario_id: UUID | None,
    ip: str | None = None,
    motivo: str | None = None,
) -> None:
    origem = fatura.status
    if destino not in TRANSICOES.get(origem, frozenset()):
        raise TransicaoInvalidaError(origem, destino)
    fatura.status = destino
    depois: dict[str, object] = {"status": destino}
    if motivo:
        depois["motivo"] = motivo
    registrar_evento_auditoria(
        session,
        organizacao_id=fatura.organizacao_id,
        usuario_id=usuario_id,
        acao="FATURA_STATUS",
        entidade="fatura",
        entidade_id=str(fatura.id),
        antes={"status": origem},
        depois=depois,
        ip=ip,
    )
    if destino == EM_REVISAO and origem in (VALIDADA, DIAGNOSTICADA):
        invalidar_por_fatura(
            session,
            organizacao_id=fatura.organizacao_id,
            fatura_id=fatura.id,
            usuario_id=usuario_id,
            ip=ip,
        )
