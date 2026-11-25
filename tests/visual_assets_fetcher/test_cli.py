"""CLI offline: planner/fetcher falsos, sin red ni tokens."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tigani_broadcast.visual_assets_fetcher.cli import (
    EXIT_ERROR,
    EXIT_OK,
    VisualAssetsCliError,
    run_cli,
)
from tigani_broadcast.visual_assets_fetcher.models import (
    DeduplicatedVisualSubject,
    VisualAttribution,
    VisualQueryPlan,
)
from tigani_broadcast.visual_assets_fetcher.providers.base import VisualProviderResponseError


class _PlannerFake:
    def __init__(
        self,
        plan: VisualQueryPlan | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.plan_value = plan
        self.error = error
        self.calls = 0

    def plan(self, subject: DeduplicatedVisualSubject, chapter_title: str) -> VisualQueryPlan:
        del chapter_title
        self.calls += 1
        if self.error is not None:
            raise self.error
        assert self.plan_value is not None
        return self.plan_value.model_copy(update={"search_query": subject.subject_label})


class _MultiPlanner:
    def __init__(self, plans: dict[str, VisualQueryPlan]) -> None:
        self.plans = plans

    def plan(self, subject: DeduplicatedVisualSubject, chapter_title: str) -> VisualQueryPlan:
        del chapter_title
        return self.plans[subject.subject_label]


class _FetcherFake:
    def __init__(
        self,
        *,
        ok_labels: set[str] | None = None,
        none_labels: set[str] | None = None,
        error_labels: dict[str, Exception] | None = None,
    ) -> None:
        self.ok_labels = ok_labels or set()
        self.none_labels = none_labels or set()
        self.error_labels = error_labels or {}

    def fetch_for_plan(
        self,
        plan: VisualQueryPlan,
        *,
        images_dir: Path,
        filename_stem: str,
    ) -> tuple[VisualAttribution, Path] | None:
        query = plan.search_query
        if query in self.error_labels:
            raise self.error_labels[query]
        if query in self.none_labels:
            return None
        if query not in self.ok_labels:
            return None
        path = images_dir / f"{filename_stem}.jpg"
        images_dir.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\xff\xd8\xff")
        attribution = VisualAttribution(
            provider="wikimedia",
            author="Autor Test",
            license_name="CC BY 4.0",
            license_code="CC-BY",
            source_page_url="https://commons.wikimedia.org/wiki/File:T.jpg",
            image_url="https://upload.wikimedia.org/t.jpg",
            width=1280,
            height=720,
            mime_type="image/jpeg",
        )
        return attribution, path


def _chapters_payload() -> dict:
    """Estructura equivalente a kP_G1sAStQE.v3.chapters.json (recortada)."""
    return {
        "chapters": [
            {
                "start_cue_index": 0,
                "end_cue_index": 5,
                "start_time": "00:00:01",
                "end_time": "00:00:50",
                "title": "Intro",
                "summary": "Apertura.",
                "suggested_lower_third": "Intro",
                "hard_data": [],
                "visual_subjects": [
                    {
                        "cue_index": 1,
                        "timestamp": "00:00:10",
                        "subject_label": "Casa Rosada",
                        "asset_kind": "event_photo",
                        "context_text": "Sede del ejecutivo",
                    }
                ],
            },
            {
                "start_cue_index": 6,
                "end_cue_index": 20,
                "start_time": "00:01:00",
                "end_time": "00:03:00",
                "title": "Coyuntura",
                "summary": "Gobierno e inflación.",
                "suggested_lower_third": "Coyuntura",
                "hard_data": [],
                "visual_subjects": [
                    {
                        "cue_index": 7,
                        "timestamp": "00:01:10",
                        "subject_label": "gobierno",
                        "asset_kind": "event_photo",
                        "context_text": "primera",
                    },
                    {
                        "cue_index": 8,
                        "timestamp": "00:01:20",
                        "subject_label": "Gobierno",
                        "asset_kind": "event_photo",
                        "context_text": "segunda",
                    },
                    {
                        "cue_index": 9,
                        "timestamp": "00:01:30",
                        "subject_label": "  gobierno  ",
                        "asset_kind": "event_photo",
                        "context_text": "tercera",
                    },
                    {
                        "cue_index": 10,
                        "timestamp": "00:01:40",
                        "subject_label": "GOBIERNO",
                        "asset_kind": "event_photo",
                        "context_text": "cuarta",
                    },
                    {
                        "cue_index": 11,
                        "timestamp": "00:01:50",
                        "subject_label": "gobierno",
                        "asset_kind": "event_photo",
                        "context_text": "quinta",
                    },
                    {
                        "cue_index": 12,
                        "timestamp": "00:02:00",
                        "subject_label": "inflación",
                        "asset_kind": "conceptual_illustration",
                        "context_text": "concepto",
                    },
                    {
                        "cue_index": 13,
                        "timestamp": "00:02:10",
                        "subject_label": "fallido",
                        "asset_kind": "event_photo",
                        "context_text": "error",
                    },
                ],
            },
        ]
    }


def _default_planner() -> _MultiPlanner:
    return _MultiPlanner(
        {
            "Casa Rosada": VisualQueryPlan(
                search_query="Casa Rosada",
                preferred_provider="wikimedia",
                rationale="foto",
            ),
            "gobierno": VisualQueryPlan(
                search_query="gobierno",
                preferred_provider="wikimedia",
                rationale="foto",
            ),
            "inflación": VisualQueryPlan(
                search_query="inflación",
                preferred_provider="openverse",
                rationale="concepto",
            ),
            "fallido": VisualQueryPlan(
                search_query="fallido",
                preferred_provider="wikimedia",
                rationale="x",
            ),
        }
    )


def _default_fetcher() -> _FetcherFake:
    return _FetcherFake(
        ok_labels={"Casa Rosada", "gobierno"},
        none_labels={"inflación"},
        error_labels={"fallido": VisualProviderResponseError("HTTP 503")},
    )


def test_cli_e2e_offline_no_llm(tmp_path: Path) -> None:
    chapters_path = tmp_path / "chapters.json"
    chapters_path.write_text(json.dumps(_chapters_payload()), encoding="utf-8")
    output = tmp_path / "assets.json"
    assets_dir = tmp_path / "assets"
    markdown = tmp_path / "assets.md"

    code = run_cli(
        [
            "--input",
            str(chapters_path),
            "--output",
            str(output),
            "--assets-dir",
            str(assets_dir),
            "--markdown",
            str(markdown),
            "--no-llm",
            "--portrait-layout",
            "sidebar",
        ],
        planner=_default_planner(),
        fetcher=_default_fetcher(),  # type: ignore[arg-type]
    )
    assert code == EXIT_OK
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["portrait_layout"] == "sidebar"
    items = payload["items"]
    assert len(items) == 4
    by_label = {item["subject_label"]: item for item in items}
    assert by_label["gobierno"]["occurrences_count"] == 5
    assert by_label["Casa Rosada"]["status"] == "verified_asset"
    assert by_label["gobierno"]["status"] == "verified_asset"
    assert by_label["inflación"]["status"] == "fallback_card"
    assert by_label["fallido"]["status"] == "fetch_error"
    assert markdown.is_file()
    assert any(assets_dir.glob("*.html"))
    assert any((assets_dir / "images").glob("*.jpg"))


def test_cli_portrait_layout_contain(tmp_path: Path) -> None:
    chapters_path = tmp_path / "chapters.json"
    chapters_path.write_text(json.dumps(_chapters_payload()), encoding="utf-8")
    code = run_cli(
        [
            "--input",
            str(chapters_path),
            "--output",
            str(tmp_path / "assets.json"),
            "--assets-dir",
            str(tmp_path / "assets"),
            "--no-llm",
            "--portrait-layout",
            "contain",
        ],
        planner=_default_planner(),
        fetcher=_default_fetcher(),  # type: ignore[arg-type]
    )
    assert code == EXIT_OK
    payload = json.loads((tmp_path / "assets.json").read_text(encoding="utf-8"))
    assert payload["portrait_layout"] == "contain"
    assert all(item["portrait_layout"] == "contain" for item in payload["items"])


def test_cli_sin_env_llm_falla(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TIGANI_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("TIGANI_LLM_MODEL", raising=False)
    chapters_path = tmp_path / "chapters.json"
    chapters_path.write_text(json.dumps(_chapters_payload()), encoding="utf-8")
    code = run_cli(
        [
            "--input",
            str(chapters_path),
            "--output",
            str(tmp_path / "out.json"),
            "--assets-dir",
            str(tmp_path / "assets"),
        ],
        planner=None,
        fetcher=_default_fetcher(),  # type: ignore[arg-type]
    )
    assert code == EXIT_ERROR


def test_cli_input_inexistente(tmp_path: Path) -> None:
    code = run_cli(
        [
            "--input",
            str(tmp_path / "missing.json"),
            "--output",
            str(tmp_path / "out.json"),
            "--assets-dir",
            str(tmp_path / "assets"),
            "--no-llm",
        ],
        planner=_PlannerFake(
            VisualQueryPlan(
                search_query="x",
                preferred_provider="wikimedia",
                rationale="x",
            )
        ),
        fetcher=_FetcherFake(),  # type: ignore[arg-type]
    )
    assert code == EXIT_ERROR


def test_cli_json_invalido(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{nope", encoding="utf-8")
    code = run_cli(
        [
            "--input",
            str(bad),
            "--output",
            str(tmp_path / "out.json"),
            "--assets-dir",
            str(tmp_path / "assets"),
            "--no-llm",
        ],
        planner=_PlannerFake(
            VisualQueryPlan(
                search_query="x",
                preferred_provider="wikimedia",
                rationale="x",
            )
        ),
        fetcher=_FetcherFake(),  # type: ignore[arg-type]
    )
    assert code == EXIT_ERROR


def test_cli_portrait_layout_invalido(tmp_path: Path) -> None:
    chapters_path = tmp_path / "chapters.json"
    chapters_path.write_text(json.dumps(_chapters_payload()), encoding="utf-8")
    code = run_cli(
        [
            "--input",
            str(chapters_path),
            "--output",
            str(tmp_path / "out.json"),
            "--assets-dir",
            str(tmp_path / "assets"),
            "--portrait-layout",
            "zoom",
            "--no-llm",
        ],
        planner=_PlannerFake(
            VisualQueryPlan(
                search_query="x",
                preferred_provider="wikimedia",
                rationale="x",
            )
        ),
        fetcher=_FetcherFake(),  # type: ignore[arg-type]
    )
    assert code == EXIT_ERROR


def test_main_module_exporta_main() -> None:
    from tigani_broadcast.visual_assets_fetcher import __main__ as mod

    assert callable(mod.main)


def test_visual_assets_cli_error_mensaje() -> None:
    with pytest.raises(VisualAssetsCliError):
        raise VisualAssetsCliError("boom")
