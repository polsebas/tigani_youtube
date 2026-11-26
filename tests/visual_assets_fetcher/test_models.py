"""Contratos Pydantic: casos felices, bordes y rechazos fail-closed."""

import pytest
from pydantic import ValidationError

from tigani_broadcast.visual_assets_fetcher.models import (
    DeduplicatedVisualSubject,
    VisualAssetArtifact,
    VisualAssetsPackage,
    VisualAttribution,
    VisualQueryPlan,
)


def _attribution(**overrides: object) -> VisualAttribution:
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


def _artifact(**overrides: object) -> VisualAssetArtifact:
    payload: dict[str, object] = {
        "chapter_index": 0,
        "cue_index": 1,
        "timestamp": "00:01:00",
        "subject_label": "gobierno",
        "asset_kind": "event_photo",
        "context_text": "Mención al gobierno nacional",
        "occurrences_count": 1,
        "search_query": "gobierno argentina",
        "status": "fallback_card",
    }
    payload.update(overrides)
    return VisualAssetArtifact.model_validate(payload)


def test_visual_attribution_acepta_payload_completo() -> None:
    attribution = _attribution()
    assert attribution.provider == "wikimedia"
    assert attribution.width == 1280
    assert attribution.license_url is not None


def test_visual_attribution_acepta_dimensiones_desconocidas() -> None:
    attribution = _attribution(width=None, height=None)
    assert attribution.width is None
    assert attribution.height is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("author", ""),
        ("license_name", ""),
        ("license_code", ""),
        ("source_page_url", ""),
        ("image_url", ""),
        ("width", 0),
        ("height", -1),
        ("mime_type", ""),
    ],
)
def test_visual_attribution_rechaza_campos_invalidos(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        _attribution(**{field: value})


def test_visual_attribution_rechaza_campos_extra() -> None:
    with pytest.raises(ValidationError):
        VisualAttribution.model_validate(
            {
                **_attribution().model_dump(),
                "extra_field": "no",
            }
        )


def test_visual_query_plan_limites_de_longitud() -> None:
    plan = VisualQueryPlan(
        search_query="gobierno",
        preferred_provider="openverse",
        rationale="Consulta conceptual genérica",
    )
    assert plan.preferred_provider == "openverse"

    with pytest.raises(ValidationError):
        VisualQueryPlan(
            search_query="",
            preferred_provider="wikimedia",
            rationale="x",
        )
    with pytest.raises(ValidationError):
        VisualQueryPlan(
            search_query="a" * 161,
            preferred_provider="wikimedia",
            rationale="ok",
        )
    with pytest.raises(ValidationError):
        VisualQueryPlan(
            search_query="ok",
            preferred_provider="wikimedia",
            rationale="a" * 241,
        )


def test_deduplicated_visual_subject_rechaza_occurrences_cero() -> None:
    with pytest.raises(ValidationError):
        DeduplicatedVisualSubject(
            chapter_index=0,
            cue_index=0,
            timestamp="00:00:01",
            subject_label="gobierno",
            normalized_label="gobierno",
            asset_kind="event_photo",
            context_text="contexto",
            occurrences_count=0,
        )


def test_verified_asset_exige_attribution_y_local_path() -> None:
    artifact = _artifact(
        status="verified_asset",
        attribution=_attribution(),
        local_image_path="images/gobierno.jpg",
        html_path="plates/gobierno.html",
    )
    assert artifact.status == "verified_asset"
    assert artifact.portrait_layout == "sidebar"


@pytest.mark.parametrize(
    "overrides",
    [
        {"attribution": None, "local_image_path": "images/x.jpg"},
        {"attribution": _attribution(), "local_image_path": None},
        {"attribution": _attribution(), "local_image_path": "  "},
        {
            "attribution": _attribution(),
            "local_image_path": "images/x.jpg",
            "error_message": "no debería",
        },
    ],
)
def test_verified_asset_fail_closed(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _artifact(status="verified_asset", **overrides)


def test_fallback_card_sin_attribution_ni_error() -> None:
    artifact = _artifact(status="fallback_card")
    assert artifact.attribution is None
    assert artifact.local_image_path is None
    assert artifact.error_message is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"attribution": _attribution()},
        {"local_image_path": "images/x.jpg"},
        {"error_message": "algo"},
    ],
)
def test_fallback_card_fail_closed(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _artifact(status="fallback_card", **overrides)


def test_fetch_error_exige_mensaje() -> None:
    artifact = _artifact(status="fetch_error", error_message="HTTP 500")
    assert artifact.error_message == "HTTP 500"


@pytest.mark.parametrize(
    "overrides",
    [
        {"error_message": None},
        {"error_message": "  "},
        {"error_message": "HTTP 500", "attribution": _attribution()},
        {"error_message": "HTTP 500", "local_image_path": "images/x.jpg"},
    ],
)
def test_fetch_error_fail_closed(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _artifact(status="fetch_error", **overrides)


def test_visual_assets_package_defaults() -> None:
    package = VisualAssetsPackage(items=[_artifact()])
    assert package.source_chapters_path is None
    assert package.portrait_layout == "sidebar"
    assert len(package.items) == 1

    with pytest.raises(ValidationError):
        VisualAssetsPackage.model_validate({"items": [], "extra": True})
