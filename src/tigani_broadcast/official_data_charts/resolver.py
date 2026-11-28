"""Resolvedor de HardDataMention → ChartResolutionDraft (Agno) y orquestación a ChartsPackage."""

from __future__ import annotations

import logging
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
    DataPoint,
    NarrativeMode,
    PlaybookId,
    SecondarySeriesData,
    SeriesData,
    SeriesFrequency,
    SeriesObservation,
)
from tigani_broadcast.official_data_charts.playbook import (
    PLAYBOOK_CATALOG,
    build_dual_base100,
    build_dual_spread,
    build_trade_balance,
    match_playbook_fallback,
)
from tigani_broadcast.official_data_charts.providers.base import ProviderError
from tigani_broadcast.official_data_charts.providers.fetcher import SeriesFetcher
from tigani_broadcast.transcript_chapterizer.models import (
    Chapter,
    ChapterizedTranscript,
    HardDataMention,
)

_NULLISH_CATALOG_IDS = frozenset({"", "none", "null", "quoted_only"})
_LOGGER = logging.getLogger(__name__)
_PLAYBOOK_MAX_ITEMS = 2
_PlaybookPick = tuple[PlaybookId, int, str]
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


class _PlaybookPickPayload(BaseModel):
    """Un gráfico de playbook elegido por el LLM, sin números calculados."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    playbook_id: str = Field(min_length=1, max_length=40)
    cue_index: int = Field(ge=0)
    rationale: str = Field(min_length=1, max_length=240)


class _PlaybookSelectionPayload(BaseModel):
    """Hasta dos gráficos de Playbook v1 para la tesis del capítulo."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    items: list[_PlaybookPickPayload] = Field(default_factory=list, max_length=2)


_PLAYBOOK_INSTRUCTIONS = "\n".join(
    (
        "Elegí hasta 2 gráficos del Playbook v2 que iluminen la tesis del capítulo.",
        "Devolvé items con playbook_id exacto, cue_index de la mención más afín y rationale.",
        "playbook_id solo puede ser: " + ", ".join(PLAYBOOK_CATALOG) + ".",
        "No calcules cifras. Si ningún gráfico aporta, devolvé items=[].",
        "Pueden convivir con un IPC mensual ya citado: ipc_vs_dolar_base100,",
        "salarios_vs_ipc_base100 y canasta_basica_vs_ipc_base100.",
        "No repitas ipc_trend si el IPC mensual ya está resuelto en el capítulo.",
        "No repitas un playbook_id que ya se haya usado en otro capítulo del video.",
    )
)
_IPC_COMPOSITE_PLAYBOOKS = frozenset(
    {
        "ipc_vs_dolar_base100",
        "salarios_vs_ipc_base100",
        "canasta_basica_vs_ipc_base100",
    }
)


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
        self.playbook_agent = Agent(
            model=model,
            output_schema=_PlaybookSelectionPayload,
            instructions=_PLAYBOOK_INSTRUCTIONS,
            expected_output="Objeto con items (máximo 2) de playbook_id, cue_index y rationale.",
            markdown=False,
            telemetry=False,
        )

    def select_playbooks(
        self,
        chapter_text: str,
        mentions: Sequence[HardDataMention],
        publish_date: date,
    ) -> list[_PlaybookPick]:
        """Pide hasta 2 playbook_id. Si el parseo falla, el caller usa el fallback."""
        prompt = _format_playbook_prompt(chapter_text, mentions, publish_date)
        content = _checked_content(self.playbook_agent, prompt, ())
        if not isinstance(content, _PlaybookSelectionPayload):
            received = type(content).__name__
            raise ResolutionValidationError(
                f"el agente no devolvió un _PlaybookSelectionPayload (recibido: {received})"
            )
        return _validated_playbook_picks(content)

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
    Después agrega hasta 2 gráficos de Playbook v1 por capítulo, sin borrar citas.
    Fallos de resolución, de fetch o de un playbook no abortan el resto del video.
    """
    items: list[ChartArtifact] = []
    used_playbook_ids: set[PlaybookId] = set()
    prior_series_keys: set[str] = set()
    for chapter_index, chapter in enumerate(chapters.chapters):
        chapter_context = f"{chapter.title}. {chapter.summary}".strip()
        chapter_items: list[ChartArtifact] = []
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
                chapter_items.append(
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
                chapter_items.append(_quoted_artifact(chapter_index, mention, draft.rationale))
                continue

            assert draft.catalog_id is not None
            assert draft.start_date is not None
            assert draft.end_date is not None
            entry = get_catalog_entry(draft.catalog_id)
            try:
                series = fetcher.fetch(entry, draft.start_date, draft.end_date)
                metrics = compute_series_metrics(series.observations)
            except (ProviderError, MetricsCalculationError) as exc:
                chapter_items.append(
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
            chapter_items.append(
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

        chapter_items.extend(
            _playbook_artifacts_for_chapter(
                chapter_index,
                chapter,
                chapter_items,
                publish_date=publish_date,
                resolver=resolver,
                fetcher=fetcher,
                used_playbook_ids=used_playbook_ids,
                prior_series_keys=prior_series_keys,
            )
        )
        chapter_items.sort(key=_artifact_sort_key)
        for artifact in chapter_items:
            if artifact.playbook_id is not None:
                used_playbook_ids.add(artifact.playbook_id)
            if artifact.resolution_status == "verified_series" and artifact.series is not None:
                prior_series_keys.add(artifact.series.catalog_id)
        items.extend(chapter_items)

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


def _artifact_sort_key(artifact: ChartArtifact) -> tuple[int, int]:
    """La cita del cue queda antes que el gráfico de playbook anclado al mismo cue."""
    return (artifact.cue_index, 1 if artifact.playbook_id is not None else 0)


def _playbook_artifacts_for_chapter(
    chapter_index: int,
    chapter: Chapter,
    mention_items: Sequence[ChartArtifact],
    *,
    publish_date: date,
    resolver: MentionResolverEngine,
    fetcher: SeriesFetcher,
    used_playbook_ids: set[PlaybookId],
    prior_series_keys: set[str],
) -> list[ChartArtifact]:
    existing = _existing_series_keys(mention_items)
    chapter_text = _chapter_playbook_text(chapter)
    picks = _select_playbook_picks(
        resolver,
        chapter,
        chapter_text,
        existing,
        publish_date,
        used_playbook_ids=used_playbook_ids,
        prior_series_keys=prior_series_keys,
    )
    artifacts: list[ChartArtifact] = []
    emitted: set[PlaybookId] = set(used_playbook_ids)
    for playbook_id, cue_index, rationale in picks:
        if len(artifacts) >= _PLAYBOOK_MAX_ITEMS:
            break
        if not _playbook_allowed(
            playbook_id,
            existing,
            emitted,
            prior_series_keys=prior_series_keys,
        ):
            continue
        cue_index, timestamp = _resolve_playbook_anchor(chapter, playbook_id, cue_index)
        artifact = _build_playbook_artifact(
            chapter_index,
            cue_index,
            timestamp,
            playbook_id,
            rationale,
            publish_date=publish_date,
            fetcher=fetcher,
        )
        if artifact is None:
            continue
        emitted.add(playbook_id)
        artifacts.append(artifact)
    return artifacts


def _select_playbook_picks(
    resolver: MentionResolverEngine,
    chapter: Chapter,
    chapter_text: str,
    existing_series_keys: set[str],
    publish_date: date,
    *,
    used_playbook_ids: set[PlaybookId],
    prior_series_keys: set[str],
) -> list[_PlaybookPick]:
    selector = getattr(resolver, "select_playbooks", None)
    picks: list[_PlaybookPick] = []
    if callable(selector):
        try:
            raw = selector(chapter_text, list(chapter.hard_data), publish_date)
            picks = _filter_playbook_picks(
                raw,
                existing_series_keys,
                used_playbook_ids=used_playbook_ids,
                prior_series_keys=prior_series_keys,
            )
        except (ResolutionValidationError, ValidationError, TypeError, ValueError) as exc:
            _LOGGER.info("playbook LLM no usable, se usa el fallback: %s", exc)
            picks = []
    if picks:
        return picks[:_PLAYBOOK_MAX_ITEMS]
    fallback_ids = match_playbook_fallback(
        chapter_text,
        existing_series_keys=existing_series_keys | prior_series_keys,
        max_items=len(PLAYBOOK_CATALOG),
    )
    anchored: list[_PlaybookPick] = []
    for playbook_id in fallback_ids:
        cue_index, _timestamp = _resolve_playbook_anchor(chapter, playbook_id, None)
        anchored.append((playbook_id, cue_index, "Match determinista de playbook."))
    return _filter_playbook_picks(
        anchored,
        existing_series_keys,
        used_playbook_ids=used_playbook_ids,
        prior_series_keys=prior_series_keys,
    )


def _filter_playbook_picks(
    raw: object,
    existing_series_keys: set[str],
    *,
    used_playbook_ids: set[PlaybookId] | None = None,
    prior_series_keys: set[str] | None = None,
) -> list[_PlaybookPick]:
    if not isinstance(raw, list):
        return []
    chosen: list[_PlaybookPick] = []
    emitted: set[PlaybookId] = set(used_playbook_ids or ())
    prior = prior_series_keys or set()
    for item in raw:
        parsed = _coerce_playbook_pick(item)
        if parsed is None:
            continue
        playbook_id, cue_index, rationale = parsed
        if not _playbook_allowed(
            playbook_id,
            existing_series_keys,
            emitted,
            prior_series_keys=prior,
        ):
            continue
        emitted.add(playbook_id)
        chosen.append((playbook_id, cue_index, rationale))
        if len(chosen) >= _PLAYBOOK_MAX_ITEMS:
            break
    return chosen


def _coerce_playbook_pick(item: object) -> _PlaybookPick | None:
    if isinstance(item, tuple) and len(item) == 3:
        playbook_id, cue_index, rationale = item
    else:
        return None
    if not isinstance(playbook_id, str) or playbook_id not in PLAYBOOK_CATALOG:
        return None
    if not isinstance(cue_index, int) or isinstance(cue_index, bool) or cue_index < 0:
        return None
    if not isinstance(rationale, str) or not rationale.strip():
        return None
    return playbook_id, cue_index, rationale.strip()  # type: ignore[return-value]


def _playbook_allowed(
    playbook_id: PlaybookId,
    existing_series_keys: set[str],
    emitted: set[PlaybookId],
    *,
    prior_series_keys: set[str] | None = None,
) -> bool:
    if playbook_id in emitted or playbook_id not in PLAYBOOK_CATALOG:
        return False
    spec = PLAYBOOK_CATALOG[playbook_id]
    prior = prior_series_keys or set()
    if playbook_id == "ipc_trend" and spec.series_keys[0] in prior:
        return False
    if playbook_id in _IPC_COMPOSITE_PLAYBOOKS:
        return True
    if spec.chart_type in {"single_line", "bar_diverging"}:
        return spec.series_keys[0] not in existing_series_keys
    return spec.series_keys[0] not in existing_series_keys


def _validated_playbook_picks(payload: _PlaybookSelectionPayload) -> list[_PlaybookPick]:
    picks: list[_PlaybookPick] = []
    for item in payload.items:
        if item.playbook_id not in PLAYBOOK_CATALOG:
            continue
        picks.append((item.playbook_id, item.cue_index, item.rationale))  # type: ignore[arg-type]
    return picks


def _format_playbook_prompt(
    chapter_text: str,
    mentions: Sequence[HardDataMention],
    publish_date: date,
) -> str:
    catalog_lines = [
        f"- {spec.playbook_id} | {spec.chart_type} | {spec.title}"
        for spec in PLAYBOOK_CATALOG.values()
    ]
    mention_lines = [
        f"- cue_index={mention.cue_index} label={mention.indicator_label!r} "
        f"raw={mention.raw_value_text!r}"
        for mention in mentions
    ] or ["- sin menciones"]
    return "\n".join(
        (
            f"publish_date: {publish_date.isoformat()}",
            f"chapter_text: {chapter_text}",
            "menciones:",
            *mention_lines,
            "playbook:",
            *catalog_lines,
        )
    )


def _chapter_playbook_text(chapter: Chapter) -> str:
    parts = [chapter.title, chapter.summary]
    for mention in chapter.hard_data:
        parts.append(mention.indicator_label)
        parts.append(mention.raw_value_text)
        if mention.time_reference:
            parts.append(mention.time_reference)
    return ". ".join(part.strip() for part in parts if part and part.strip())


def _existing_series_keys(items: Sequence[ChartArtifact]) -> set[str]:
    keys: set[str] = set()
    for artifact in items:
        if (
            artifact.playbook_id is None
            and artifact.resolution_status == "verified_series"
            and artifact.series is not None
        ):
            keys.add(artifact.series.catalog_id)
    return keys


_PLAYBOOK_AFFINITY: dict[PlaybookId, tuple[str, ...]] = {
    "ipc_vs_dolar_base100": (
        "dolar",
        "producto",
        "servicio",
        "precio",
        "atraso",
        "competitividad",
    ),
    "reservas_bcra_regimes": ("reserva", "swap", "banco central"),
    "riesgo_pais_trend": ("riesgo", "embi", "bono", "tasa", "deuda", "vencimiento"),
    "emae_activity": ("emae", "actividad", "recesion", "pbi"),
    "ipc_trend": ("inflacion", "ipc"),
    "brecha_cambiaria": ("brecha", "cepo", "blue", "paralelo", "mep", "ccl"),
    "salarios_vs_ipc_base100": ("salario", "sueldo", "adquisitivo", "paritaria", "ingreso"),
    "canasta_basica_vs_ipc_base100": ("canasta", "pobreza", "indigencia", "cbt", "cba"),
    "balanza_comercial_ica": ("balanza", "exportacion", "importacion", "ica"),
}


def _resolve_playbook_anchor(
    chapter: Chapter,
    playbook_id: PlaybookId,
    requested_cue: int | None,
) -> tuple[int, str]:
    if requested_cue is not None:
        for mention in chapter.hard_data:
            if mention.cue_index == requested_cue:
                return mention.cue_index, mention.timestamp
        if chapter.start_cue_index <= requested_cue <= chapter.end_cue_index:
            return requested_cue, chapter.end_time
    tokens = _PLAYBOOK_AFFINITY.get(playbook_id, ())
    best: HardDataMention | None = None
    best_score = 0
    for mention in chapter.hard_data:
        blob = normalize_label(f"{mention.indicator_label} {mention.raw_value_text}")
        score = sum(1 for token in tokens if token in blob)
        if score > best_score:
            best = mention
            best_score = score
    if best is not None:
        return best.cue_index, best.timestamp
    if chapter.hard_data:
        last = chapter.hard_data[-1]
        return last.cue_index, last.timestamp
    return chapter.end_cue_index, chapter.end_time


def _build_playbook_artifact(
    chapter_index: int,
    cue_index: int,
    timestamp: str,
    playbook_id: PlaybookId,
    rationale: str,
    *,
    publish_date: date,
    fetcher: SeriesFetcher,
) -> ChartArtifact | None:
    spec = PLAYBOOK_CATALOG[playbook_id]
    try:
        if spec.chart_type == "dual_base100":
            return _build_dual_base100_playbook_artifact(
                chapter_index,
                cue_index,
                timestamp,
                playbook_id,
                rationale,
                publish_date=publish_date,
                fetcher=fetcher,
            )
        if spec.chart_type == "dual_spread":
            return _build_spread_playbook_artifact(
                chapter_index,
                cue_index,
                timestamp,
                playbook_id,
                rationale,
                publish_date=publish_date,
                fetcher=fetcher,
            )
        if spec.chart_type == "trade_balance":
            return _build_trade_playbook_artifact(
                chapter_index,
                cue_index,
                timestamp,
                playbook_id,
                rationale,
                publish_date=publish_date,
                fetcher=fetcher,
            )
        entry = get_catalog_entry(spec.series_keys[0])
        start = _fetch_start(publish_date, spec.default_window_months)
        series = fetcher.fetch(entry, start, publish_date)
        metrics = compute_series_metrics(series.observations)
        mode: NarrativeMode = (
            "term_comparison" if playbook_id == "reservas_bcra_regimes" else "trend_with_callout"
        )
        narrative = _safe_chart_narrative(
            series.observations,
            entry=entry,
            mode=mode,
            publish_date=publish_date,
            unit=series.unit,
            frequency=series.frequency,
        )
        if narrative is None:
            _LOGGER.info("playbook %s omitido: narrativa vacía", playbook_id)
            return None
        latest = series.observations[-1].value if series.observations else None
        raw_value = f"{latest}" if latest is not None else spec.title
        return ChartArtifact(
            chapter_index=chapter_index,
            cue_index=cue_index,
            timestamp=timestamp,
            indicator_label=spec.title,
            raw_value_text=raw_value,
            resolution_status="verified_series",
            rationale=rationale[:240],
            series=series,
            metrics=metrics,
            narrative=narrative,
            playbook_id=playbook_id,
            chart_type=spec.chart_type,
            editorial_note=spec.editorial_note,
        )
    except (ProviderError, MetricsCalculationError, ValueError, KeyError) as exc:
        _LOGGER.info("playbook %s omitido: %s", playbook_id, exc)
        return None


def _build_dual_base100_playbook_artifact(
    chapter_index: int,
    cue_index: int,
    timestamp: str,
    playbook_id: PlaybookId,
    rationale: str,
    *,
    publish_date: date,
    fetcher: SeriesFetcher,
) -> ChartArtifact:
    spec = PLAYBOOK_CATALOG[playbook_id]
    primary_entry = get_catalog_entry(spec.series_keys[0])
    secondary_entry = get_catalog_entry(spec.series_keys[1])
    start = _fetch_start(publish_date, spec.fetch_window_months)
    primary_series = fetcher.fetch(primary_entry, start, publish_date)
    secondary_series = fetcher.fetch(secondary_entry, start, publish_date)
    if playbook_id == "ipc_vs_dolar_base100":
        call = {
            "primary_mode": "percent_change",
            "secondary_mode": "level",
            "primary_label": "IPC acumulado",
            "secondary_label": "Dólar oficial",
            "primary_subject": "IPC",
            "secondary_subject": "dólar",
            "secondary_name": "Dólar mayorista",
        }
    else:
        call = {
            "primary_mode": "level",
            "secondary_mode": "percent_change",
            "primary_label": spec.title.split(" vs.")[0],
            "secondary_label": "IPC",
            "primary_subject": spec.title.split(" vs.")[0].casefold(),
            "secondary_subject": "IPC",
            "secondary_name": "IPC",
        }
    primary_index, secondary_index, narrative = build_dual_base100(
        _series_points(primary_series),
        _series_points(secondary_series),
        publish_date=publish_date,
        max_months=spec.default_window_months,
        primary_mode=call["primary_mode"],  # type: ignore[arg-type]
        secondary_mode=call["secondary_mode"],  # type: ignore[arg-type]
        primary_label=str(call["primary_label"]),
        secondary_label=str(call["secondary_label"]),
        primary_subject=str(call["primary_subject"]),
        secondary_subject=str(call["secondary_subject"]),
    )
    return _indexed_playbook_artifact(
        chapter_index,
        cue_index,
        timestamp,
        playbook_id,
        rationale,
        spec_title=spec.title,
        editorial_note=spec.editorial_note,
        chart_type="dual_base100",
        base_series=primary_series,
        indexed_points=primary_index,
        secondary_points=secondary_index,
        secondary_series=secondary_series,
        secondary_label=str(call["secondary_name"]),
        narrative=narrative,
        unit="base 100",
    )


def _build_spread_playbook_artifact(
    chapter_index: int,
    cue_index: int,
    timestamp: str,
    playbook_id: PlaybookId,
    rationale: str,
    *,
    publish_date: date,
    fetcher: SeriesFetcher,
) -> ChartArtifact:
    spec = PLAYBOOK_CATALOG[playbook_id]
    official = fetcher.fetch(
        get_catalog_entry(spec.series_keys[0]),
        _fetch_start(publish_date, spec.fetch_window_months),
        publish_date,
    )
    parallel = fetcher.fetch(
        get_catalog_entry(spec.series_keys[1]),
        _fetch_start(publish_date, spec.fetch_window_months),
        publish_date,
    )
    official_points, parallel_points, narrative = build_dual_spread(
        _series_points(official),
        _series_points(parallel),
        publish_date=publish_date,
        max_months=spec.default_window_months,
    )
    return _indexed_playbook_artifact(
        chapter_index,
        cue_index,
        timestamp,
        playbook_id,
        rationale,
        spec_title=spec.title,
        editorial_note=spec.editorial_note,
        chart_type="dual_spread",
        base_series=official,
        indexed_points=official_points,
        secondary_points=parallel_points,
        secondary_series=parallel,
        secondary_label="Dólar blue",
        narrative=narrative,
        unit=official.unit,
    )


def _build_trade_playbook_artifact(
    chapter_index: int,
    cue_index: int,
    timestamp: str,
    playbook_id: PlaybookId,
    rationale: str,
    *,
    publish_date: date,
    fetcher: SeriesFetcher,
) -> ChartArtifact:
    spec = PLAYBOOK_CATALOG[playbook_id]
    exports = fetcher.fetch(
        get_catalog_entry(spec.series_keys[0]),
        _fetch_start(publish_date, spec.fetch_window_months),
        publish_date,
    )
    imports = fetcher.fetch(
        get_catalog_entry(spec.series_keys[1]),
        _fetch_start(publish_date, spec.fetch_window_months),
        publish_date,
    )
    export_points, import_points, narrative = build_trade_balance(
        _series_points(exports),
        _series_points(imports),
        publish_date=publish_date,
        max_months=spec.default_window_months,
    )
    return _indexed_playbook_artifact(
        chapter_index,
        cue_index,
        timestamp,
        playbook_id,
        rationale,
        spec_title=spec.title,
        editorial_note=spec.editorial_note,
        chart_type="trade_balance",
        base_series=exports,
        indexed_points=export_points,
        secondary_points=import_points,
        secondary_series=imports,
        secondary_label="Importaciones",
        narrative=narrative,
        unit=exports.unit,
    )


def _indexed_playbook_artifact(
    chapter_index: int,
    cue_index: int,
    timestamp: str,
    playbook_id: PlaybookId,
    rationale: str,
    *,
    spec_title: str,
    editorial_note: str | None,
    chart_type: str,
    base_series: SeriesData,
    indexed_points: Sequence[DataPoint],
    secondary_points: Sequence[DataPoint],
    secondary_series: SeriesData,
    secondary_label: str,
    narrative: ChartNarrative,
    unit: str,
) -> ChartArtifact:
    series = base_series.model_copy(
        update={
            "unit": unit,
            "frequency": "monthly",
            "observations": [
                SeriesObservation(obs_date=point.obs_date, value=point.value)
                for point in indexed_points
            ],
        }
    )
    metrics = compute_series_metrics(series.observations)
    return ChartArtifact(
        chapter_index=chapter_index,
        cue_index=cue_index,
        timestamp=timestamp,
        indicator_label=spec_title,
        raw_value_text=narrative.headline_badge or spec_title,
        resolution_status="verified_series",
        rationale=rationale[:240],
        series=series,
        metrics=metrics,
        narrative=narrative,
        playbook_id=playbook_id,
        chart_type=chart_type,  # type: ignore[arg-type]
        secondary_series=SecondarySeriesData(
            label=secondary_label,
            series_key=secondary_series.catalog_id,
            provider=secondary_series.provider,
            series_id=secondary_series.series_id,
            unit=unit,
            points=list(secondary_points),
        ),
        editorial_note=editorial_note,
    )


def _series_points(series: SeriesData) -> list[DataPoint]:
    return [
        DataPoint(obs_date=obs.obs_date, value=obs.value)
        for obs in series.observations
        if obs.value is not None
    ]


def _fetch_start(publish_date: date, months: int) -> date:
    """Primer día del mes que abre una ventana inclusiva de `months` meses."""
    if months < 1:
        raise ValueError("la ventana de fetch tiene que ser de al menos 1 mes")
    month_index = publish_date.year * 12 + (publish_date.month - 1) - (months - 1)
    year, month0 = divmod(month_index, 12)
    return date(year, month0 + 1, 1)


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
