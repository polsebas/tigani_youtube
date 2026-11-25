"""Contratos Pydantic: casos felices y rechazos fail-closed del manifiesto."""

from datetime import date

import pytest
from pydantic import ValidationError

from tigani_broadcast.broadcast_package_builder.models import (
    BroadcastPackageManifest,
    DataSourceCredit,
    ExcludedErrorRecord,
    PackageSlide,
    VisualLicenseCredit,
)


def _slide(**overrides: object) -> PackageSlide:
    payload: dict[str, object] = {
        "slide_index": 0,
        "chapter_index": 0,
        "chapter_title": "Apertura",
        "cue_index": 0,
        "timestamp": "00:00:00",
        "kind": "chapter_cover",
        "status": "chapter_cover",
        "title": "Apertura",
        "relative_html_path": "slides/chapters/ch00_cover.html",
    }
    payload.update(overrides)
    return PackageSlide.model_validate(payload)


def _manifest(**overrides: object) -> BroadcastPackageManifest:
    payload: dict[str, object] = {
        "video_title": "Episodio piloto",
        "video_url": None,
        "publish_date": date(2025, 11, 25),
        "include_chapter_covers": True,
        "include_errors": False,
        "chapter_count": 1,
        "slides": [_slide()],
        "excluded_errors": [],
        "data_sources": [],
        "visual_credits": [],
    }
    payload.update(overrides)
    return BroadcastPackageManifest.model_validate(payload)


def test_package_slide_acepta_payload_completo() -> None:
    slide = _slide(source_ref="series-1")
    assert slide.kind == "chapter_cover"
    assert slide.source_ref == "series-1"


@pytest.mark.parametrize(
    "field,value",
    [
        ("slide_index", -1),
        ("chapter_index", -1),
        ("chapter_title", ""),
        ("cue_index", -1),
        ("timestamp", ""),
        ("status", ""),
        ("title", ""),
        ("relative_html_path", ""),
        ("kind", "unknown"),
    ],
)
def test_package_slide_rechaza_campos_invalidos(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        _slide(**{field: value})


def test_package_slide_rechaza_campos_extra() -> None:
    with pytest.raises(ValidationError):
        PackageSlide.model_validate({**_slide().model_dump(), "extra": True})


def test_data_source_y_visual_credit_rechazan_vacios() -> None:
    with pytest.raises(ValidationError):
        DataSourceCredit(
            provider="",
            source_tier="official_primary",
            series_id="1",
            source_attribution="Fuente",
            source_url="https://example.org",
        )
    with pytest.raises(ValidationError):
        VisualLicenseCredit(
            provider="wikimedia",
            author="",
            license_name="CC0",
            license_code="CC0",
            source_page_url="https://commons.wikimedia.org/wiki/File:X.jpg",
        )


def test_excluded_error_record_acepta_chart_y_visual() -> None:
    chart = ExcludedErrorRecord(
        chapter_index=0,
        cue_index=2,
        timestamp="00:00:20",
        kind="chart",
        title="IPC",
        error_message="timeout",
    )
    visual = ExcludedErrorRecord.model_validate(
        {**chart.model_dump(), "kind": "visual", "title": "gobierno"}
    )
    assert chart.kind == "chart"
    assert visual.kind == "visual"
    with pytest.raises(ValidationError):
        ExcludedErrorRecord.model_validate({**chart.model_dump(), "kind": "chapter_cover"})


def test_manifest_acepta_slides_secuenciales_relativos() -> None:
    slides = [
        _slide(slide_index=0, kind="chapter_cover"),
        _slide(
            slide_index=1,
            kind="chart",
            status="verified_series",
            title="IPC",
            relative_html_path="slides/charts/ch00_cue014_00.html",
            cue_index=14,
            timestamp="00:01:50",
        ),
        _slide(
            slide_index=2,
            kind="visual",
            status="verified_asset",
            title="gobierno",
            relative_html_path="slides/visuals/ch00_cue014_00.html",
            cue_index=14,
            timestamp="00:01:50",
        ),
    ]
    manifest = _manifest(slides=slides)
    assert len(manifest.slides) == 3
    assert manifest.slides[1].kind == "chart"


def test_manifest_rechaza_slide_index_no_secuencial() -> None:
    slides = [
        _slide(slide_index=0),
        _slide(slide_index=2, kind="chart", status="quoted_only", title="IPC"),
    ]
    with pytest.raises(ValidationError, match="slide_index tiene que ser secuencial"):
        _manifest(slides=slides)


def test_manifest_rechaza_ruta_absoluta_en_relative_html_path() -> None:
    slides = [
        _slide(relative_html_path="/tmp/slides/chapters/ch00_cover.html"),
    ]
    with pytest.raises(ValidationError, match="no puede ser ruta absoluta"):
        _manifest(slides=slides)


def test_manifest_rechaza_campos_extra() -> None:
    with pytest.raises(ValidationError):
        BroadcastPackageManifest.model_validate({**_manifest().model_dump(), "extra": 1})


def test_manifest_rechaza_chapter_count_cero() -> None:
    with pytest.raises(ValidationError):
        _manifest(chapter_count=0)
