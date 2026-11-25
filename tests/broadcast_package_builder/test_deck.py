"""Player OBS y portadas de capítulo: offline, sin CDN, escape seguro."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from tigani_broadcast.broadcast_package_builder.assemble import assemble_broadcast_package
from tigani_broadcast.broadcast_package_builder.deck import (
    render_chapter_cover_html,
    render_deck_html,
    write_deck_files,
)
from tigani_broadcast.broadcast_package_builder.models import (
    BroadcastPackageManifest,
    PackageSlide,
)
from tigani_broadcast.official_data_charts.models import ChartsPackage
from tigani_broadcast.visual_assets_fetcher.models import VisualAssetsPackage

from .conftest import make_chapters, make_chart, make_visual


def test_render_chapter_cover_html_16x9_escape() -> None:
    html_doc = render_chapter_cover_html(
        0,
        "Inflación <script>alert(1)</script>",
        "Resumen con <b>HTML</b> & más",
        "00:00:00",
        'Video "piloto"',
    )
    assert "aspect-ratio: 16 / 9" in html_doc
    assert "1080px" in html_doc
    assert "cdn." not in html_doc.lower()
    assert "&lt;script&gt;" in html_doc
    assert "<script>alert" not in html_doc
    assert "&lt;b&gt;HTML&lt;/b&gt;" in html_doc
    assert "Video &quot;piloto&quot;" in html_doc
    assert "Capítulo 01" in html_doc


def test_render_deck_html_controles_hud_y_escape(tmp_path: Path) -> None:
    chapters = make_chapters()
    charts = ChartsPackage(publish_date=date(2025, 11, 25), items=[make_chart(tmp_path)])
    assets = VisualAssetsPackage(
        items=[
            make_visual(
                tmp_path,
                subject_label="gobierno </script><img src=x>",
                filename="evil.html",
                image_name="evil.jpg",
            )
        ]
    )
    manifest = assemble_broadcast_package(
        chapters,
        charts,
        assets,
        output_dir=tmp_path / "pkg",
        video_title="Piloto",
    )
    deck = render_deck_html(manifest)

    assert "cdn." not in deck.lower()
    assert "background: #000" in deck
    assert "ArrowRight" in deck
    assert 'event.key === " "' in deck
    assert "ArrowLeft" in deck
    assert "Home" in deck
    assert "End" in deck
    assert 'event.key === "H"' in deck
    assert 'params.get("hud") === "1"' in deck
    assert "hud.classList.add(" in deck
    assert "<\\/" in deck
    assert "</script><img" not in deck
    assert "slides/charts/" in deck
    assert "slides/visuals/" in deck
    assert "/tmp/" not in deck
    assert "file://" not in deck


def test_render_deck_html_sin_slides() -> None:
    manifest = BroadcastPackageManifest(
        video_title="Vacío",
        publish_date=date(2025, 11, 25),
        chapter_count=1,
        slides=[],
        excluded_errors=[],
        data_sources=[],
        visual_credits=[],
    )
    deck = render_deck_html(manifest)
    assert "Sin placas" in deck or "Rotación vacía" in deck
    assert "const SLIDES = []" in deck
    assert "ArrowRight" in deck


def test_write_deck_files_escribe_covers_deck_y_package(tmp_path: Path) -> None:
    chapters = make_chapters()
    charts = ChartsPackage(publish_date=date(2025, 11, 25), items=[make_chart(tmp_path)])
    assets = VisualAssetsPackage(items=[make_visual(tmp_path)])
    output_dir = tmp_path / "package"
    manifest = assemble_broadcast_package(
        chapters,
        charts,
        assets,
        output_dir=output_dir,
        video_title="Piloto OBS",
    )

    write_deck_files(chapters, manifest, output_dir)

    cover0 = output_dir / "slides" / "chapters" / "ch00_cover.html"
    cover1 = output_dir / "slides" / "chapters" / "ch01_cover.html"
    deck_path = output_dir / "deck.html"
    package_path = output_dir / "package.json"

    assert cover0.is_file()
    assert cover1.is_file()
    assert "Apertura e inflación" in cover0.read_text(encoding="utf-8")
    assert deck_path.is_file()
    payload = json.loads(package_path.read_text(encoding="utf-8"))
    assert payload["video_title"] == "Piloto OBS"
    assert payload["chapter_count"] == 2
    assert len(payload["slides"]) == len(manifest.slides)


def test_write_deck_files_sin_covers(tmp_path: Path) -> None:
    chapters = make_chapters()
    charts = ChartsPackage(publish_date=date(2025, 11, 25), items=[make_chart(tmp_path)])
    assets = VisualAssetsPackage(items=[make_visual(tmp_path)])
    output_dir = tmp_path / "package"
    manifest = assemble_broadcast_package(
        chapters,
        charts,
        assets,
        output_dir=output_dir,
        video_title="Sin covers",
        include_chapter_covers=False,
    )

    write_deck_files(chapters, manifest, output_dir)

    assert not (output_dir / "slides" / "chapters" / "ch00_cover.html").exists()
    assert (output_dir / "deck.html").is_file()
    assert (output_dir / "package.json").is_file()


def test_deck_embebe_slide_relativo() -> None:
    slide = PackageSlide(
        slide_index=0,
        chapter_index=0,
        chapter_title="Apertura",
        cue_index=0,
        timestamp="00:00:00",
        kind="chart",
        status="verified_series",
        title="IPC",
        relative_html_path="slides/charts/ch00.html",
    )
    manifest = BroadcastPackageManifest(
        video_title="T",
        publish_date=date(2025, 1, 1),
        chapter_count=1,
        slides=[slide],
        excluded_errors=[],
        data_sources=[],
        visual_credits=[],
    )
    deck = render_deck_html(manifest)
    assert '"relative_html_path": "slides/charts/ch00.html"' in deck
