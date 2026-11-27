"""Resolvedor de HardDataMention → ChartResolutionDraft (Agno) y orquestación a ChartsPackage."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta
from types import SimpleNamespace
from typing import Protocol, runtime_checkable

from agno.agent import Agent
from agno.exceptions import OutputCheckError
from agno.models.base import Model
from agno.run.base import RunStatus
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from tigani_broadcast.official_data_charts.catalog import (
    get_catalog_entry,
    is_valid_catalog_id,
    list_catalog_entries,
)
from tigani_broadcast.official_data_charts.guardrails import (
    AntiSubstitutionGuardrail,
    CatalogMembershipGuardrail,
    DateRangeGuardrail,
    normalize_label,
)
from tigani_broadcast.official_data_charts.metrics import (
    MetricsCalculationError,
    build_chart_narrative,
    compute_series_metrics,
)
from tigani_broadcast.official_data_charts.models import (
    CatalogEntry,
    ChartArtifact,
    ChartNarrative,
    ChartResolutionDraft,
    ChartsPackage,
    NarrativeMode,
    SeriesFrequency,
    SeriesObservation,
)
from tigani_broadcast.official_data_charts.providers.base import ProviderError
from tigani_broadcast.official_data_charts.providers.fetcher import SeriesFetcher
from tigani_broadcast.transcript_chapterizer.models import (
    ChapterizedTranscript,
    HardDataMention,
)

_NULLISH_CATALOG_IDS = frozenset({"", "none", "null", "quoted_only"})
# Fetch mínimo: 13 meses (~400d) para YTD/YoY; 48 meses para comparación de gestiones.
_TREND_FETCH_DAYS = 400
_TERM_COMPARISON_FETCH_DAYS = 1461  # ≈ 48 meses

# IDs del catálogo cerrado (para validar claves del fallback determinista).
SERIES_CATALOG: frozenset[str] = frozenset(entry.catalog_id for entry in list_catalog_entries())
_FOREIGN_INFLATION_TOKEN_MARKERS = frozenset({"eeuu", "usa", "brasil", "brazil", "ee.uu"})
_FOREIGN_INFLATION_PHRASES = ("estados unidos",)

RESOLVER_INSTRUCTIONS = "\n".join(
    (
        "Sos el resolvedor de menciones económicas para placas de noticiero.",
        "Recibís una HardDataMention, el contexto breve del capítulo, publish_date",
        "y el catálogo cerrado de indicadores verificables.",
        "Devolvé catalog_id, start_date, end_date, narrative_mode y rationale.",
        "Si la mención corresponde a un indicador exacto del catálogo,",
        "poné ese catalog_id (string exacto).",
        "Si es cifra puntual/coyuntural (licitación, swap, vencimiento, bono,",
        "porcentaje analítico) o un derivado no publicado (reservas netas),",
        "poné catalog_id=null.",
        "Clasificá narrative_mode según la intención del tramo (sin calcular números):",
        '- "trend_with_callout" (default): dato reciente, rebote, desaceleración o nivel',
        '  actual (ej. "la inflación subió al 2,2 %").',
        '- "ytd_focus": referencia explícita al año en curso',
        '  (ej. "en lo que va del año").',
        '- "term_comparison": comparación entre gobiernos, gestiones o perspectiva',
        '  histórica larga (ej. "frente al gobierno anterior").',
        "start_date y end_date son opcionales (YYYY-MM-DD); si faltan,",
        "Python completa el rango. end_date nunca posterior a publish_date.",
        "Nunca sustituyas reservas netas por ar_bcra_reservas_brutas.",
        "Nunca inventes un catalog_id fuera del listado.",
        "Nunca calcules ni inventes valores numéricos de KPIs.",
        "rationale en español, breve y fiel a la decisión.",
    )
)

RESOLVER_EXPECTED_OUTPUT = "\n".join(
    (
        "Objeto con catalog_id (ID del catálogo o null), start_date, end_date,",
        'narrative_mode ("trend_with_callout"|"ytd_focus"|"term_comparison") y rationale.',
        "Sin campo resolution_status: Python lo deriva.",
    )
)


class _LLMResolutionPayload(BaseModel):
    """Salida laxa del LLM. Python deriva ChartResolutionDraft y corre guardrails."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    catalog_id: str | None = Field(
        default=None,
        description="ID exacto del catálogo, o null si es dato citado / sin serie oficial.",
    )
    start_date: date | None = None
    end_date: date | None = None
    narrative_mode: NarrativeMode = "trend_with_callout"
    rationale: str = Field(min_length=1, max_length=240)


class ResolutionValidationError(ValueError):
    """El agente o un guardrail rechazó la resolución. Fail-closed por mención."""


@runtime_checkable
class MentionResolverEngine(Protocol):
    """Motor inyectable: Agno real en producción, fake en tests offline."""

    def resolve(
        self,
        mention: HardDataMention,
        chapter_context: str,
        publish_date: date,
    ) -> ChartResolutionDraft:
        """Propone verified_series o quoted_only para una mención."""
        ...


class AgnoMentionResolver:
    """Resolvedor Agno 3.2.1: esquema laxo del LLM + ensamblado/guardrails en Python."""

    def __init__(self, model: Model, *, max_retries: int = 1) -> None:
        if max_retries < 0:
            raise ResolutionValidationError("max_retries no puede ser negativo")
        _set_temperature_zero(model)
        self.max_retries = max_retries
        self.catalog = CatalogMembershipGuardrail()
        self.anti_substitution = AntiSubstitutionGuardrail()
        self.date_range = DateRangeGuardrail()
        self.guardrails = (self.catalog, self.anti_substitution, self.date_range)
        self.agent = Agent(
            model=model,
            output_schema=_LLMResolutionPayload,
            instructions=RESOLVER_INSTRUCTIONS,
            expected_output=RESOLVER_EXPECTED_OUTPUT,
            markdown=False,
            telemetry=False,
        )

    def resolve(
        self,
        mention: HardDataMention,
        chapter_context: str,
        publish_date: date,
    ) -> ChartResolutionDraft:
        self.anti_substitution.bind(mention.indicator_label)
        self.date_range.bind(publish_date)
        base_prompt = format_resolver_prompt(mention, chapter_context, publish_date)
        prompt = base_prompt
        last_error: ResolutionValidationError | None = None

        for attempt in range(self.max_retries + 1):
            try:
                content = _checked_content(self.agent, prompt, ())
                if not isinstance(content, _LLMResolutionPayload):
                    received = type(content).__name__
                    raise ResolutionValidationError(
                        f"el agente no devolvió un _LLMResolutionPayload (recibido: {received})"
                    )
                draft = draft_from_llm_payload(content, publish_date=publish_date)
                draft = _maybe_apply_catalog_fallback(
                    draft,
                    payload=content,
                    mention=mention,
                    chapter_context=chapter_context,
                    publish_date=publish_date,
                )
                _run_guardrails(draft, self.guardrails)
                return draft
            except ResolutionValidationError as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
                prompt = "\n".join(
                    (
                        base_prompt,
                        (
                            f"Tu respuesta anterior fue rechazada porque: {exc}. "
                            "Corregila o devolvé catalog_id=null."
                        ),
                    )
                )

        assert last_error is not None
        # El rescate de alias inequívocos (inflación/IPC, etc.) vive en
        # resolve_chapters_to_artifacts para no tapar fail-closed de fechas/guardrails
        # cuando se llama a resolve() en aislamiento.
        raise last_error


def fallback_match_series_key(indicator: str, context: str) -> str | None:
    """
    Match determinista de alias inequívocos cuando el LLM falló o eligió mal.

    Los alias (`inflacion`, `ipc`, `riesgo pais`, `dolar blue`, etc.) se buscan
    **solo** en `indicator` normalizado. `context` solo actúa como filtro negativo
    de alcance geográfico (EE. UU., Brasil, etc.), para no arrastrar menciones
    ajenas cuando el título del capítulo menciona "inflación".
    Solo devuelve claves que existen en SERIES_CATALOG.
    """
    indicator_norm = normalize_label(indicator)
    context_norm = normalize_label(context)
    if not indicator_norm:
        return None
    # Fail-closed: reservas netas nunca se sustituyen.
    if "reservas netas" in indicator_norm:
        return None

    candidate: str | None = None
    if "dolar blue" in indicator_norm:
        candidate = "ar_mkt_dolar_blue"
    elif "dolar oficial" in indicator_norm or "tipo de cambio oficial" in indicator_norm:
        candidate = "ar_bcra_dolar_mayorista"
    elif "riesgo pais" in indicator_norm or "embi" in indicator_norm:
        candidate = "ar_mkt_riesgo_pais"
    elif "emae" in indicator_norm or "actividad economica" in indicator_norm:
        candidate = "ar_indec_emae_mensual"
    elif "inflacion" in indicator_norm or "ipc" in indicator_norm:
        scope_blob = f"{indicator_norm} {context_norm}".strip()
        if _mentions_foreign_inflation(scope_blob):
            return None
        # Preferir señal del indicador: "interanual" explícito → serie YoY; si no, mensual.
        if (
            "interanual" in indicator_norm
            or "ano a ano" in indicator_norm
            or "yoy" in indicator_norm.split()
        ):
            candidate = "ar_indec_ipc_interanual"
        else:
            candidate = "ar_indec_ipc_mensual"

    if candidate is None:
        return None
    if candidate not in SERIES_CATALOG or not is_valid_catalog_id(candidate):
        return None
    return candidate


def _mentions_foreign_inflation(blob: str) -> bool:
    if any(phrase in blob for phrase in _FOREIGN_INFLATION_PHRASES):
        return True
    tokens = set(blob.replace(".", " ").split())
    return bool(tokens & _FOREIGN_INFLATION_TOKEN_MARKERS)


def _fallback_verified_draft(
    mention: HardDataMention,
    chapter_context: str,
    publish_date: date,
    *,
    narrative_mode: NarrativeMode,
    rationale: str,
) -> ChartResolutionDraft | None:
    """Construye un draft verified_series si el indicador es un alias inequívoco."""
    matched = fallback_match_series_key(mention.indicator_label, chapter_context)
    if matched is None:
        return None
    return draft_from_llm_payload(
        _LLMResolutionPayload(
            catalog_id=matched,
            narrative_mode=narrative_mode,
            rationale=rationale[:240] if rationale else "Match determinista de catálogo.",
        ),
        publish_date=publish_date,
    )


def _maybe_apply_catalog_fallback(
    draft: ChartResolutionDraft,
    *,
    payload: _LLMResolutionPayload,
    mention: HardDataMention,
    chapter_context: str,
    publish_date: date,
) -> ChartResolutionDraft:
    """
    Alias inequívocos del catálogo pisan la decisión del LLM.

    Cubre quoted_only / catalog_id=None / clave inexistente / clave válida pero
    incorrecta para el alias (p. ej. ar_indec_ipc_interanual ante "índice de inflación").
    Si el LLM ya eligió exactamente la clave del fallback, se conserva el draft
    (fechas/mode) para que los guardrails de rango sigan fallando fail-closed.
    """
    matched = fallback_match_series_key(mention.indicator_label, chapter_context)
    if matched is None:
        return draft
    if draft.catalog_id == matched:
        return draft
    return draft_from_llm_payload(
        _LLMResolutionPayload(
            catalog_id=matched,
            narrative_mode=payload.narrative_mode,
            rationale=payload.rationale,
        ),
        publish_date=publish_date,
    )


def draft_from_llm_payload(
    payload: _LLMResolutionPayload,
    *,
    publish_date: date,
) -> ChartResolutionDraft:
    """
    Deriva ChartResolutionDraft en Python.
    catalog_id vacío / none / null / quoted_only → quoted_only (ignora fechas sueltas).
    """
    catalog_id = _normalize_catalog_id(payload.catalog_id)
    narrative_mode = payload.narrative_mode
    if catalog_id is None:
        return ChartResolutionDraft(
            resolution_status="quoted_only",
            catalog_id=None,
            start_date=None,
            end_date=None,
            rationale=payload.rationale,
            narrative_mode=narrative_mode,
        )

    end_date = payload.end_date or publish_date
    start_date = payload.start_date
    frequency: SeriesFrequency | None = None
    if is_valid_catalog_id(catalog_id):
        frequency = get_catalog_entry(catalog_id).frequency
        if start_date is None:
            start_date = _default_start_date(end_date, frequency, narrative_mode)
    elif start_date is None:
        # ID inválido: fechas placeholder; CatalogMembershipGuardrail falla después.
        start_date = end_date

    # Ventana mínima por frecuencia + narrativa (absorbe "hoy" / start==end).
    # No toca rangos invertidos: DateRangeGuardrail / el modelo fallan fail-closed.
    if frequency is not None and start_date <= end_date:
        min_days = max(_min_window_days(frequency), _narrative_fetch_days(narrative_mode))
        if (end_date - start_date).days < min_days:
            start_date = end_date - timedelta(days=min_days)

    try:
        return ChartResolutionDraft(
            resolution_status="verified_series",
            catalog_id=catalog_id,
            start_date=start_date,
            end_date=end_date,
            rationale=payload.rationale,
            narrative_mode=narrative_mode,
        )
    except ValidationError as exc:
        raise ResolutionValidationError(str(exc)) from exc


def format_resolver_prompt(
    mention: HardDataMention,
    chapter_context: str,
    publish_date: date,
) -> str:
    """Arma el prompt con mención, contexto, publish_date y catálogo compacto."""
    catalog_lines = [
        f"- {entry.catalog_id} | {entry.label} | {entry.description}"
        for entry in list_catalog_entries()
    ]
    time_ref = mention.time_reference if mention.time_reference is not None else "null"
    return "\n".join(
        (
            f"publish_date: {publish_date.isoformat()}",
            f"chapter_context: {chapter_context}",
            (
                f"mention: indicator_label={mention.indicator_label!r} "
                f"raw_value_text={mention.raw_value_text!r} "
                f"time_reference={time_ref!r}"
            ),
            "catálogo cerrado:",
            *catalog_lines,
        )
    )


def resolve_chapters_to_artifacts(
    chapters: ChapterizedTranscript,
    publish_date: date,
    resolver: MentionResolverEngine,
    fetcher: SeriesFetcher,
    *,
    source_chapters_path: str | None = None,
) -> ChartsPackage:
    """
    Recorre menciones en orden. quoted_only / verified_series / fetch_error por mención.
    Fallos de resolución o de fetch no abortan el resto del video.
    """
    items: list[ChartArtifact] = []
    for chapter_index, chapter in enumerate(chapters.chapters):
        chapter_context = f"{chapter.title}. {chapter.summary}".strip()
        for mention in chapter.hard_data:
            draft: ChartResolutionDraft | None = None
            resolve_error: str | None = None
            try:
                draft = resolver.resolve(mention, chapter_context, publish_date)
            except ResolutionValidationError as exc:
                resolve_error = str(exc)

            # Siempre evaluar alias inequívocos ANTES de emitir quoted_only / fetch_error,
            # e incluso si el LLM eligió otra clave válida del catálogo.
            matched = fallback_match_series_key(mention.indicator_label, chapter_context)
            if matched is not None and (draft is None or draft.catalog_id != matched):
                narrative_mode: NarrativeMode = (
                    draft.narrative_mode if draft is not None else "trend_with_callout"
                )
                rationale = (
                    draft.rationale
                    if draft is not None
                    else "Match determinista de catálogo tras error de resolución."
                )
                draft = _fallback_verified_draft(
                    mention,
                    chapter_context,
                    publish_date,
                    narrative_mode=narrative_mode,
                    rationale=rationale,
                )
            elif draft is None:
                items.append(
                    ChartArtifact(
                        chapter_index=chapter_index,
                        cue_index=mention.cue_index,
                        timestamp=mention.timestamp,
                        indicator_label=mention.indicator_label,
                        raw_value_text=mention.raw_value_text,
                        time_reference=mention.time_reference,
                        resolution_status="fetch_error",
                        rationale="Error de validación al resolver indicador.",
                        error_message=resolve_error or "Error de resolución.",
                    )
                )
                continue
            elif draft.resolution_status == "quoted_only":
                items.append(_quoted_artifact(chapter_index, mention, draft.rationale))
                continue

            assert draft.catalog_id is not None
            assert draft.start_date is not None
            assert draft.end_date is not None
            entry = get_catalog_entry(draft.catalog_id)
            try:
                series = fetcher.fetch(entry, draft.start_date, draft.end_date)
                metrics = compute_series_metrics(series.observations)
            except (ProviderError, MetricsCalculationError) as exc:
                items.append(
                    ChartArtifact(
                        chapter_index=chapter_index,
                        cue_index=mention.cue_index,
                        timestamp=mention.timestamp,
                        indicator_label=mention.indicator_label,
                        raw_value_text=mention.raw_value_text,
                        time_reference=mention.time_reference,
                        resolution_status="fetch_error",
                        rationale=draft.rationale,
                        error_message=str(exc),
                    )
                )
                continue

            narrative = _safe_chart_narrative(
                series.observations,
                entry=entry,
                mode=draft.narrative_mode,
                publish_date=publish_date,
                unit=series.unit,
                frequency=series.frequency,
            )
            items.append(
                ChartArtifact(
                    chapter_index=chapter_index,
                    cue_index=mention.cue_index,
                    timestamp=mention.timestamp,
                    indicator_label=mention.indicator_label,
                    raw_value_text=mention.raw_value_text,
                    time_reference=mention.time_reference,
                    resolution_status="verified_series",
                    rationale=draft.rationale,
                    series=series,
                    metrics=metrics,
                    narrative=narrative,
                )
            )

    return ChartsPackage(
        publish_date=publish_date,
        source_chapters_path=source_chapters_path,
        items=items,
    )


def _normalize_catalog_id(catalog_id: str | None) -> str | None:
    if catalog_id is None:
        return None
    cleaned = catalog_id.strip()
    if cleaned.casefold() in _NULLISH_CATALOG_IDS:
        return None
    return cleaned


def _default_start_date(
    end_date: date,
    frequency: SeriesFrequency,
    narrative_mode: NarrativeMode,
) -> date:
    narrative_days = _narrative_fetch_days(narrative_mode)
    if frequency == "daily":
        return end_date - timedelta(days=max(90, narrative_days))
    if frequency == "monthly":
        return end_date - timedelta(days=max(365, narrative_days))
    # Trimestral / anual: mantener horizonte largo y respetar narrativa.
    years = 5 if narrative_mode != "term_comparison" else 4
    by_years = _years_before(end_date, years)
    by_narrative = end_date - timedelta(days=narrative_days)
    return min(by_years, by_narrative)


def _min_window_days(frequency: SeriesFrequency) -> int:
    """Ventana mínima inclusiva para garantizar observaciones publicadas + contexto SVG."""
    if frequency == "daily":
        return 30
    if frequency == "monthly":
        return 365
    return 365 * 5


def _narrative_fetch_days(mode: NarrativeMode) -> int:
    if mode == "term_comparison":
        return _TERM_COMPARISON_FETCH_DAYS
    return _TREND_FETCH_DAYS


def _is_monthly_pct_change(entry: CatalogEntry) -> bool:
    """Detecta series mensuales de variación % (IPC/EMAE/IPCA mensual) desde el catálogo."""
    if entry.frequency != "monthly":
        return False
    unit = entry.unit.strip().casefold()
    if unit not in {"%", "p.p.", "pp"} and "%" not in unit and "porcent" not in unit:
        return False
    blob = " ".join((entry.catalog_id, entry.label, entry.description, *entry.aliases)).casefold()
    if "interanual" in blob or "año a año" in blob or " yoy" in f" {blob}":
        return False
    return (
        "variación mensual" in blob
        or "variacion mensual" in blob
        or entry.catalog_id.casefold().endswith("_mensual")
    )


def _scope_from_entry(entry: CatalogEntry) -> str:
    if entry.geography == "AR":
        return "argentina"
    return entry.geography.casefold()


def _safe_chart_narrative(
    observations: list[SeriesObservation],
    *,
    entry: CatalogEntry,
    mode: NarrativeMode,
    publish_date: date,
    unit: str,
    frequency: SeriesFrequency,
) -> ChartNarrative | None:
    try:
        return build_chart_narrative(
            observations,
            unit=unit,
            frequency=frequency,
            mode=mode,
            publish_date=publish_date,
            scope=_scope_from_entry(entry),
            is_monthly_pct_change=_is_monthly_pct_change(entry),
        )
    except MetricsCalculationError:
        return None


def _years_before(end_date: date, years: int) -> date:
    try:
        return end_date.replace(year=end_date.year - years)
    except ValueError:
        # 29-feb → 28-feb del año destino.
        return end_date.replace(year=end_date.year - years, day=28)


def _run_guardrails(draft: ChartResolutionDraft, guards: Sequence[object]) -> None:
    run_output = SimpleNamespace(content=draft)
    for guard in guards:
        try:
            guard.check(run_output)  # type: ignore[attr-defined]
        except OutputCheckError as exc:
            raise ResolutionValidationError(str(exc)) from exc


def _quoted_artifact(
    chapter_index: int,
    mention: HardDataMention,
    rationale: str,
) -> ChartArtifact:
    return ChartArtifact(
        chapter_index=chapter_index,
        cue_index=mention.cue_index,
        timestamp=mention.timestamp,
        indicator_label=mention.indicator_label,
        raw_value_text=mention.raw_value_text,
        time_reference=mention.time_reference,
        resolution_status="quoted_only",
        rationale=rationale,
    )


def _checked_content(agent: object, prompt: str, guards: Sequence[object]) -> object:
    for guard in guards:
        if hasattr(guard, "failure"):
            guard.failure = None
    try:
        result = agent.run(prompt)  # type: ignore[attr-defined]
    except OutputCheckError as exc:
        raise ResolutionValidationError(str(exc)) from exc
    if getattr(result, "status", None) == RunStatus.error:
        raise ResolutionValidationError(_guardrail_failure_message(result, guards))
    if hasattr(result, "content"):
        return result.content
    return result


def _guardrail_failure_message(result: object, guards: Sequence[object]) -> str:
    for guard in guards:
        failure = getattr(guard, "failure", None)
        if isinstance(failure, str) and failure.strip():
            return failure
    content = getattr(result, "content", None)
    if isinstance(content, str) and content.strip():
        return content
    for event in getattr(result, "events", None) or []:
        text = getattr(event, "content", None)
        if isinstance(text, str) and text.strip():
            return text
    return "el guardrail rechazó la salida del agente"


def _set_temperature_zero(model: Model) -> None:
    if not hasattr(model, "temperature"):
        raise ResolutionValidationError("el modelo inyectado no permite fijar temperature=0.0")
    model.temperature = 0.0
