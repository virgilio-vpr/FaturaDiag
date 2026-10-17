from __future__ import annotations

from collections.abc import Callable, Mapping
from uuid import UUID, uuid4

import structlog
from app.core.audit import registrar_evento_auditoria
from app.db.models import Cliente, ContratoDemanda, Distribuidora, UnidadeConsumidora
from app.modules.clientes.repository import ClienteRepository
from app.modules.diagnosticos.invalidacao import invalidar_por_unidade
from app.modules.unidades.repository import ContratoRepository, UnidadeRepository
from app.modules.unidades.schemas import ContratoCreate, UnidadeCreate, UnidadeUpdate
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

MODALIDADES_VERDE_ELEGIVEIS = frozenset({"A3a", "A4", "AS"})
MODALIDADES_AZUL_OBRIGATORIAS = frozenset({"A1", "A2", "A3"})
MODALIDADES_CONVENCIONAL_LEGADAS = frozenset({"A3a", "A4", "AS"})
logger = structlog.get_logger(__name__)


class UnidadeNotFoundError(LookupError):
    pass


class CadastroValidationError(ValueError):
    pass


class UnidadeConflictError(ValueError):
    pass


def validar_elegibilidade_modalidade(subgrupo: str, modalidade: str) -> None:
    if subgrupo in MODALIDADES_AZUL_OBRIGATORIAS and modalidade != "AZUL":
        raise CadastroValidationError(f"Subgrupo {subgrupo} exige modalidade AZUL.")
    if modalidade == "VERDE" and subgrupo not in MODALIDADES_VERDE_ELEGIVEIS:
        raise CadastroValidationError(f"Modalidade VERDE não elegível para subgrupo {subgrupo}.")
    if modalidade == "CONVENCIONAL":
        if subgrupo not in MODALIDADES_CONVENCIONAL_LEGADAS:
            raise CadastroValidationError(
                f"Modalidade CONVENCIONAL não elegível para subgrupo {subgrupo}."
            )
        logger.warning("modalidade_nao_suportada", subgrupo=subgrupo)


def validar_tipo_rede_as(subgrupo: str, tipo_rede: str) -> None:
    if subgrupo == "AS" and tipo_rede != "SUBTERRANEA":
        raise CadastroValidationError("Subgrupo AS exige tipo de rede SUBTERRANEA.")


def listar_unidades(
    session: Session,
    *,
    organizacao_id: UUID,
    cliente_id: UUID,
    limit: int,
    cursor: UUID | None,
) -> tuple[list[UnidadeConsumidora], UUID | None]:
    _get_customer(session, organizacao_id, cliente_id)
    return UnidadeRepository(session, organizacao_id).list_for_customer(
        cliente_id=cliente_id,
        limit=limit,
        cursor=cursor,
    )


def criar_unidade(
    session: Session,
    *,
    organizacao_id: UUID,
    usuario_id: UUID,
    cliente_id: UUID,
    payload: UnidadeCreate,
    ip: str | None,
) -> UnidadeConsumidora:
    _get_customer(session, organizacao_id, cliente_id)
    distributor = session.get(Distribuidora, payload.distribuidora_id)
    if distributor is None:
        raise UnidadeNotFoundError("Distribuidora não encontrada.")
    validar_tipo_rede_as(payload.subgrupo.value, payload.tipo_rede.value)

    repository = UnidadeRepository(session, organizacao_id)
    if repository.code_in_use(
        distribuidora_id=payload.distribuidora_id,
        codigo_uc=payload.codigo_uc,
    ):
        raise UnidadeConflictError(
            "Já existe UC com este código para a distribuidora na organização."
        )

    unit = UnidadeConsumidora(
        id=uuid4(),
        organizacao_id=organizacao_id,
        cliente_id=cliente_id,
        distribuidora_id=payload.distribuidora_id,
        codigo_uc=payload.codigo_uc,
        apelido=payload.apelido,
        uf=payload.uf,
        municipio=payload.municipio,
        subgrupo=payload.subgrupo.value,
        tipo_rede=payload.tipo_rede.value,
        ambiente=payload.ambiente.value,
        tensao_kv=payload.tensao_kv,
        observacoes=payload.observacoes,
    )
    repository.add(unit)
    _persist_with_audit(
        session,
        organizacao_id=organizacao_id,
        usuario_id=usuario_id,
        acao="UNIDADE_CONSUMIDORA_CRIADA",
        entidade="unidade_consumidora",
        entidade_id=str(unit.id),
        depois=lambda: _unit_snapshot(unit),
        ip=ip,
    )
    return unit


def obter_unidade(
    session: Session,
    *,
    organizacao_id: UUID,
    unidade_id: UUID,
) -> UnidadeConsumidora:
    unit = UnidadeRepository(session, organizacao_id).get_active(unidade_id)
    if unit is None:
        raise UnidadeNotFoundError("Unidade consumidora não encontrada.")
    return unit


def atualizar_unidade(
    session: Session,
    *,
    organizacao_id: UUID,
    usuario_id: UUID,
    unidade_id: UUID,
    payload: UnidadeUpdate,
    ip: str | None,
) -> UnidadeConsumidora:
    repository = UnidadeRepository(session, organizacao_id)
    unit = repository.get_active(unidade_id)
    if unit is None:
        raise UnidadeNotFoundError("Unidade consumidora não encontrada.")

    changes = payload.model_dump(exclude_unset=True)
    subgrupo = changes.get("subgrupo", unit.subgrupo)
    tipo_rede = changes.get("tipo_rede", unit.tipo_rede)
    validar_tipo_rede_as(str(subgrupo), str(tipo_rede))
    codigo_uc = changes.get("codigo_uc")
    if codigo_uc is not None and repository.code_in_use(
        distribuidora_id=unit.distribuidora_id,
        codigo_uc=str(codigo_uc),
        excluding_id=unidade_id,
    ):
        raise UnidadeConflictError(
            "Já existe UC com este código para a distribuidora na organização."
        )

    before = _unit_snapshot(unit)
    alterou_insumos = any(
        campo in changes
        and getattr(changes[campo], "value", changes[campo]) != getattr(unit, campo)
        for campo in ("subgrupo", "tipo_rede")
    )
    for field, value in changes.items():
        setattr(unit, field, value.value if hasattr(value, "value") else value)
    if alterou_insumos:
        invalidar_por_unidade(
            session,
            organizacao_id=organizacao_id,
            uc_id=unit.id,
            motivo="unidade:subgrupo_ou_tipo_rede",
            usuario_id=usuario_id,
            ip=ip,
        )
    _persist_with_audit(
        session,
        organizacao_id=organizacao_id,
        usuario_id=usuario_id,
        acao="UNIDADE_CONSUMIDORA_ATUALIZADA",
        entidade="unidade_consumidora",
        entidade_id=str(unit.id),
        antes=before,
        depois=lambda: _unit_snapshot(unit),
        ip=ip,
    )
    return unit


def listar_contratos(
    session: Session, *, organizacao_id: UUID, unidade_id: UUID
) -> list[ContratoDemanda]:
    obter_unidade(session, organizacao_id=organizacao_id, unidade_id=unidade_id)
    return ContratoRepository(session).list_for_unit(unidade_id)


def criar_contrato(
    session: Session,
    *,
    organizacao_id: UUID,
    usuario_id: UUID,
    unidade_id: UUID,
    payload: ContratoCreate,
    ip: str | None,
) -> ContratoDemanda:
    unit = obter_unidade(session, organizacao_id=organizacao_id, unidade_id=unidade_id)
    modalidade = payload.modalidade.value
    validar_elegibilidade_modalidade(unit.subgrupo, modalidade)

    contract = ContratoDemanda(
        id=uuid4(),
        uc_id=unit.id,
        modalidade=modalidade,
        demanda_ponta_kw=payload.demanda_ponta_kw,
        demanda_fora_ponta_kw=payload.demanda_fora_ponta_kw,
        demanda_unica_kw=payload.demanda_unica_kw,
        vigencia_inicio=payload.vigencia_inicio,
        vigencia_fim=payload.vigencia_fim,
    )
    session.add(contract)
    invalidar_por_unidade(
        session,
        organizacao_id=organizacao_id,
        uc_id=unit.id,
        motivo=f"contrato:{contract.id}",
        usuario_id=usuario_id,
        inicio=payload.vigencia_inicio,
        fim=payload.vigencia_fim,
        ip=ip,
    )
    _persist_with_audit(
        session,
        organizacao_id=organizacao_id,
        usuario_id=usuario_id,
        acao="CONTRATO_DEMANDA_CRIADO",
        entidade="contrato_demanda",
        entidade_id=str(contract.id),
        depois=lambda: _contract_snapshot(contract),
        ip=ip,
    )
    return contract


def _get_customer(session: Session, organizacao_id: UUID, cliente_id: UUID) -> Cliente:
    customer = ClienteRepository(session, organizacao_id).get_active(cliente_id)
    if customer is None:
        raise UnidadeNotFoundError("Cliente não encontrado.")
    return customer


def _persist_with_audit(
    session: Session,
    *,
    organizacao_id: UUID,
    usuario_id: UUID,
    acao: str,
    entidade: str,
    entidade_id: str,
    depois: Callable[[], Mapping[str, object]],
    ip: str | None,
    antes: Mapping[str, object] | None = None,
) -> None:
    try:
        session.flush()
        registrar_evento_auditoria(
            session,
            organizacao_id=organizacao_id,
            usuario_id=usuario_id,
            acao=acao,
            entidade=entidade,
            entidade_id=entidade_id,
            antes=antes,
            depois=depois(),
            ip=ip,
        )
        session.commit()
    except IntegrityError as error:
        session.rollback()
        constraint_name = getattr(getattr(error.orig, "diag", None), "constraint_name", None)
        if constraint_name == "uq_unidade_distribuidora_codigo_organizacao":
            raise UnidadeConflictError(
                "Já existe UC com este código para a distribuidora na organização."
            ) from error
        if constraint_name and constraint_name.startswith(("ck_unidade_", "ck_contrato_")):
            raise CadastroValidationError(
                "Dados de UC ou contrato violam constraints de domínio."
            ) from error
        raise


def _unit_snapshot(unit: UnidadeConsumidora) -> dict[str, object]:
    return {
        "id": unit.id,
        "cliente_id": unit.cliente_id,
        "distribuidora_id": unit.distribuidora_id,
        "codigo_uc": unit.codigo_uc,
        "apelido": unit.apelido,
        "uf": unit.uf,
        "municipio": unit.municipio,
        "subgrupo": unit.subgrupo,
        "tipo_rede": unit.tipo_rede,
        "ambiente": unit.ambiente,
        "tensao_kv": unit.tensao_kv,
        "observacoes": unit.observacoes,
    }


def _contract_snapshot(contract: ContratoDemanda) -> dict[str, object]:
    return {
        "id": contract.id,
        "uc_id": contract.uc_id,
        "modalidade": contract.modalidade,
        "demanda_ponta_kw": contract.demanda_ponta_kw,
        "demanda_fora_ponta_kw": contract.demanda_fora_ponta_kw,
        "demanda_unica_kw": contract.demanda_unica_kw,
        "vigencia_inicio": contract.vigencia_inicio,
        "vigencia_fim": contract.vigencia_fim,
    }
