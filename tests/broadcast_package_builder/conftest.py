"""Fixtures sintéticas offline para broadcast-package-builder."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from tigani_broadcast.official_data_charts.models import (
    ChartArtifact,
    ChartsPackage,
    ProviderId,
    SeriesData,
    SeriesMetrics,
    SeriesObservation,
)
from tigani_broadcast.transcript_chapterizer.models import Chapter, ChapterizedTranscript
from tigani_broadcast.visual_assets_fetcher.models import (
    VisualAssetArtifact,
    VisualAssetsPackage,
    VisualAttribution,
)


def make_chapter(
    *,
    start_cue: int,
    end_cue: int,
    start_time: str,
    end_time: str,
    title: str,
    summary: str | None = None,
) -> Chapter:
    return Chapter(
        start_cue_index=start_cue,
        end_cue_index=end_cue,
        start_time=start_time,
        end_time=end_time,
        title=title,
        summary=summary or f"Resumen de {title}",
        suggested_lower_third=title[:40],
    )


def make_chapters() -> ChapterizedTranscript:
    return ChapterizedTranscript(
        chapters=[
            make_chapter(
                start_cue=0,
                end_cue=20,
                start_time="00:00:00",
                end_time="00:03:00",
                title="Apertura e inflación",
            ),
            make_chapter(
                start_cue=21,
                end_cue=40,
                start_time="00:03:01",
                end_time="00:05:00",
                title="Reservas y deuda",
            ),
        ]
    )


def make_series(*, series_id: str = "ipc", provider: ProviderId = "indec") -> SeriesData:
    return SeriesData(
        catalog_id="ar_indec_ipc_mensual",
        provider=provider,
        source_tier="official_primary",
        series_id=series_id,
        source_url=f"https://example.org/{series_id}",
        source_attribution="Fuente: INDEC",
        unit="%",
        frequency="monthly",
        observations=[
            SeriesObservation(obs_date=date(2025, 1, 1), value=2.0),
            SeriesObservation(obs_date=date(2025, 2, 1), value=2.5),
        ],
    )


def make_metrics() -> SeriesMetrics:
    return SeriesMetrics(
        observation_count=2,
        valid_count=2,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 2, 1),
        first_value=2.0,
        latest_value=2.5,
        min_value=2.0,
        min_date=date(2025, 1, 1),
        max_value=2.5,
        max_date=date(2025, 2, 1),
        absolute_change=0.5,
        percent_change=25.0,
        has_provisional_flags=False,
        flags_present=[],
    )


def make_attribution(**overrides: object) -> VisualAttribution:
    payload: dict[str, object] = {
        "provider": "wikimedia",
        "author": "Jane Doe",
        "license_name": "CC BY 4.0",
        "license_code": "CC-BY",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "source_page_url": "https://commons.wikimedia.org/wiki/File:Example.jpg",
        "image_url": "https://upload.wikimedia.org/wikipedia/commons/example.jpg",
        "width": 1280,
        "height": 720,
        "mime_type": "image/jpeg",
    }
    payload.update(overrides)
    return VisualAttribution.model_validate(payload)


def write_text(path: Path, content: str = "<html></html>") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def write_bytes(path: Path, content: bytes = b"fake-image") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def make_chart(
    tmp_path: Path,
    *,
    chapter_index: int = 0,
    cue_index: int = 14,
    timestamp: str = "00:01:50",
    indicator_label: str = "IPC",
    resolution_status: str = "verified_series",
    series: SeriesData | None = None,
    filename: str = "ch00_cue014_00.html",
    error_message: str | None = None,
    raw_value_text: str = "2,5%",
) -> ChartArtifact:
    html_path = write_text(tmp_path / "charts_src" / filename, f"<html>{indicator_label}</html>")
    payload: dict[str, object] = {
        "chapter_index": chapter_index,
        "cue_index": cue_index,
        "timestamp": timestamp,
        "indicator_label": indicator_label,
        "raw_value_text": raw_value_text,
        "time_reference": "febrero",
        "resolution_status": resolution_status,
        "rationale": "Mención verificable en catálogo",
        "html_path": str(html_path),
    }
    if resolution_status == "verified_series":
        payload["series"] = series or make_series()
        payload["metrics"] = make_metrics()
    elif resolution_status == "fetch_error":
        payload["error_message"] = error_message or "API timeout"
    return ChartArtifact.model_validate(payload)


def make_visual(
    tmp_path: Path,
    *,
    chapter_index: int = 0,
    cue_index: int = 14,
    timestamp: str = "00:01:50",
    subject_label: str = "gobierno",
    status: str = "verified_asset",
    filename: str = "ch00_cue014_00.html",
    image_name: str = "gobierno.jpg",
    attribution: VisualAttribution | None = None,
    error_message: str | None = None,
) -> VisualAssetArtifact:
    html_path = write_text(
        tmp_path / "assets_src" / filename,
        f'<html><img src="images/{image_name}"/></html>',
    )
    payload: dict[str, object] = {
        "chapter_index": chapter_index,
        "cue_index": cue_index,
        "timestamp": timestamp,
        "subject_label": subject_label,
        "asset_kind": "event_photo",
        "context_text": f"Contexto de {subject_label}",
        "occurrences_count": 1,
        "search_query": subject_label,
        "status": status,
        "html_path": str(html_path),
    }
    if status == "verified_asset":
        image_path = write_bytes(tmp_path / "assets_src" / "images" / image_name)
        payload["attribution"] = attribution or make_attribution()
        payload["local_image_path"] = str(image_path)
    elif status == "fetch_error":
        payload["error_message"] = error_message or "sin candidatos seguros"
    return VisualAssetArtifact.model_validate(payload)


@pytest.fixture
def sample_chapters() -> ChapterizedTranscript:
    return make_chapters()


@pytest.fixture
def sample_charts(tmp_path: Path) -> ChartsPackage:
    return ChartsPackage(
        publish_date=date(2025, 11, 25),
        items=[make_chart(tmp_path)],
    )


@pytest.fixture
def sample_assets(tmp_path: Path) -> VisualAssetsPackage:
    return VisualAssetsPackage(items=[make_visual(tmp_path)])
