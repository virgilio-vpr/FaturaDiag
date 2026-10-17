from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal, InvalidOperation
from threading import Lock
from time import monotonic
from typing import cast
from uuid import UUID

from app.core.audit import registrar_evento_auditoria
from app.db.models import ParametroRegulatorio
from app.domain.energia.parametros import ParametrosRegulatorios
from app.modules.diagnosticos.invalidacao import invalidar_por_parametro
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

SEED_VALID_FROM = date(2026, 10, 10)
_CACHE_TTL_SECONDS = 60
_WINDOW_PATTERN = re.compile(
    r"^((?:[01][0-9]|2[0-3]|24):[0-5][0-9])-((?:[01][0-9]|2[0-3]|24):[0-5][0-9])$"
)


@dataclass(frozen=True, slots=True)
class ParameterDefinition:
    valor: object
    status: str
    fonte: str


PARAMETROS_INICIAIS: dict[str, ParameterDefinition] = {
    "tolerancia_ultrapassagem": ParameterDefinition(
        0.05, "VALIDAR", "REN ANEEL 1.000/2021 (condições gerais)"
    ),
    "multiplicador_ultrapassagem": ParameterDefinition(
        2,
        "VALIDAR",
        "Regra geral publicada pelas distribuidoras; períodos de testes têm regra própria",
    ),
    "fator_potencia_referencia": ParameterDefinition(
        0.92, "VALIDAR", "Grupo A, indutivo ou capacitivo; apuração horária"
    ),
    "intervalo_apuracao_fp_min": ParameterDefinition(60, "VALIDAR", ""),
    "janela_indutiva": ParameterDefinition("06:00-24:00", "VALIDAR", ""),
    "janela_capacitiva": ParameterDefinition("00:00-06:00", "VALIDAR", ""),
    "demanda_minima_contratada_kw": ParameterDefinition(30, "VALIDAR", "Grupo A"),
    "modalidades_verde_elegiveis": ParameterDefinition(
        ["A3a", "A4", "AS"], "VALIDAR", "PROJECT_SPEC.md §3.8"
    ),
    "modalidades_azul_obrigatorias": ParameterDefinition(
        ["A1", "A2", "A3"], "VALIDAR", "PROJECT_SPEC.md §3.8"
    ),
    "subgrupos_prioritarios": ParameterDefinition(
        ["A4", "AS"], "VALIDADO", "Parâmetro de negócio do MVP — PROJECT_SPEC.md §3.5"
    ),
    "carga_minima_as_kw": ParameterDefinition(75, "VALIDAR", "REN ANEEL 1.000/2021, Art. 2º"),
    "limite_varejista_kw": ParameterDefinition(
        500, "VALIDAR", "Grupo A abaixo desse limite migra ao ACL via comercializador varejista"
    ),
    "prazo_notificacao_migracao_acl_dias": ParameterDefinition(
        90, "VALIDAR", "Decreto 13.097/2026"
    ),
    "feriados_nacionais_ponta": ParameterDefinition(
        [], "VALIDAR", "Define dias sem ponta; manter tabela editável"
    ),
    "limiar_subutilizacao": ParameterDefinition(
        0.85, "VALIDAR", "Heurística de consultoria, não regulatória"
    ),
    "tolerancia_divergencia_item_rs": ParameterDefinition(
        0.05, "VALIDAR", "Reconciliação de itens"
    ),
    "distribuidoras_suportadas": ParameterDefinition(
        [
            "ENEL_SP",
            "ENEL_RJ",
            "EDP_SP",
            "EDP_ES",
            "CPFL_PAULISTA",
            "CPFL_PIRATININGA",
            "ELEKTRO",
        ],
        "VALIDAR",
        "Distribuidoras com hints e validações específicas — PROJECT_SPEC.md §3.9",
    ),
}


class ParametroRegulatorioNaoEncontrado(LookupError):
    pass


class ParametroRegulatorioInvalido(ValueError):
    pass


class ParametroRegulatorioConflitante(ValueError):
    pass


_cache_lock = Lock()
_cache: dict[date, tuple[float, ParametrosRegulatorios]] = {}


def limpar_cache_parametros() -> None:
    with _cache_lock:
        _cache.clear()


def semear_parametros_regulatorios(
    session: Session,
    *,
    vigencia_inicio: date = SEED_VALID_FROM,
) -> int:
    created = 0
    for chave, definition in PARAMETROS_INICIAIS.items():
        exists = session.scalar(
            select(ParametroRegulatorio.id).where(
                ParametroRegulatorio.chave == chave,
                ParametroRegulatorio.vigencia_inicio == vigencia_inicio,
            )
        )
        if exists is not None:
            continue
        session.add(
            ParametroRegulatorio(
                chave=chave,
                valor=definition.valor,
                vigencia_inicio=vigencia_inicio,
                fonte=definition.fonte or None,
                status=definition.status,
            )
        )
        created += 1
    session.flush()
    if created:
        limpar_cache_parametros()
    return created


def listar_parametros_regulatorios(
    session: Session,
    *,
    data: date,
) -> list[ParametroRegulatorio]:
    statement = (
        select(ParametroRegulatorio)
        .where(
            ParametroRegulatorio.vigencia_inicio <= data,
            or_(
                ParametroRegulatorio.vigencia_fim.is_(None),
                ParametroRegulatorio.vigencia_fim > data,
            ),
        )
        .order_by(ParametroRegulatorio.chave)
    )
    records = list(session.scalars(statement).all())
    keys = [record.chave for record in records]
    duplicates = sorted({key for key in keys if keys.count(key) > 1})
    if duplicates:
        raise ParametroRegulatorioConflitante(
            f"Mais de uma versão vigente para: {', '.join(duplicates)}."
        )
    return list(records)


def gravar_parametro_regulatorio(
    session: Session,
    *,
    chave: str,
    valor: object,
    vigencia_inicio: date,
    vigencia_fim: date | None,
    fonte: str | None,
    status: str,
    usuario_id: UUID,
    organizacao_id: UUID,
    ip: str | None,
) -> ParametroRegulatorio:
    if chave not in PARAMETROS_INICIAIS:
        raise ParametroRegulatorioInvalido(f"Chave de parâmetro desconhecida: {chave}.")
    _validate_value(chave, valor)
    if vigencia_fim is not None and vigencia_fim <= vigencia_inicio:
        raise ParametroRegulatorioInvalido("vigencia_fim deve ser posterior a vigencia_inicio.")
    if status not in {"VALIDAR", "VALIDADO"}:
        raise ParametroRegulatorioInvalido("status deve ser VALIDAR ou VALIDADO.")
    if status == "VALIDADO" and not (fonte and fonte.strip()):
        raise ParametroRegulatorioInvalido("fonte é obrigatória para marcar um parâmetro VALIDADO.")

    versions = session.scalars(
        select(ParametroRegulatorio)
        .where(ParametroRegulatorio.chave == chave)
        .order_by(ParametroRegulatorio.vigencia_inicio)
    ).all()
    previous = max(
        (version for version in versions if version.vigencia_inicio < vigencia_inicio),
        key=lambda version: version.vigencia_inicio,
        default=None,
    )
    record = session.scalar(
        select(ParametroRegulatorio).where(
            ParametroRegulatorio.chave == chave,
            ParametroRegulatorio.vigencia_inicio == vigencia_inicio,
        )
    )
    for version in versions:
        if version.vigencia_inicio == vigencia_inicio:
            continue
        overlaps_new_version = (
            vigencia_fim is None or version.vigencia_inicio < vigencia_fim
        ) and (version.vigencia_fim is None or version.vigencia_fim > vigencia_inicio)
        is_auto_closed_previous = (
            previous is not None
            and version.id == previous.id
            and version.vigencia_inicio < vigencia_inicio
        )
        if overlaps_new_version and not is_auto_closed_previous:
            raise ParametroRegulatorioConflitante(
                f"A vigência do parâmetro {chave} sobrepõe outra versão."
            )
    before = _snapshot(record) if record is not None else None
    previous_before = _snapshot(previous)
    if previous is not None and (
        previous.vigencia_fim is None or previous.vigencia_fim > vigencia_inicio
    ):
        previous.vigencia_fim = vigencia_inicio
    validation = status == "VALIDADO"
    if record is None:
        record = ParametroRegulatorio(
            chave=chave,
            valor=valor,
            vigencia_inicio=vigencia_inicio,
            vigencia_fim=vigencia_fim,
            fonte=fonte,
            status=status,
            validado_por=usuario_id if validation else None,
            validado_em=datetime.now(UTC) if validation else None,
        )
        session.add(record)
    else:
        record.valor = valor
        record.vigencia_fim = vigencia_fim
        record.fonte = fonte
        record.status = status
        record.validado_por = usuario_id if validation else None
        record.validado_em = datetime.now(UTC) if validation else None
    session.flush()
    _invalidar_diagnosticos(session, chave, before, record)
    if previous is not None and previous_before != _snapshot(previous):
        registrar_evento_auditoria(
            session,
            organizacao_id=organizacao_id,
            usuario_id=usuario_id,
            acao="PARAMETRO_REGULATORIO_VIGENCIA_ENCERRADA",
            entidade="parametro_regulatorio",
            entidade_id=str(previous.id),
            antes=previous_before,
            depois=_snapshot(previous),
            ip=ip,
        )
    registrar_evento_auditoria(
        session,
        organizacao_id=organizacao_id,
        usuario_id=usuario_id,
        acao="PARAMETRO_REGULATORIO_ATUALIZADO",
        entidade="parametro_regulatorio",
        entidade_id=str(record.id),
        antes=before,
        depois=_snapshot(record),
        ip=ip,
    )
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        constraint_name = getattr(getattr(error.orig, "diag", None), "constraint_name", None)
        if constraint_name == "uq_parametro_regulatorio_versao":
            raise ParametroRegulatorioConflitante(
                f"Já existe uma versão de {chave} com início em {vigencia_inicio.isoformat()}."
            ) from error
        raise
    limpar_cache_parametros()
    return record


def carregar_parametros_regulatorios(
    session: Session,
    *,
    data: date,
    usar_cache: bool = True,
) -> ParametrosRegulatorios:
    now = monotonic()
    if usar_cache:
        with _cache_lock:
            cached = _cache.get(data)
            if cached is not None and cached[0] > now:
                return cached[1]

    records = listar_parametros_regulatorios(session, data=data)
    by_key = {record.chave: record for record in records}
    missing = sorted(set(PARAMETROS_INICIAIS) - set(by_key))
    if missing:
        raise ParametroRegulatorioNaoEncontrado(
            f"Parâmetros sem versão vigente em {data.isoformat()}: {', '.join(missing)}."
        )
    resolved = _to_immutable_parameters(data, by_key)
    if usar_cache:
        with _cache_lock:
            _cache[data] = (now + _CACHE_TTL_SECONDS, resolved)
    return resolved


def _to_immutable_parameters(
    data: date,
    records: dict[str, ParametroRegulatorio],
) -> ParametrosRegulatorios:
    values = {key: record.valor for key, record in records.items()}
    for key, value in values.items():
        _validate_value(key, value)
    decimals = {
        key: _as_decimal(values[key], key)
        for key in (
            "tolerancia_ultrapassagem",
            "multiplicador_ultrapassagem",
            "fator_potencia_referencia",
            "demanda_minima_contratada_kw",
            "carga_minima_as_kw",
            "limite_varejista_kw",
            "limiar_subutilizacao",
            "tolerancia_divergencia_item_rs",
        )
    }
    return ParametrosRegulatorios(
        **decimals,
        intervalo_apuracao_fp_min=cast(int, values["intervalo_apuracao_fp_min"]),
        janela_indutiva=cast(str, values["janela_indutiva"]),
        janela_capacitiva=cast(str, values["janela_capacitiva"]),
        modalidades_verde_elegiveis=tuple(cast(list[str], values["modalidades_verde_elegiveis"])),
        modalidades_azul_obrigatorias=tuple(
            cast(list[str], values["modalidades_azul_obrigatorias"])
        ),
        subgrupos_prioritarios=tuple(cast(list[str], values["subgrupos_prioritarios"])),
        prazo_notificacao_migracao_acl_dias=cast(
            int, values["prazo_notificacao_migracao_acl_dias"]
        ),
        feriados_nacionais_ponta=tuple(
            date.fromisoformat(day) for day in cast(list[str], values["feriados_nacionais_ponta"])
        ),
        distribuidoras_suportadas=tuple(cast(list[str], values["distribuidoras_suportadas"])),
        vigencia_referencia=data,
        pendentes_validacao=tuple(
            sorted(key for key, record in records.items() if record.status == "VALIDAR")
        ),
    )


def _validate_value(chave: str, valor: object) -> None:
    if chave in {
        "tolerancia_ultrapassagem",
        "multiplicador_ultrapassagem",
        "fator_potencia_referencia",
        "demanda_minima_contratada_kw",
        "carga_minima_as_kw",
        "limite_varejista_kw",
        "limiar_subutilizacao",
        "tolerancia_divergencia_item_rs",
    }:
        _as_decimal(valor, chave)
    elif chave in {"intervalo_apuracao_fp_min", "prazo_notificacao_migracao_acl_dias"}:
        if not isinstance(valor, int) or isinstance(valor, bool) or valor < 1:
            raise ParametroRegulatorioInvalido(f"{chave} deve ser um inteiro positivo.")
    elif chave in {"janela_indutiva", "janela_capacitiva"}:
        if not isinstance(valor, str):
            raise ParametroRegulatorioInvalido(f"{chave} deve ser uma janela HH:MM-HH:MM.")
        match = _WINDOW_PATTERN.fullmatch(valor)
        if match is None:
            raise ParametroRegulatorioInvalido(f"{chave} deve ser uma janela HH:MM-HH:MM.")
        for part in match.groups():
            if part == "24:00":
                continue
            try:
                time.fromisoformat(part)
            except ValueError as error:
                raise ParametroRegulatorioInvalido(f"{chave} contém horário inválido.") from error
    elif chave == "feriados_nacionais_ponta":
        if not isinstance(valor, list) or any(not isinstance(item, str) for item in valor):
            raise ParametroRegulatorioInvalido(f"{chave} deve ser uma lista de datas ISO.")
        try:
            [date.fromisoformat(item) for item in valor]
        except ValueError as error:
            raise ParametroRegulatorioInvalido(f"{chave} contém uma data inválida.") from error
    else:
        if (
            not isinstance(valor, list)
            or not valor
            or any(not isinstance(item, str) or not item.strip() for item in valor)
        ):
            raise ParametroRegulatorioInvalido(f"{chave} deve ser uma lista não vazia de textos.")


def _as_decimal(valor: object, chave: str) -> Decimal:
    if isinstance(valor, bool):
        raise ParametroRegulatorioInvalido(f"{chave} deve ser um número decimal.")
    try:
        result = Decimal(str(valor))
    except (InvalidOperation, ValueError) as error:
        raise ParametroRegulatorioInvalido(f"{chave} deve ser um número decimal.") from error
    if not result.is_finite():
        raise ParametroRegulatorioInvalido(f"{chave} deve ser um decimal finito.")
    return result


def _invalidar_diagnosticos(
    session: Session,
    chave: str,
    antes: dict[str, object] | None,
    record: ParametroRegulatorio,
) -> None:
    """Marca STALE diagnósticos congelados com a vigência alterada (valor, status ou período)."""
    campos = ("valor", "status", "vigencia_fim")
    if antes is not None and all(antes[campo] == getattr(record, campo) for campo in campos):
        return
    vigencias = [(record.vigencia_inicio, record.vigencia_fim)]
    if antes is not None:
        vigencias.append((record.vigencia_inicio, cast(date | None, antes["vigencia_fim"])))
    invalidar_por_parametro(session, chave=chave, vigencias=vigencias)


def _snapshot(record: ParametroRegulatorio | None) -> dict[str, object] | None:
    if record is None:
        return None
    return {
        "chave": record.chave,
        "valor": record.valor,
        "vigencia_inicio": record.vigencia_inicio,
        "vigencia_fim": record.vigencia_fim,
        "fonte": record.fonte,
        "status": record.status,
        "validado_por": record.validado_por,
        "validado_em": record.validado_em,
    }
