"""Render JSON/MD/HTML 16:9 con crédito y portrait_layout (cero red)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from tigani_broadcast.visual_assets_fetcher.models import (
    VisualAssetArtifact,
    VisualAssetsPackage,
    VisualAttribution,
)
from tigani_broadcast.visual_assets_fetcher.render import (
    render_assets_json,
    render_assets_markdown,
    render_visual_artifact_html,
    write_visual_assets_package,
)


def _attribution(**overrides: object) -> VisualAttribution:
    payload: dict[str, object] = {
        "provider": "wikimedia",
        "author": "María Pérez",
        "license_name": "CC BY-SA 4.0",
        "license_code": "CC-BY-SA",
        "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
        "source_page_url": "https://commons.wikimedia.org/wiki/File:Casa.jpg",
        "image_url": "https://upload.wikimedia.org/casa.jpg",
        "width": 1280,
        "height": 720,
        "mime_type": "image/jpeg",
    }
    payload.update(overrides)
    return VisualAttribution.model_validate(payload)


def _verified(**overrides: object) -> VisualAssetArtifact:
    payload: dict[str, object] = {
        "chapter_index": 0,
        "cue_index": 1,
        "timestamp": "00:00:07",
        "subject_label": "Casa Rosada",
        "asset_kind": "event_photo",
        "context_text": "Sede del ejecutivo",
        "occurrences_count": 1,
        "search_query": "Casa Rosada",
        "status": "verified_asset",
        "portrait_layout": "sidebar",
        "attribution": _attribution(),
        "local_image_path": "images/ch00_cue001_00.jpg",
    }
    payload.update(overrides)
    return VisualAssetArtifact.model_validate(payload)


def _fallback() -> VisualAssetArtifact:
    return VisualAssetArtifact(
        chapter_index=1,
        cue_index=2,
        timestamp="00:01:00",
        subject_label="inflación",
        asset_kind="conceptual_illustration",
        context_text="concepto abstracto",
        occurrences_count=3,
        search_query="inflation concept",
        status="fallback_card",
    )


def _error() -> VisualAssetArtifact:
    return VisualAssetArtifact(
        chapter_index=2,
        cue_index=3,
        timestamp="00:02:00",
        subject_label="BCRA",
        asset_kind="event_photo",
        context_text="banco",
        occurrences_count=1,
        search_query="BCRA",
        status="fetch_error",
        error_message="HTTP 500",
    )


def test_render_assets_json_y_markdown() -> None:
    package = VisualAssetsPackage(
        source_chapters_path="out/video.chapters.json",
        portrait_layout="sidebar",
        items=[_verified(), _fallback(), _error()],
    )
    payload = json.loads(render_assets_json(package))
    assert payload["items"][0]["status"] == "verified_asset"
    assert "María Pérez" in payload["items"][0]["attribution"]["author"]

    md = render_assets_markdown(package)
    assert "Paquete de activos visuales" in md
    assert "verified_asset" in md
    assert "fallback_card" in md
    assert "fetch_error" in md
    assert "Casa Rosada" in md
    assert "María Pérez" in md
    assert "CC BY-SA 4.0" in md
    assert "wikimedia" in md
    assert "images/ch00_cue001_00.jpg" in md
    assert "| Occ |" in md or "Occ" in md


def test_html_verified_horizontal_credito_y_ruta_relativa() -> None:
    html = render_visual_artifact_html(
        _verified(),
        relative_image_src="images/ch00_cue001_00.jpg",
    )
    assert 'data-status="verified_asset"' in html
    assert 'src="images/ch00_cue001_00.jpg"' in html
    assert "landscape-layout" in html
    assert "María Pérez" in html
    assert "CC BY-SA 4.0" in html
    assert "wikimedia" in html
    assert "min-width: 960px" in html
    assert "min-height: 540px" in html
    assert "max-width: 1920px" not in html
    assert "max-height: 1080px" not in html
    assert "object-fit: cover" in html
    assert "object-fit: contain" in html
    assert not re.search(r"https?://(?:cdn\.|fonts\.|unpkg|jsdelivr)", html)
    assert "<script" not in html
    assert 'rel="stylesheet"' not in html


def test_html_retrato_sidebar_y_contain() -> None:
    portrait = _verified(
        attribution=_attribution(width=800, height=1200),
        portrait_layout="sidebar",
    )
    html_sidebar = render_visual_artifact_html(portrait, relative_image_src="images/p.jpg")
    assert "sidebar-layout" in html_sidebar
    assert "media sidebar" in html_sidebar
    assert "Sede del ejecutivo" in html_sidebar
    assert "María Pérez" in html_sidebar
    assert "CC BY-SA 4.0" in html_sidebar
    assert "wikimedia" in html_sidebar

    html_contain = render_visual_artifact_html(
        portrait.model_copy(update={"portrait_layout": "contain"}),
        relative_image_src="images/p.jpg",
    )
    assert "contain-layout" in html_contain
    assert "media contain" in html_contain
    assert "object-fit: contain" in html_contain
    assert "María Pérez" in html_contain
    assert "CC BY-SA 4.0" in html_contain


def test_html_escapea_contenido() -> None:
    artifact = _verified(
        subject_label='Gobierno <script>alert("x")</script>',
        context_text="A & B",
        attribution=_attribution(width=800, height=1200),
        portrait_layout="sidebar",
    )
    html = render_visual_artifact_html(artifact, relative_image_src="images/x.jpg")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "A &amp; B" in html


def test_html_fallback_y_error() -> None:
    fallback = render_visual_artifact_html(_fallback())
    assert "Placa contextual — sin imagen con licencia verificada" in fallback
    assert 'data-status="fallback_card"' in fallback
    assert "concepto abstracto" in fallback

    error = render_visual_artifact_html(_error())
    assert "HTTP 500" in error
    assert 'data-status="fetch_error"' in error
    assert "BCRA" in error


def test_write_visual_assets_package_actualiza_html_path(tmp_path: Path) -> None:
    images = tmp_path / "assets" / "images"
    images.mkdir(parents=True)
    image_path = images / "ch00_cue001_00.jpg"
    image_path.write_bytes(b"\xff\xd8\xff")

    package = VisualAssetsPackage(
        items=[
            _verified(local_image_path=str(image_path)),
            _fallback(),
            _error(),
        ]
    )
    result = write_visual_assets_package(
        package,
        output_json=tmp_path / "out" / "assets.json",
        assets_dir=tmp_path / "assets",
        markdown_path=tmp_path / "out" / "assets.md",
    )
    assert all(item.html_path for item in result.items)
    html_file = Path(result.items[0].html_path or "")
    assert html_file.is_file()
    content = html_file.read_text(encoding="utf-8")
    assert 'src="images/ch00_cue001_00.jpg"' in content
    assert (tmp_path / "out" / "assets.json").is_file()
    assert (tmp_path / "out" / "assets.md").is_file()
    assert "Imagen verificada" in content
