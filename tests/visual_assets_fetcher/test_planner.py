"""Planificador Agno/determinista y orquestación a VisualAssetsPackage (offline)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Literal

import pytest
from agno.exceptions import CheckTrigger, OutputCheckError
from agno.run.base import RunStatus

from tigani_broadcast.transcript_chapterizer.models import (
    Chapter,
    ChapterizedTranscript,
    VisualSubjectMention,
)
from tigani_broadcast.visual_assets_fetcher.models import (
    DeduplicatedVisualSubject,
    VisualAttribution,
    VisualQueryPlan,
)
from tigani_broadcast.visual_assets_fetcher.planner import (
    PLANNER_EXPECTED_OUTPUT,
    PLANNER_INSTRUCTIONS,
    AgnoVisualQueryPlanner,
    DeterministicVisualQueryPlanner,
    PlannerError,
    format_planner_prompt,
    resolve_chapters_to_visual_assets,
)
from tigani_broadcast.visual_assets_fetcher.providers.base import VisualProviderResponseError

AssetKind = Literal["event_photo", "conceptual_illustration"]


class _Modelo:
    def __init__(self, temperature: float = 0.7) -> None:
        self.temperature = temperature


class _AgentDoble:
    creados: list[_AgentDoble] = []

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.prompts: list[str] = []
        self.content: object = None
        self.contents: list[object] | None = None
        self.status = RunStatus.completed
        self.raise_output_check: OutputCheckError | None = None
        self._call = 0
        _AgentDoble.creados.append(self)

    def run(self, prompt: str, **kwargs: object) -> SimpleNamespace:
        del kwargs
        self.prompts.append(prompt)
        if self.raise_output_check is not None:
            raise self.raise_output_check
        if self.contents is not None:
            content = self.contents[min(self._call, len(self.contents) - 1)]
            self._call += 1
            return SimpleNamespace(content=content, status=self.status)
        return SimpleNamespace(content=self.content, status=self.status)


def _dedup(
    label: str,
    *,
    asset_kind: AssetKind = "event_photo",
    cue_index: int = 0,
    chapter_index: int = 0,
) -> DeduplicatedVisualSubject:
    return DeduplicatedVisualSubject(
        chapter_index=chapter_index,
        cue_index=cue_index,
        timestamp=f"00:00:{cue_index:02d}",
        subject_label=label,
        normalized_label=label.casefold().strip(),
        asset_kind=asset_kind,
        context_text=f"contexto de {label}",
        occurrences_count=1,
    )


def _subject(
    cue_index: int,
    label: str,
    *,
    asset_kind: AssetKind = "event_photo",
) -> VisualSubjectMention:
    return VisualSubjectMention(
        cue_index=cue_index,
        timestamp=f"00:00:{cue_index:02d}",
        subject_label=label,
        asset_kind=asset_kind,
        context_text=f"contexto de {label}",
    )


def _chapter(
    start: int,
    end: int,
    subjects: list[VisualSubjectMention],
    *,
    title: str = "Capítulo",
) -> Chapter:
    return Chapter(
        start_cue_index=start,
        end_cue_index=end,
        start_time=f"00:00:{start:02d}",
        end_time=f"00:00:{end:02d}",
        title=title,
        summary="Resumen.",
        suggested_lower_third="Zócalo",
        visual_subjects=subjects,
    )


def _attribution(**overrides: object) -> VisualAttribution:
    payload: dict[str, object] = {
        "provider": "wikimedia",
        "author": "Jane Doe",
        "license_name": "CC BY 4.0",
        "license_code": "CC-BY",
        "source_page_url": "https://commons.wikimedia.org/wiki/File:X.jpg",
        "image_url": "https://upload.wikimedia.org/x.jpg",
        "width": 1280,
        "height": 720,
        "mime_type": "image/jpeg",
    }
    payload.update(overrides)
    return VisualAttribution.model_validate(payload)


class _PlannerFake:
    def __init__(
        self,
        plans: dict[str, VisualQueryPlan] | None = None,
        *,
        errors: dict[str, Exception] | None = None,
    ) -> None:
        self.plans = plans or {}
        self.errors = errors or {}

    def plan(self, subject: DeduplicatedVisualSubject, chapter_title: str) -> VisualQueryPlan:
        del chapter_title
        if subject.subject_label in self.errors:
            raise self.errors[subject.subject_label]
        return self.plans[subject.subject_label]


class _FetcherFake:
    def __init__(
        self,
        results: dict[str, tuple[VisualAttribution, Path] | None] | None = None,
        *,
        errors: dict[str, Exception] | None = None,
    ) -> None:
        self.results = results or {}
        self.errors = errors or {}

    def fetch_for_plan(
        self,
        plan: VisualQueryPlan,
        *,
        images_dir: Path,
        filename_stem: str,
    ) -> tuple[VisualAttribution, Path] | None:
        if plan.search_query in self.errors:
            raise self.errors[plan.search_query]
        if plan.search_query not in self.results:
            return None
        result = self.results[plan.search_query]
        if result is None:
            return None
        attribution, _ = result
        path = images_dir / f"{filename_stem}.jpg"
        images_dir.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\xff\xd8\xff")
        return attribution, path


def test_deterministic_asigna_proveedor_por_asset_kind() -> None:
    planner = DeterministicVisualQueryPlanner()
    photo = planner.plan(_dedup("  Cristina Kirchner  "), "Título")
    concept = planner.plan(
        _dedup("inflación", asset_kind="conceptual_illustration"),
        "Título",
    )
    assert photo.search_query == "Cristina Kirchner"
    assert photo.preferred_provider == "wikimedia"
    assert concept.preferred_provider == "openverse"


def test_agno_planner_rechaza_urls_y_reintenta(monkeypatch: pytest.MonkeyPatch) -> None:
    _AgentDoble.creados.clear()
    monkeypatch.setattr(
        "tigani_broadcast.visual_assets_fetcher.planner.Agent",
        _AgentDoble,
    )
    planner = AgnoVisualQueryPlanner(_Modelo(), max_retries=1)
    agent = _AgentDoble.creados[0]
    assert agent.kwargs["output_schema"] is VisualQueryPlan
    assert PLANNER_INSTRUCTIONS in agent.kwargs["instructions"]
    assert "2–4 palabras clave" in PLANNER_INSTRUCTIONS
    assert "Casa Rosada Buenos Aires" in PLANNER_INSTRUCTIONS
    assert "US dollar banknotes prices" in PLANNER_INSTRUCTIONS
    assert agent.kwargs["expected_output"] == PLANNER_EXPECTED_OUTPUT

    bad = VisualQueryPlan(
        search_query="https://evil.example/cristina",
        preferred_provider="wikimedia",
        rationale="mal",
    )
    good = VisualQueryPlan(
        search_query="Cristina Fernández de Kirchner",
        preferred_provider="wikimedia",
        rationale="typo corregido",
    )
    agent.contents = [bad, good]
    plan = planner.plan(_dedup("Cristina Kirner"), "Política")
    assert plan.search_query == "Cristina Fernández de Kirchner"
    assert len(agent.prompts) == 2
    assert "rechazada" in agent.prompts[1]


def test_agno_planner_falla_tras_reintento(monkeypatch: pytest.MonkeyPatch) -> None:
    _AgentDoble.creados.clear()
    monkeypatch.setattr(
        "tigani_broadcast.visual_assets_fetcher.planner.Agent",
        _AgentDoble,
    )
    planner = AgnoVisualQueryPlanner(_Modelo(), max_retries=1)
    agent = _AgentDoble.creados[0]
    agent.content = VisualQueryPlan(
        search_query="http://bad",
        preferred_provider="wikimedia",
        rationale="sigue mal",
    )
    with pytest.raises(PlannerError, match="URLs"):
        planner.plan(_dedup("X"), "Cap")


def test_agno_output_check_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _AgentDoble.creados.clear()
    monkeypatch.setattr(
        "tigani_broadcast.visual_assets_fetcher.planner.Agent",
        _AgentDoble,
    )
    planner = AgnoVisualQueryPlanner(_Modelo(), max_retries=0)
    agent = _AgentDoble.creados[0]
    agent.raise_output_check = OutputCheckError(
        "roto", check_trigger=CheckTrigger.VALIDATION_FAILED
    )
    with pytest.raises(PlannerError, match="roto"):
        planner.plan(_dedup("X"), "Cap")


def test_format_planner_prompt_incluye_campos() -> None:
    subject = _dedup("BCRA", cue_index=3, chapter_index=1)
    subject = subject.model_copy(update={"occurrences_count": 2})
    prompt = format_planner_prompt(subject, "Reservas")
    assert "chapter_title: Reservas" in prompt
    assert "subject_label: 'BCRA'" in prompt
    assert "occurrences_count: 2" in prompt


def test_resolve_degrada_por_sujeto_sin_abortar(tmp_path: Path) -> None:
    transcript = ChapterizedTranscript(
        chapters=[
            _chapter(
                0,
                5,
                [
                    _subject(0, "gobierno"),
                    _subject(1, "Gobierno"),
                    _subject(2, "inflación", asset_kind="conceptual_illustration"),
                    _subject(3, "roto"),
                    _subject(4, "sin_resultado"),
                ],
                title="Coyuntura",
            )
        ]
    )
    planner = _PlannerFake(
        plans={
            "gobierno": VisualQueryPlan(
                search_query="gobierno",
                preferred_provider="wikimedia",
                rationale="ok",
            ),
            "inflación": VisualQueryPlan(
                search_query="inflation concept",
                preferred_provider="openverse",
                rationale="ok",
            ),
            "sin_resultado": VisualQueryPlan(
                search_query="sin_resultado",
                preferred_provider="wikimedia",
                rationale="ok",
            ),
        },
        errors={"roto": PlannerError("planner caído")},
    )
    fetcher = _FetcherFake(
        results={
            "gobierno": (_attribution(), tmp_path / "g.jpg"),
            "inflation concept": None,
            "sin_resultado": None,
        }
    )
    package = resolve_chapters_to_visual_assets(
        transcript,
        planner=planner,
        fetcher=fetcher,  # type: ignore[arg-type]
        images_dir=tmp_path / "images",
        portrait_layout="contain",
        source_chapters_path="chapters.json",
    )
    assert package.portrait_layout == "contain"
    assert len(package.items) == 4
    by_label = {item.subject_label: item for item in package.items}
    assert by_label["gobierno"].status == "verified_asset"
    assert by_label["gobierno"].occurrences_count == 2
    assert by_label["inflación"].status == "fallback_card"
    assert by_label["roto"].status == "fetch_error"
    assert "planner caído" in (by_label["roto"].error_message or "")
    assert by_label["sin_resultado"].status == "fallback_card"


def test_resolve_fetch_error_de_provider(tmp_path: Path) -> None:
    transcript = ChapterizedTranscript(
        chapters=[_chapter(0, 1, [_subject(0, "BCRA")], title="BCRA")]
    )
    planner = _PlannerFake(
        plans={
            "BCRA": VisualQueryPlan(
                search_query="BCRA",
                preferred_provider="wikimedia",
                rationale="ok",
            )
        }
    )
    fetcher = _FetcherFake(errors={"BCRA": VisualProviderResponseError("wikimedia: HTTP 500")})
    package = resolve_chapters_to_visual_assets(
        transcript,
        planner=planner,
        fetcher=fetcher,  # type: ignore[arg-type]
        images_dir=tmp_path / "images",
    )
    assert package.items[0].status == "fetch_error"
    assert "500" in (package.items[0].error_message or "")


def test_promo_outro_no_genera_busqueda_de_imagenes(tmp_path: Path) -> None:
    class _Boom:
        def plan(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("no debe planear imágenes del cierre")

        def fetch_for_plan(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("no debe bajar imágenes del cierre")

    chapters = ChapterizedTranscript(
        chapters=[
            Chapter(
                start_cue_index=0,
                end_cue_index=1,
                start_time="00:11:15",
                end_time="00:12:32",
                title="Cierre",
                summary="Invitación a la comunidad.",
                suggested_lower_third="Sumate",
                chapter_kind="promo_outro",
                visual_subjects=[
                    VisualSubjectMention(
                        cue_index=0,
                        timestamp="00:11:15",
                        subject_label="comunidad",
                        asset_kind="conceptual_illustration",
                        context_text="nivel uno",
                    )
                ],
            )
        ]
    )
    package = resolve_chapters_to_visual_assets(
        chapters,
        planner=_Boom(),  # type: ignore[arg-type]
        fetcher=_Boom(),  # type: ignore[arg-type]
        images_dir=tmp_path / "images",
    )
    assert package.items == []


def test_max_retries_negativo() -> None:
    with pytest.raises(PlannerError, match="max_retries"):
        AgnoVisualQueryPlanner(_Modelo(), max_retries=-1)


def test_modelo_sin_temperature() -> None:
    class _SinTemp:
        pass

    with pytest.raises(PlannerError, match="temperature"):
        AgnoVisualQueryPlanner(_SinTemp())  # type: ignore[arg-type]
