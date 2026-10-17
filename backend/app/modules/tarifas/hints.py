from __future__ import annotations

from datetime import date
from uuid import UUID

from app.core.audit import registrar_evento_auditoria
from app.db.models import Distribuidora, HintDistribuidora
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


class HintNaoEncontrado(LookupError):
    pass


class HintAmbiguoError(LookupError):
    pass


class HintInvalidoError(ValueError):
    pass


class HintConflitanteError(ValueError):
    pass


def listar_hints(
    session: Session,
    *,
    distribuidora_id: UUID | None = None,
    data: date | None = None,
) -> list[HintDistribuidora]:
    statement = select(HintDistribuidora)
    if distribuidora_id is not None:
        statement = statement.where(HintDistribuidora.distribuidora_id == distribuidora_id)
    if data is not None:
        statement = statement.where(
            HintDistribuidora.vigencia_inicio <= data,
            (HintDistribuidora.vigencia_fim.is_(None) | (HintDistribuidora.vigencia_fim > data)),
        )
    statement = statement.order_by(
        HintDistribuidora.distribuidora_id,
        HintDistribuidora.vigencia_inicio,
    )
    hints = list(session.scalars(statement).all())
    if data is not None:
        _raise_if_ambiguous(hints, data=data)
    return hints


def resolver_hint(
    session: Session,
    *,
    distribuidora_id: UUID,
    data: date,
) -> HintDistribuidora | None:
    hints = session.scalars(
        select(HintDistribuidora).where(
            HintDistribuidora.distribuidora_id == distribuidora_id,
            HintDistribuidora.vigencia_inicio <= data,
            (HintDistribuidora.vigencia_fim.is_(None) | (HintDistribuidora.vigencia_fim > data)),
        )
    ).all()
    if len(hints) > 1:
        raise HintAmbiguoError(
            f"Mais de uma versão de hint vigente para a distribuidora {distribuidora_id} "
            f"em {data.isoformat()}."
        )
    return hints[0] if hints else None


def atualizar_hint(
    session: Session,
    *,
    distribuidora_id: UUID,
    versao: str,
    arquivo_md: str,
    usuario_id: UUID,
    organizacao_id: UUID,
    ip: str | None,
) -> HintDistribuidora:
    versao = versao.strip()
    _validate_version(versao)
    _validate_content(arquivo_md)
    record = session.scalar(
        select(HintDistribuidora).where(
            HintDistribuidora.distribuidora_id == distribuidora_id,
            HintDistribuidora.versao == versao,
        )
    )
    if record is None:
        raise HintNaoEncontrado(
            f"Versão {versao} do hint não encontrada para a distribuidora {distribuidora_id}."
        )

    before = _snapshot(record)
    record.arquivo_md = arquivo_md.strip()
    session.flush()
    _audit_hint_change(
        session,
        record=record,
        before=before,
        usuario_id=usuario_id,
        organizacao_id=organizacao_id,
        ip=ip,
        action="HINT_DISTRIBUIDORA_ATUALIZADO",
    )
    session.commit()
    return record


def versionar_hint(
    session: Session,
    *,
    distribuidora_id: UUID,
    versao: str,
    arquivo_md: str,
    vigencia_inicio: date,
    usuario_id: UUID,
    organizacao_id: UUID,
    ip: str | None,
) -> HintDistribuidora:
    versao = versao.strip()
    _validate_version(versao)
    _validate_content(arquivo_md)

    distributor = session.scalar(
        select(Distribuidora).where(Distribuidora.id == distribuidora_id).with_for_update()
    )
    if distributor is None:
        raise HintNaoEncontrado(f"Distribuidora {distribuidora_id} não encontrada.")

    versions = list(
        session.scalars(
            select(HintDistribuidora)
            .where(HintDistribuidora.distribuidora_id == distribuidora_id)
            .order_by(HintDistribuidora.vigencia_inicio)
            .with_for_update()
        ).all()
    )
    if any(version.versao == versao for version in versions):
        raise HintConflitanteError(f"A versão {versao} já existe para esta distribuidora.")

    previous = max(
        (version for version in versions if version.vigencia_inicio < vigencia_inicio),
        key=lambda version: version.vigencia_inicio,
        default=None,
    )
    next_version = min(
        (version for version in versions if version.vigencia_inicio > vigencia_inicio),
        key=lambda version: version.vigencia_inicio,
        default=None,
    )
    if previous is not None and (
        previous.vigencia_fim is None or previous.vigencia_fim > vigencia_inicio
    ):
        before = _snapshot(previous)
        previous.vigencia_fim = vigencia_inicio
        session.flush()
        _audit_hint_change(
            session,
            record=previous,
            before=before,
            usuario_id=usuario_id,
            organizacao_id=organizacao_id,
            ip=ip,
            action="HINT_DISTRIBUIDORA_VIGENCIA_ENCERRADA",
        )

    effective_end = next_version.vigencia_inicio if next_version is not None else None
    if next_version is not None and (
        next_version.vigencia_fim is not None and next_version.vigencia_fim <= vigencia_inicio
    ):
        raise HintConflitanteError("A nova vigência conflita com o intervalo da próxima versão.")

    record = HintDistribuidora(
        distribuidora_id=distribuidora_id,
        versao=versao,
        arquivo_md=arquivo_md.strip(),
        vigencia_inicio=vigencia_inicio,
        vigencia_fim=effective_end,
        ativo=False,
    )
    session.add(record)
    distributor.tem_hint = True
    try:
        session.flush()
        active_version = max(
            (version for version in [*versions, record] if version.vigencia_inicio <= date.today()),
            key=lambda version: version.vigencia_inicio,
            default=None,
        )
        for version in versions:
            should_be_active = version is active_version
            if version.ativo != should_be_active:
                before = _snapshot(version)
                version.ativo = should_be_active
                session.flush()
                _audit_hint_change(
                    session,
                    record=version,
                    before=before,
                    usuario_id=usuario_id,
                    organizacao_id=organizacao_id,
                    ip=ip,
                    action=(
                        "HINT_DISTRIBUIDORA_ATIVADO"
                        if should_be_active
                        else "HINT_DISTRIBUIDORA_DESATIVADO"
                    ),
                )
        record.ativo = active_version is record
        session.flush()
        _audit_hint_change(
            session,
            record=record,
            before=None,
            usuario_id=usuario_id,
            organizacao_id=organizacao_id,
            ip=ip,
            action="HINT_DISTRIBUIDORA_VERSIONADO",
        )
        session.commit()
    except IntegrityError as error:
        session.rollback()
        constraint_name = getattr(getattr(error.orig, "diag", None), "constraint_name", None)
        if constraint_name == "uq_hint_distribuidora_versao":
            raise HintConflitanteError(
                f"A versão {versao} já existe para esta distribuidora."
            ) from error
        raise
    return record


def _validate_version(versao: str) -> None:
    normalized = versao.strip()
    if not normalized or len(normalized) > 32:
        raise HintInvalidoError("versao deve conter de 1 a 32 caracteres.")
    if any(not (character.isalnum() or character in "-_.") for character in normalized):
        raise HintInvalidoError("versao pode conter apenas letras, números, ponto, hífen e '_'.")


def _validate_content(arquivo_md: str) -> None:
    if not arquivo_md.strip():
        raise HintInvalidoError("arquivo_md não pode ser vazio.")
    if len(arquivo_md) > 100_000:
        raise HintInvalidoError("arquivo_md deve ter no máximo 100.000 caracteres.")


def _raise_if_ambiguous(hints: list[HintDistribuidora], *, data: date) -> None:
    distributors = [hint.distribuidora_id for hint in hints]
    duplicates = sorted({item for item in distributors if distributors.count(item) > 1}, key=str)
    if duplicates:
        raise HintAmbiguoError(
            f"Mais de uma versão de hint vigente para as distribuidoras "
            f"{', '.join(map(str, duplicates))} em {data.isoformat()}."
        )


def _audit_hint_change(
    session: Session,
    *,
    record: HintDistribuidora,
    before: dict[str, object] | None,
    usuario_id: UUID,
    organizacao_id: UUID,
    ip: str | None,
    action: str,
) -> None:
    registrar_evento_auditoria(
        session,
        organizacao_id=organizacao_id,
        usuario_id=usuario_id,
        acao=action,
        entidade="hint_distribuidora",
        entidade_id=str(record.id),
        antes=before,
        depois=_snapshot(record),
        ip=ip,
    )


def _snapshot(record: HintDistribuidora) -> dict[str, object]:
    return {
        "id": record.id,
        "distribuidora_id": record.distribuidora_id,
        "versao": record.versao,
        "arquivo_md": record.arquivo_md,
        "vigencia_inicio": record.vigencia_inicio,
        "vigencia_fim": record.vigencia_fim,
        "ativo": record.ativo,
    }
