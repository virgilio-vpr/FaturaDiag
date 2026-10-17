from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

from app.core.audit import registrar_evento_auditoria
from app.db.models import Arquivo, Cliente, Organizacao, Relatorio, UnidadeConsumidora
from app.integrations.storage import ObjetoNaoEncontrado, StorageBackend
from app.modules.diagnosticos.revisao import (
    STATUS_STALE,
    DiagnosticoNaoEncontrado,
    TransicaoDiagnosticoInvalida,
    listar_simulacoes_acl,
    obter_diagnostico,
)
from app.reports.builder import DadosRelatorio, MarcaOrganizacao, renderizar_pdf
from sqlalchemy import func, select
from sqlalchemy.orm import Session

TEMPLATE = "relatorio.html.j2"
MIME_PDF = "application/pdf"
MIMES_LOGO = {"image/png", "image/jpeg"}


class RelatorioNaoEncontrado(LookupError):
    pass


@dataclass(frozen=True, slots=True)
class RelatorioBaixado:
    conteudo: bytes
    nome: str


def _marca(session: Session, organizacao_id: UUID, storage: StorageBackend) -> MarcaOrganizacao:
    org = session.get(Organizacao, organizacao_id)
    if org is None:
        raise DiagnosticoNaoEncontrado("Organização não encontrada.")
    logo: bytes | None = None
    logo_mime: str | None = None
    if org.logo_arquivo_id is not None:
        arquivo = session.get(Arquivo, org.logo_arquivo_id)
        # O logo só vale se pertencer à própria organização e for imagem raster.
        if arquivo and arquivo.organizacao_id == organizacao_id and arquivo.mime in MIMES_LOGO:
            try:
                logo, logo_mime = storage.get(arquivo.storage_key), arquivo.mime
            except ObjetoNaoEncontrado:
                logo = None
    return MarcaOrganizacao(
        nome=org.nome,
        cnpj=org.cnpj,
        cor_primaria=org.cor_primaria,
        logo=logo,
        logo_mime=logo_mime,
        responsavel_tecnico_nome=org.responsavel_tecnico_nome,
        responsavel_tecnico_crea=org.responsavel_tecnico_crea,
    )


def gerar_relatorio(
    session: Session,
    storage: StorageBackend,
    *,
    organizacao_id: UUID,
    usuario_id: UUID,
    diagnostico_id: UUID,
    ip: str | None = None,
) -> Relatorio:
    """Gera nova versão do PDF a partir do snapshot, sem recalcular (§12.2)."""
    diagnostico = obter_diagnostico(
        session, organizacao_id=organizacao_id, diagnostico_id=diagnostico_id
    )
    if diagnostico.status == STATUS_STALE:
        raise TransicaoDiagnosticoInvalida(
            "Diagnóstico desatualizado (STALE); gere um novo diagnóstico."
        )
    # Bloqueia o diagnóstico para serializar a numeração de versões.
    session.execute(
        select(Relatorio.id).where(Relatorio.diagnostico_id == diagnostico.id).with_for_update()
    )
    versao = (
        session.scalar(
            select(func.max(Relatorio.versao)).where(Relatorio.diagnostico_id == diagnostico.id)
        )
        or 0
    ) + 1
    uc = session.get(UnidadeConsumidora, diagnostico.uc_id)
    cliente = session.get(Cliente, uc.cliente_id) if uc else None
    resultado = cast(dict[str, Any], diagnostico.resultado)
    insumos = cast(dict[str, Any], diagnostico.insumos_snapshot)
    simulacoes = [
        {"cenario": s.cenario, "resultado": s.resultado}
        for s in listar_simulacoes_acl(session, diagnostico)
    ]
    agora = datetime.now(UTC)
    dados = DadosRelatorio(
        diagnostico_id=str(diagnostico.id),
        escopo=diagnostico.escopo,
        periodo_inicio=diagnostico.periodo_inicio.isoformat(),
        periodo_fim=diagnostico.periodo_fim.isoformat(),
        status=diagnostico.status,
        versao_motor=diagnostico.versao_motor,
        economia_anual_estimada=str(diagnostico.economia_anual_estimada),
        economia_mensal_estimada=str(diagnostico.economia_mensal_estimada),
        insumos=cast(dict[str, Any], insumos["insumos"]),
        resultado=resultado,
        parametros=cast(dict[str, Any], diagnostico.parametros_snapshot),
        marca=_marca(session, organizacao_id, storage),
        versao_relatorio=versao,
        gerado_em=agora,
        cliente=cliente.razao_social if cliente else None,
        unidade=(uc.apelido or uc.codigo_uc) if uc else None,
        simulacoes_acl=simulacoes,
        notas=diagnostico.notas,
    )
    pdf = renderizar_pdf(dados)
    sha256 = hashlib.sha256(pdf).hexdigest()
    storage_key = f"{organizacao_id}/relatorios/{uuid4()}.pdf"
    storage.put(storage_key, pdf, MIME_PDF)
    try:
        arquivo = Arquivo(
            organizacao_id=organizacao_id,
            storage_key=storage_key,
            nome_original=f"diagnostico-{diagnostico.id}-v{versao}.pdf",
            mime=MIME_PDF,
            tamanho_bytes=len(pdf),
            sha256=sha256,
            criado_por=usuario_id,
        )
        session.add(arquivo)
        session.flush()
        relatorio = Relatorio(
            organizacao_id=organizacao_id,
            diagnostico_id=diagnostico.id,
            arquivo_id=arquivo.id,
            versao=versao,
            template=TEMPLATE,
            gerado_por=usuario_id,
            gerado_em=agora,
        )
        session.add(relatorio)
        session.flush()
        registrar_evento_auditoria(
            session,
            organizacao_id=organizacao_id,
            usuario_id=usuario_id,
            acao="relatorio.gerar",
            entidade="relatorio",
            entidade_id=str(relatorio.id),
            depois={
                "diagnostico_id": str(diagnostico.id),
                "versao": versao,
                "arquivo_id": str(arquivo.id),
                "sha256": sha256,
            },
            ip=ip,
        )
        session.commit()
    except Exception:
        session.rollback()
        storage.delete(storage_key)
        raise
    return relatorio


def baixar_relatorio(
    session: Session,
    storage: StorageBackend,
    *,
    organizacao_id: UUID,
    relatorio_id: UUID,
    somente_publicados: bool,
) -> RelatorioBaixado:
    relatorio = session.scalar(
        select(Relatorio).where(
            Relatorio.id == relatorio_id, Relatorio.organizacao_id == organizacao_id
        )
    )
    if relatorio is None:
        raise RelatorioNaoEncontrado("Relatório não encontrado.")
    try:
        obter_diagnostico(
            session,
            organizacao_id=organizacao_id,
            diagnostico_id=relatorio.diagnostico_id,
            somente_publicados=somente_publicados,
        )
    except DiagnosticoNaoEncontrado as error:
        raise RelatorioNaoEncontrado("Relatório não encontrado.") from error
    arquivo = session.get(Arquivo, relatorio.arquivo_id)
    if arquivo is None or arquivo.organizacao_id != organizacao_id:
        raise RelatorioNaoEncontrado("Relatório não encontrado.")
    try:
        conteudo = storage.get(arquivo.storage_key)
    except ObjetoNaoEncontrado as error:
        raise RelatorioNaoEncontrado("Relatório não encontrado.") from error
    return RelatorioBaixado(conteudo, arquivo.nome_original or f"relatorio-{relatorio.id}.pdf")
