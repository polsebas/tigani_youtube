"""Kit de publicación y rundown: determinista, sin cifras inventadas."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from tigani_broadcast.broadcast_package_builder.assemble import assemble_broadcast_package
from tigani_broadcast.broadcast_package_builder.models import (
    BroadcastPackageManifest,
    DataSourceCredit,
    ExcludedErrorRecord,
    PackageSlide,
    VisualLicenseCredit,
)
from tigani_broadcast.broadcast_package_builder.publishing import (
    render_rundown_markdown,
    render_social_post,
    render_youtube_description,
    write_publishing_files,
)
from tigani_broadcast.official_data_charts.models import ChartsPackage
from tigani_broadcast.transcript_chapterizer.models import ChapterizedTranscript
from tigani_broadcast.visual_assets_fetcher.models import VisualAssetsPackage

from .conftest import make_chapter, make_chapters, make_chart, make_visual


def test_youtube_description_empieza_en_00_00_con_fuentes_y_creditos(tmp_path: Path) -> None:
    chapters = ChapterizedTranscript(
        chapters=[
            make_chapter(
                start_cue=0,
                end_cue=10,
                start_time="00:00:05",
                end_time="00:02:00",
                title="Apertura",
            ),
            make_chapter(
                start_cue=11,
                end_cue=20,
                start_time="00:02:00",
                end_time="00:04:00",
                title="Coyuntura",
            ),
            make_chapter(
                start_cue=21,
                end_cue=30,
                start_time="01:05:00",
                end_time="01:10:00",
                title="Cierre largo",
            ),
        ]
    )
    charts = ChartsPackage(publish_date=date(2025, 11, 25), items=[make_chart(tmp_path)])
    assets = VisualAssetsPackage(items=[make_visual(tmp_path)])
    manifest = assemble_broadcast_package(
        chapters,
        charts,
        assets,
        output_dir=tmp_path / "pkg",
        video_title="Inflación y reservas",
    )

    text = render_youtube_description(chapters, manifest)
    assert text.startswith("Inflación y reservas\n")
    assert "Fecha de publicación: 2025-11-25" in text
    assert "Capítulos\n00:00 Apertura\n" in text
    assert "02:00 Coyuntura" in text
    assert "01:05:00 Cierre largo" in text
    assert "Fuentes de datos" in text
    assert "Fuente: INDEC" in text
    assert "series_id=ipc" in text
    assert "Créditos y licencias de imágenes" in text
    assert "Jane Doe" in text
    assert "CC BY 4.0" in text
    assert "wikimedia" in text


def test_social_post_con_y_sin_video_url(tmp_path: Path) -> None:
    chapters = make_chapters()
    charts = ChartsPackage(
        publish_date=date(2025, 11, 25),
        items=[
            make_chart(tmp_path),
            make_chart(
                tmp_path,
                cue_index=15,
                timestamp="00:02:00",
                indicator_label="Dólar blue",
                resolution_status="quoted_only",
                filename="quoted.html",
                raw_value_text="1200 pesos",
            ),
        ],
    )
    assets = VisualAssetsPackage(items=[make_visual(tmp_path)])

    with_url = assemble_broadcast_package(
        chapters,
        charts,
        assets,
        output_dir=tmp_path / "pkg_url",
        video_title="Episodio piloto",
        video_url="https://youtu.be/abc123",
    )
    post_url = render_social_post(chapters, charts, with_url)
    assert "Episodio piloto" in post_url
    assert "https://youtu.be/abc123" in post_url
    assert "[LINK_VIDEO]" not in post_url
    assert "último dato oficial 2.5 %" in post_url
    assert "Dólar blue" in post_url
    assert "1200 pesos" in post_url
    assert "#Economía" in post_url
    assert "#Argentina" in post_url
    assert "#AnálisisEconómico" in post_url
    assert 2 <= post_url.count("• ") <= 4

    without_url = assemble_broadcast_package(
        chapters,
        charts,
        assets,
        output_dir=tmp_path / "pkg_nolink",
        video_title="Episodio piloto",
        video_url=None,
    )
    post_nolink = render_social_post(chapters, charts, without_url)
    assert "[LINK_VIDEO]" in post_nolink
    assert "9999" not in post_nolink  # no cifras inventadas


def test_rundown_con_y_sin_excluded_errors() -> None:
    slides = [
        PackageSlide(
            slide_index=0,
            chapter_index=0,
            chapter_title="Apertura",
            cue_index=0,
            timestamp="00:00:00",
            kind="chapter_cover",
            status="chapter_cover",
            title="Apertura",
            relative_html_path="slides/chapters/ch00_cover.html",
        )
    ]
    clean = BroadcastPackageManifest(
        video_title="Limpio",
        publish_date=date(2025, 11, 25),
        chapter_count=1,
        slides=slides,
        excluded_errors=[],
        data_sources=[],
        visual_credits=[],
    )
    clean_md = render_rundown_markdown(clean)
    assert "# Rundown · Limpio" in clean_md
    assert "Slides al aire: **1**" in clean_md
    assert "Errores excluidos: **0**" in clean_md
    assert "Advertencia" not in clean_md
    assert "chapter_cover" in clean_md

    dirty = BroadcastPackageManifest(
        video_title="Con errores",
        publish_date=date(2025, 11, 25),
        chapter_count=1,
        slides=slides,
        excluded_errors=[
            ExcludedErrorRecord(
                chapter_index=0,
                cue_index=9,
                timestamp="00:01:00",
                kind="chart",
                title="Reservas",
                error_message="timeout BCRA",
            )
        ],
        data_sources=[
            DataSourceCredit(
                provider="indec",
                source_tier="official_primary",
                series_id="ipc",
                source_attribution="Fuente: INDEC",
                source_url="https://example.org/ipc",
            )
        ],
        visual_credits=[
            VisualLicenseCredit(
                provider="wikimedia",
                author="Jane Doe",
                license_name="CC BY 4.0",
                license_code="CC-BY",
                source_page_url="https://commons.wikimedia.org/wiki/File:Example.jpg",
            )
        ],
    )
    dirty_md = render_rundown_markdown(dirty)
    assert "Advertencia · placas `fetch_error` excluidas" in dirty_md
    assert "timeout BCRA" in dirty_md
    assert "Reservas" in dirty_md


def test_social_bullets_rellena_con_resumen_y_trunca_a_cuatro(tmp_path: Path) -> None:
    from .conftest import make_metrics, make_series

    chapters = ChapterizedTranscript(
        chapters=[
            make_chapter(
                start_cue=0,
                end_cue=5,
                start_time="00:00:00",
                end_time="00:01:00",
                title="Único",
                summary="Eje resumido del episodio",
            )
        ]
    )
    empty_charts = ChartsPackage(publish_date=date(2025, 11, 25), items=[])
    assets = VisualAssetsPackage(items=[make_visual(tmp_path, filename="only.html")])
    manifest = assemble_broadcast_package(
        chapters,
        empty_charts,
        assets,
        output_dir=tmp_path / "pkg_one",
        video_title="Uno",
    )
    post = render_social_post(chapters, empty_charts, manifest)
    assert "• Único" in post
    assert "• Eje resumido del episodio" in post

    items = []
    for i in range(1, 5):
        series = make_series(series_id=f"s{i}")
        metrics = make_metrics().model_copy(update={"latest_value": float(i)})
        item = make_chart(
            tmp_path,
            cue_index=i,
            timestamp=f"00:00:{i:02d}",
            indicator_label=f"Ind {i}",
            filename=f"m{i}.html",
            series=series,
        )
        items.append(item.model_copy(update={"metrics": metrics}))
    many = ChartsPackage(publish_date=date(2025, 11, 25), items=items)
    chapters2 = make_chapters()
    stub = BroadcastPackageManifest(
        video_title="Muchos",
        publish_date=date(2025, 11, 25),
        chapter_count=2,
        slides=[
            PackageSlide(
                slide_index=0,
                chapter_index=0,
                chapter_title="Apertura e inflación",
                cue_index=0,
                timestamp="00:00:00",
                kind="chapter_cover",
                status="chapter_cover",
                title="Apertura e inflación",
                relative_html_path="slides/chapters/ch00_cover.html",
            )
        ],
        excluded_errors=[],
        data_sources=[],
        visual_credits=[],
    )
    post_many = render_social_post(chapters2, many, stub)
    assert 2 <= post_many.count("• ") <= 4
    assert "último dato oficial 1" in post_many


def test_write_publishing_files(tmp_path: Path) -> None:
    chapters = make_chapters()
    charts = ChartsPackage(publish_date=date(2025, 11, 25), items=[make_chart(tmp_path)])
    assets = VisualAssetsPackage(items=[make_visual(tmp_path)])
    output_dir = tmp_path / "out"
    manifest = assemble_broadcast_package(
        chapters,
        charts,
        assets,
        output_dir=output_dir,
        video_title="Write test",
        video_url="https://youtu.be/x",
    )

    write_publishing_files(chapters, charts, manifest, output_dir)

    assert (output_dir / "rundown.md").is_file()
    assert (output_dir / "youtube_description.txt").is_file()
    assert (output_dir / "social_post.txt").is_file()
    assert "00:00" in (output_dir / "youtube_description.txt").read_text(encoding="utf-8")
    assert "https://youtu.be/x" in (output_dir / "social_post.txt").read_text(encoding="utf-8")
