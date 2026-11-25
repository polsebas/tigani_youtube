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
)
from tigani_broadcast.official_data_charts.metrics import (
    MetricsCalculationError,
    compute_series_metrics,
)
from tigani_broadcast.official_data_charts.models import (
    ChartArtifact,
    ChartResolutionDraft,
    ChartsPackage,
    SeriesFrequency,
)
from tigani_broadcast.official_data_charts.providers.base import ProviderError
from tigani_broadcast.official_data_charts.providers.fetcher import SeriesFetcher
from tigani_broadcast.transcript_chapterizer.models import (
    ChapterizedTranscript,
    HardDataMention,
)

_NULLISH_CATALOG_IDS = frozenset({"", "none", "null", "quoted_only"})

RESOLVER_INSTRUCTIONS = "\n".join(
    (
        "Sos el resolvedor de menciones económicas para placas de noticiero.",
        "Recibís una HardDataMention, el contexto breve del capítulo, publish_date",
        "y el catálogo cerrado de indicadores verificables.",
        "Devolvé solo catalog_id, start_date, end_date y rationale.",
        "Si la mención corresponde a un indicador exacto del catálogo,",
        "poné ese catalog_id (string exacto).",
        "Si es cifra puntual/coyuntural (licitación, swap, vencimiento, bono,",
        "porcentaje analítico) o un derivado no publicado (reservas netas),",
        "poné catalog_id=null.",
        "start_date y end_date son opcionales (YYYY-MM-DD); si faltan,",
        "Python completa el rango. end_date nunca posterior a publish_date.",
        "Nunca sustituyas reservas netas por ar_bcra_reservas_brutas.",
        "Nunca inventes un catalog_id fuera del listado.",
        "rationale en español, breve y fiel a la decisión.",
    )
)

RESOLVER_EXPECTED_OUTPUT = "\n".join(
    (
        "Objeto con catalog_id (ID del catálogo o null), start_date, end_date y rationale.",
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
        raise last_error


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
    if catalog_id is None:
        return ChartResolutionDraft(
            resolution_status="quoted_only",
            catalog_id=None,
            start_date=None,
            end_date=None,
            rationale=payload.rationale,
        )

    end_date = payload.end_date or publish_date
    start_date = payload.start_date
    frequency: SeriesFrequency | None = None
    if is_valid_catalog_id(catalog_id):
        frequency = get_catalog_entry(catalog_id).frequency
        if start_date is None:
            start_date = _default_start_date(end_date, frequency)
    elif start_date is None:
        # ID inválido: fechas placeholder; CatalogMembershipGuardrail falla después.
        start_date = end_date

    # Ventana mínima por frecuencia (absorbe "hoy" / start==end en series mensuales).
    # No toca rangos invertidos: DateRangeGuardrail / el modelo fallan fail-closed.
    if frequency is not None and start_date <= end_date:
        min_days = _min_window_days(frequency)
        if (end_date - start_date).days < min_days:
            start_date = end_date - timedelta(days=min_days)

    try:
        return ChartResolutionDraft(
            resolution_status="verified_series",
            catalog_id=catalog_id,
            start_date=start_date,
            end_date=end_date,
            rationale=payload.rationale,
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
            try:
                draft = resolver.resolve(mention, chapter_context, publish_date)
            except ResolutionValidationError as exc:
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
                        error_message=str(exc),
                    )
                )
                continue

            if draft.resolution_status == "quoted_only":
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


def _default_start_date(end_date: date, frequency: SeriesFrequency) -> date:
    if frequency == "daily":
        return end_date - timedelta(days=90)
    if frequency == "monthly":
        return end_date - timedelta(days=365)
    return _years_before(end_date, 5)


def _min_window_days(frequency: SeriesFrequency) -> int:
    """Ventana mínima inclusiva para garantizar observaciones publicadas + contexto SVG."""
    if frequency == "daily":
        return 30
    if frequency == "monthly":
        return 365
    return 365 * 5


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
