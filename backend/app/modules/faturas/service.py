from __future__ import annotations

import hashlib
from uuid import UUID, uuid4

import structlog
from app.core.audit import registrar_evento_auditoria
from app.db.models import Arquivo, Fatura
from app.integrations.storage import StorageBackend
from app.modules.faturas.arquivos import validar_arquivo
from app.modules.unidades.service import UnidadeNotFoundError, obter_unidade
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

logger = structlog.get_logger(__name__)


def registrar_upload(
    session: Session,
    storage: StorageBackend,
    *,
    organizacao_id: UUID,
    usuario_id: UUID,
    conteudo: bytes,
    unidade_id: UUID | None,
    idempotency_key: str | None,
    max_bytes: int,
    max_paginas: int,
    ip: str | None,
) -> Fatura:
    if idempotency_key:
        existente = session.scalar(
            select(Fatura).where(
                Fatura.organizacao_id == organizacao_id,
                Fatura.idempotency_key == idempotency_key,
            )
        )
        if existente is not None:
            return existente

    if unidade_id is not None:
        obter_unidade(session, organizacao_id=organizacao_id, unidade_id=unidade_id)

    validado = validar_arquivo(conteudo, max_bytes=max_bytes, max_paginas=max_paginas)
    sha256 = hashlib.sha256(conteudo).hexdigest()

    duplicado = session.scalar(
        select(Fatura)
        .join(Arquivo, Fatura.arquivo_id == Arquivo.id)
        .where(Arquivo.organizacao_id == organizacao_id, Arquivo.sha256 == sha256)
    )
    if duplicado is not None:
        return duplicado

    storage_key = f"{organizacao_id}/{uuid4()}.{validado.extensao}"
    storage.put(storage_key, validado.conteudo, validado.mime)
    try:
        arquivo = Arquivo(
            organizacao_id=organizacao_id,
            storage_key=storage_key,
            nome_original=None,
            mime=validado.mime,
            tamanho_bytes=len(validado.conteudo),
            sha256=sha256,
            criado_por=usuario_id,
        )
        session.add(arquivo)
        session.flush()
        fatura = Fatura(
            organizacao_id=organizacao_id,
            uc_id=unidade_id,
            arquivo_id=arquivo.id,
            idempotency_key=idempotency_key or None,
            status="ENVIADA",
        )
        session.add(fatura)
        session.flush()
        registrar_evento_auditoria(
            session,
            organizacao_id=organizacao_id,
            usuario_id=usuario_id,
            acao="FATURA_ENVIADA",
            entidade="fatura",
            entidade_id=str(fatura.id),
            antes=None,
            depois={"status": "ENVIADA", "arquivo_id": str(arquivo.id), "mime": validado.mime},
            ip=ip,
        )
        session.commit()
    except IntegrityError:
        session.rollback()
        storage.delete(storage_key)
        racing = session.scalar(
            select(Fatura).where(
                Fatura.organizacao_id == organizacao_id,
                Fatura.idempotency_key == idempotency_key,
            )
        )
        if racing is not None:
            return racing
        raise
    except Exception:
        session.rollback()
        storage.delete(storage_key)
        raise
    logger.info("fatura_enviada", fatura_id=str(fatura.id), mime=validado.mime)
    return fatura


__all__ = ["UnidadeNotFoundError", "registrar_upload"]
