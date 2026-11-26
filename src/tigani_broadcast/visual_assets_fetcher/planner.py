"""Planificador de búsquedas visuales (Agno + determinista) y orquestación a VisualAssetsPackage."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Protocol, runtime_checkable

from agno.agent import Agent
from agno.exceptions import OutputCheckError
from agno.models.base import Model
from agno.run.base import RunStatus

from tigani_broadcast.transcript_chapterizer.models import ChapterizedTranscript
from tigani_broadcast.visual_assets_fetcher.dedupe import deduplicate_visual_subjects
from tigani_broadcast.visual_assets_fetcher.models import (
    DeduplicatedVisualSubject,
    PortraitLayout,
    VisualAssetArtifact,
    VisualAssetsPackage,
    VisualQueryPlan,
)
from tigani_broadcast.visual_assets_fetcher.providers.base import VisualProviderError
from tigani_broadcast.visual_assets_fetcher.providers.fetcher import VisualAssetFetcher

_WHITESPACE = re.compile(r"\s+")
_URL_IN_QUERY = re.compile(r"https?://", re.IGNORECASE)

PLANNER_INSTRUCTIONS = "\n".join(
    (
        "Sos el planificador de búsquedas de imágenes para placas de noticiero.",
        "Recibís un visual_subject deduplicado y el título del capítulo.",
        "Devolvé solo search_query, preferred_provider y rationale.",
        "Corregí typos de transcripción en nombres propios",
        '(ej. "Cristina Kirner" → "Cristina Fernández de Kirchner").',
        'Si asset_kind es event_photo, preferred_provider="wikimedia"',
        "y usá nombres propios o lugares concretos en search_query",
        '(ej. "gobierno" en contexto argentino → "Casa Rosada Buenos Aires").',
        'Si asset_kind es conceptual_illustration, preferred_provider="openverse"',
        "y traducí SIEMPRE el concepto a 2–4 palabras clave concretas en inglés",
        '(ej. "Productos y servicios en dólares" → "US dollar banknotes prices").',
        "Nunca dejes search_query como un sustantivo abstracto suelto en español",
        "si asset_kind es conceptual_illustration.",
        "Nunca devuelvas URLs (http/https) en search_query.",
        "Nunca inventes licencias, autores ni rutas de imagen.",
        "rationale en español, breve y fiel a la decisión.",
    )
)

PLANNER_EXPECTED_OUTPUT = "\n".join(
    (
        "Objeto VisualQueryPlan con search_query (sin URLs),",
        'preferred_provider ("wikimedia" u "openverse") y rationale.',
    )
)


class PlannerError(ValueError):
    """El planificador rechazó o no pudo producir un VisualQueryPlan válido."""


@runtime_checkable
class VisualQueryPlanner(Protocol):
    """Motor inyectable: Agno real en producción, determinista/fake en tests offline."""

    def plan(self, subject: DeduplicatedVisualSubject, chapter_title: str) -> VisualQueryPlan:
        """Propone search_query + preferred_provider para un sujeto deduplicado."""
        ...


class DeterministicVisualQueryPlanner:
    """Planificador puro para `--no-llm` y tests: subject_label + proveedor por asset_kind."""

    def plan(self, subject: DeduplicatedVisualSubject, chapter_title: str) -> VisualQueryPlan:
        del chapter_title
        search_query = _WHITESPACE.sub(" ", subject.subject_label).strip()
        if not search_query:
            raise PlannerError("subject_label vacío tras normalizar")
        if len(search_query) > 160:
            search_query = search_query[:160].rstrip()
        preferred = "wikimedia" if subject.asset_kind == "event_photo" else "openverse"
        return VisualQueryPlan(
            search_query=search_query,
            preferred_provider=preferred,
            rationale=(
                f"Query determinista desde subject_label; "
                f"proveedor por asset_kind={subject.asset_kind}."
            ),
        )


class AgnoVisualQueryPlanner:
    """Planificador Agno 3.2.1: VisualQueryPlan tipado + rechazo fail-closed de URLs."""

    def __init__(self, model: Model, *, max_retries: int = 1) -> None:
        if max_retries < 0:
            raise PlannerError("max_retries no puede ser negativo")
        _set_temperature_zero(model)
        self.max_retries = max_retries
        self.agent = Agent(
            model=model,
            output_schema=VisualQueryPlan,
            instructions=PLANNER_INSTRUCTIONS,
            expected_output=PLANNER_EXPECTED_OUTPUT,
            markdown=False,
            telemetry=False,
        )

    def plan(self, subject: DeduplicatedVisualSubject, chapter_title: str) -> VisualQueryPlan:
        base_prompt = format_planner_prompt(subject, chapter_title)
        prompt = base_prompt
        last_error: PlannerError | None = None

        for attempt in range(self.max_retries + 1):
            try:
                content = _checked_content(self.agent, prompt)
                if not isinstance(content, VisualQueryPlan):
                    received = type(content).__name__
                    raise PlannerError(
                        f"el agente no devolvió un VisualQueryPlan (recibido: {received})"
                    )
                _reject_urls_in_query(content.search_query)
                return content
            except PlannerError as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
                prompt = "\n".join(
                    (
                        base_prompt,
                        (
                            f"Tu respuesta anterior fue rechazada porque: {exc}. "
                            "Corregila sin incluir URLs en search_query."
                        ),
                    )
                )

        assert last_error is not None
        raise last_error


def format_planner_prompt(subject: DeduplicatedVisualSubject, chapter_title: str) -> str:
    """Arma el prompt con sujeto deduplicado y contexto de capítulo."""
    return "\n".join(
        (
            f"chapter_title: {chapter_title}",
            f"subject_label: {subject.subject_label!r}",
            f"asset_kind: {subject.asset_kind}",
            f"context_text: {subject.context_text!r}",
            f"occurrences_count: {subject.occurrences_count}",
        )
    )


def resolve_chapters_to_visual_assets(
    chapters: ChapterizedTranscript,
    *,
    planner: VisualQueryPlanner,
    fetcher: VisualAssetFetcher,
    images_dir: Path,
    portrait_layout: PortraitLayout = "sidebar",
    source_chapters_path: str | None = None,
) -> VisualAssetsPackage:
    """
    Deduplica sujetos y resuelve verified_asset / fallback_card / fetch_error por sujeto.
    Fallos de planner o fetch no abortan el resto del video.
    """
    subjects = deduplicate_visual_subjects(chapters)
    items: list[VisualAssetArtifact] = []
    images_dir.mkdir(parents=True, exist_ok=True)

    for index, subject in enumerate(subjects):
        chapter = chapters.chapters[subject.chapter_index]
        filename_stem = f"ch{subject.chapter_index:02d}_cue{subject.cue_index:03d}_{index:02d}"
        try:
            plan = planner.plan(subject, chapter.title)
        except PlannerError as exc:
            items.append(
                _error_artifact(
                    subject,
                    search_query=subject.subject_label,
                    portrait_layout=portrait_layout,
                    exc=exc,
                )
            )
            continue

        try:
            fetched = fetcher.fetch_for_plan(
                plan,
                images_dir=images_dir,
                filename_stem=filename_stem,
            )
        except VisualProviderError as exc:
            items.append(
                _error_artifact(
                    subject,
                    search_query=plan.search_query,
                    portrait_layout=portrait_layout,
                    exc=exc,
                )
            )
            continue

        if fetched is None:
            items.append(
                VisualAssetArtifact(
                    chapter_index=subject.chapter_index,
                    cue_index=subject.cue_index,
                    timestamp=subject.timestamp,
                    subject_label=subject.subject_label,
                    asset_kind=subject.asset_kind,
                    context_text=subject.context_text,
                    occurrences_count=subject.occurrences_count,
                    search_query=plan.search_query,
                    status="fallback_card",
                    portrait_layout=portrait_layout,
                )
            )
            continue

        attribution, local_path = fetched
        items.append(
            VisualAssetArtifact(
                chapter_index=subject.chapter_index,
                cue_index=subject.cue_index,
                timestamp=subject.timestamp,
                subject_label=subject.subject_label,
                asset_kind=subject.asset_kind,
                context_text=subject.context_text,
                occurrences_count=subject.occurrences_count,
                search_query=plan.search_query,
                status="verified_asset",
                portrait_layout=portrait_layout,
                attribution=attribution,
                local_image_path=str(local_path),
            )
        )

    return VisualAssetsPackage(
        source_chapters_path=source_chapters_path,
        portrait_layout=portrait_layout,
        items=items,
    )


def _error_artifact(
    subject: DeduplicatedVisualSubject,
    *,
    search_query: str,
    portrait_layout: PortraitLayout,
    exc: Exception,
) -> VisualAssetArtifact:
    return VisualAssetArtifact(
        chapter_index=subject.chapter_index,
        cue_index=subject.cue_index,
        timestamp=subject.timestamp,
        subject_label=subject.subject_label,
        asset_kind=subject.asset_kind,
        context_text=subject.context_text,
        occurrences_count=subject.occurrences_count,
        search_query=search_query,
        status="fetch_error",
        portrait_layout=portrait_layout,
        error_message=str(exc),
    )


def _reject_urls_in_query(search_query: str) -> None:
    if _URL_IN_QUERY.search(search_query):
        raise PlannerError("search_query no puede contener URLs")


def _checked_content(agent: object, prompt: str) -> object:
    try:
        result = agent.run(prompt)  # type: ignore[attr-defined]
    except OutputCheckError as exc:
        raise PlannerError(str(exc)) from exc
    if getattr(result, "status", None) == RunStatus.error:
        content = getattr(result, "content", None)
        if isinstance(content, str) and content.strip():
            raise PlannerError(content)
        raise PlannerError("el agente falló al planificar la búsqueda")
    if hasattr(result, "content"):
        return result.content
    return result


def _set_temperature_zero(model: Model) -> None:
    if not hasattr(model, "temperature"):
        raise PlannerError("el modelo inyectado no permite fijar temperature=0.0")
    model.temperature = 0.0
