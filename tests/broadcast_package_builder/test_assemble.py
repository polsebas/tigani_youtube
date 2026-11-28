"""Ensamblado portable: ordenamiento, copia, créditos y validación fail-closed."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from tigani_broadcast.broadcast_package_builder.assemble import (
    PackageValidationError,
    assemble_broadcast_package,
    collect_data_sources,
    collect_visual_credits,
    validate_package_inputs,
)
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


def _chapter(
    *,
    start_cue: int,
    end_cue: int,
    start_time: str,
    end_time: str,
    title: str,
) -> Chapter:
    return Chapter(
        start_cue_index=start_cue,
        end_cue_index=end_cue,
        start_time=start_time,
        end_time=end_time,
        title=title,
        summary=f"Resumen de {title}",
        suggested_lower_third=title[:40],
    )


def _chapters() -> ChapterizedTranscript:
    return ChapterizedTranscript(
        chapters=[
            _chapter(
                start_cue=0,
                end_cue=20,
                start_time="00:00:00",
                end_time="00:03:00",
                title="Apertura e inflación",
            ),
            _chapter(
                start_cue=21,
                end_cue=40,
                start_time="00:03:01",
                end_time="00:05:00",
                title="Reservas y deuda",
            ),
        ]
    )


def _series(*, series_id: str = "ipc", provider: ProviderId = "indec") -> SeriesData:
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


def _metrics() -> SeriesMetrics:
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


def _write(path: Path, content: str = "<html></html>") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _write_bytes(path: Path, content: bytes = b"fake-image") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _chart(
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
) -> ChartArtifact:
    html_path = _write(tmp_path / "charts_src" / filename, f"<html>{indicator_label}</html>")
    payload: dict[str, object] = {
        "chapter_index": chapter_index,
        "cue_index": cue_index,
        "timestamp": timestamp,
        "indicator_label": indicator_label,
        "raw_value_text": "2,5%",
        "time_reference": "febrero",
        "resolution_status": resolution_status,
        "rationale": "Mención verificable en catálogo",
        "html_path": str(html_path),
    }
    if resolution_status == "verified_series":
        payload["series"] = series or _series()
        payload["metrics"] = _metrics()
    elif resolution_status == "fetch_error":
        payload["error_message"] = error_message or "API timeout"
    return ChartArtifact.model_validate(payload)


def _visual(
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
    html_path = _write(
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
        image_path = _write_bytes(tmp_path / "assets_src" / "images" / image_name)
        payload["attribution"] = attribution or _attribution()
        payload["local_image_path"] = str(image_path)
    elif status == "fetch_error":
        payload["error_message"] = error_message or "sin candidatos seguros"
    return VisualAssetArtifact.model_validate(payload)


def test_ordenamiento_colision_cue_14_chapter_cover_chart_visual(tmp_path: Path) -> None:
    chapters = _chapters()
    charts = ChartsPackage(publish_date=date(2025, 11, 25), items=[_chart(tmp_path)])
    assets = VisualAssetsPackage(items=[_visual(tmp_path)])

    manifest = assemble_broadcast_package(
        chapters,
        charts,
        assets,
        output_dir=tmp_path / "package",
        video_title="Piloto",
    )

    kinds_at_cue_14 = [
        slide.kind
        for slide in manifest.slides
        if slide.chapter_index == 0 and slide.cue_index == 14
    ]
    # chapter_cover del capítulo 0 también usa cue_index=0; en cue 14 solo chart+visual
    assert kinds_at_cue_14 == ["chart", "visual"]

    # Colisión exacta en cue 0 (inicio de capítulo): cover → chart → visual
    chart_at_0 = _chart(
        tmp_path,
        cue_index=0,
        timestamp="00:00:00",
        filename="ch00_cue000_chart.html",
        indicator_label="CER",
        series=_series(series_id="cer"),
    )
    visual_at_0 = _visual(
        tmp_path,
        cue_index=0,
        timestamp="00:00:00",
        filename="ch00_cue000_visual.html",
        image_name="cer.jpg",
        subject_label="banco central",
        attribution=_attribution(
            source_page_url="https://commons.wikimedia.org/wiki/File:BCRA.jpg",
        ),
    )
    collision = assemble_broadcast_package(
        chapters,
        ChartsPackage(publish_date=date(2025, 11, 25), items=[chart_at_0]),
        VisualAssetsPackage(items=[visual_at_0]),
        output_dir=tmp_path / "package_collision",
        video_title="Piloto",
    )
    first_three = [s.kind for s in collision.slides[:3]]
    assert first_three == ["chapter_cover", "chart", "visual"]
    assert [s.slide_index for s in collision.slides] == list(range(len(collision.slides)))


def test_copia_portable_html_e_imagenes(tmp_path: Path) -> None:
    chapters = _chapters()
    charts = ChartsPackage(publish_date=date(2025, 11, 25), items=[_chart(tmp_path)])
    assets = VisualAssetsPackage(items=[_visual(tmp_path)])
    output_dir = tmp_path / "package"

    manifest = assemble_broadcast_package(
        chapters,
        charts,
        assets,
        output_dir=output_dir,
        video_title="Piloto",
        video_url="https://youtu.be/abc",
    )

    chart_dest = output_dir / "slides" / "charts" / "ch00_cue014_00.html"
    visual_dest = output_dir / "slides" / "visuals" / "ch00_cue014_00.html"
    image_dest = output_dir / "slides" / "visuals" / "images" / "gobierno.jpg"

    assert chart_dest.is_file()
    assert visual_dest.is_file()
    assert image_dest.is_file()
    assert image_dest.read_bytes() == b"fake-image"
    assert "images/gobierno.jpg" in visual_dest.read_text(encoding="utf-8")

    chart_slide = next(s for s in manifest.slides if s.kind == "chart")
    visual_slide = next(s for s in manifest.slides if s.kind == "visual")
    assert chart_slide.relative_html_path == "slides/charts/ch00_cue014_00.html"
    assert visual_slide.relative_html_path == "slides/visuals/ch00_cue014_00.html"
    assert (output_dir / "slides" / "chapters").is_dir()
    assert any(s.kind == "chapter_cover" for s in manifest.slides)
    assert manifest.video_url == "https://youtu.be/abc"


def test_copia_echarts_min_js_a_slides_charts(tmp_path: Path) -> None:
    chapters = _chapters()
    chart = _chart(tmp_path)
    assert chart.html_path is not None
    # Simula el runtime offline escrito por write_charts_package junto a las placas.
    echarts_src = Path(chart.html_path).parent / "echarts.min.js"
    echarts_src.write_text("/* apache echarts stub */", encoding="utf-8")
    output_dir = tmp_path / "package"

    assemble_broadcast_package(
        chapters,
        ChartsPackage(publish_date=date(2025, 11, 25), items=[chart]),
        VisualAssetsPackage(items=[_visual(tmp_path)]),
        output_dir=output_dir,
        video_title="Piloto",
    )

    dest = output_dir / "slides" / "charts" / "echarts.min.js"
    assert dest.is_file()
    assert dest.read_text(encoding="utf-8") == "/* apache echarts stub */"


def test_excluye_fetch_error_por_defecto(tmp_path: Path) -> None:
    chapters = _chapters()
    charts = ChartsPackage(
        publish_date=date(2025, 11, 25),
        items=[
            _chart(tmp_path),
            _chart(
                tmp_path,
                cue_index=15,
                timestamp="00:02:00",
                indicator_label="Reservas",
                resolution_status="fetch_error",
                filename="ch00_cue015_err.html",
                error_message="BCRA 503",
            ),
        ],
    )
    assets = VisualAssetsPackage(
        items=[
            _visual(tmp_path),
            _visual(
                tmp_path,
                cue_index=16,
                timestamp="00:02:10",
                subject_label="mercado",
                status="fetch_error",
                filename="ch00_cue016_err.html",
                error_message="sin licencia segura",
            ),
        ]
    )

    manifest = assemble_broadcast_package(
        chapters,
        charts,
        assets,
        output_dir=tmp_path / "package",
        video_title="Piloto",
    )

    assert all(s.status != "fetch_error" for s in manifest.slides)
    assert len(manifest.excluded_errors) == 2
    assert {e.kind for e in manifest.excluded_errors} == {"chart", "visual"}
    assert not (tmp_path / "package" / "slides" / "charts" / "ch00_cue015_err.html").exists()
    assert not (tmp_path / "package" / "slides" / "visuals" / "ch00_cue016_err.html").exists()


def test_include_errors_true_incluye_fetch_error(tmp_path: Path) -> None:
    chapters = _chapters()
    charts = ChartsPackage(
        publish_date=date(2025, 11, 25),
        items=[
            _chart(
                tmp_path,
                cue_index=15,
                timestamp="00:02:00",
                indicator_label="Reservas",
                resolution_status="fetch_error",
                filename="ch00_cue015_err.html",
            ),
        ],
    )
    assets = VisualAssetsPackage(
        items=[
            _visual(
                tmp_path,
                cue_index=16,
                timestamp="00:02:10",
                subject_label="mercado",
                status="fetch_error",
                filename="ch00_cue016_err.html",
            ),
        ]
    )

    manifest = assemble_broadcast_package(
        chapters,
        charts,
        assets,
        output_dir=tmp_path / "package",
        video_title="Piloto",
        include_errors=True,
    )

    assert manifest.include_errors is True
    assert manifest.excluded_errors == []
    statuses = {s.status for s in manifest.slides}
    assert "fetch_error" in statuses
    assert (tmp_path / "package" / "slides" / "charts" / "ch00_cue015_err.html").is_file()
    assert (tmp_path / "package" / "slides" / "visuals" / "ch00_cue016_err.html").is_file()


def test_include_chapter_covers_false(tmp_path: Path) -> None:
    chapters = _chapters()
    charts = ChartsPackage(publish_date=date(2025, 11, 25), items=[_chart(tmp_path)])
    assets = VisualAssetsPackage(items=[_visual(tmp_path)])

    manifest = assemble_broadcast_package(
        chapters,
        charts,
        assets,
        output_dir=tmp_path / "package",
        video_title="Piloto",
        include_chapter_covers=False,
    )

    assert manifest.include_chapter_covers is False
    assert all(s.kind != "chapter_cover" for s in manifest.slides)
    assert not (tmp_path / "package" / "slides" / "chapters").exists()


def test_deduplicacion_data_sources_y_visual_credits(tmp_path: Path) -> None:
    series = _series(series_id="ipc")
    charts = ChartsPackage(
        publish_date=date(2025, 11, 25),
        items=[
            _chart(tmp_path, series=series, filename="a.html"),
            _chart(
                tmp_path,
                cue_index=15,
                timestamp="00:02:00",
                indicator_label="IPC repetido",
                series=series,
                filename="b.html",
            ),
            _chart(
                tmp_path,
                cue_index=16,
                timestamp="00:02:10",
                indicator_label="CER",
                series=_series(series_id="cer"),
                filename="c.html",
            ),
        ],
    )
    attr = _attribution()
    assets = VisualAssetsPackage(
        items=[
            _visual(tmp_path, attribution=attr, filename="v1.html", image_name="a.jpg"),
            _visual(
                tmp_path,
                cue_index=15,
                timestamp="00:02:00",
                subject_label="gobierno bis",
                attribution=attr,
                filename="v2.html",
                image_name="b.jpg",
            ),
            _visual(
                tmp_path,
                cue_index=16,
                timestamp="00:02:10",
                subject_label="mercado",
                attribution=_attribution(
                    source_page_url="https://commons.wikimedia.org/wiki/File:Other.jpg",
                    author="Other",
                ),
                filename="v3.html",
                image_name="c.jpg",
            ),
        ]
    )

    data_sources = collect_data_sources(charts)
    visual_credits = collect_visual_credits(assets)

    assert [c.series_id for c in data_sources] == ["ipc", "cer"]
    assert len(visual_credits) == 2
    assert visual_credits[0].author == "Jane Doe"
    assert visual_credits[1].author == "Other"


def test_validate_rechaza_chapter_index_inexistente(tmp_path: Path) -> None:
    chapters = _chapters()
    charts = ChartsPackage(
        publish_date=date(2025, 11, 25),
        items=[_chart(tmp_path, chapter_index=9, filename="bad_ch.html")],
    )
    assets = VisualAssetsPackage(items=[])

    with pytest.raises(PackageValidationError, match="chapter_index=9 no existe"):
        validate_package_inputs(chapters, charts, assets)


def test_validate_rechaza_html_faltante(tmp_path: Path) -> None:
    chapters = _chapters()
    item = _chart(tmp_path)
    Path(item.html_path).unlink()
    charts = ChartsPackage(publish_date=date(2025, 11, 25), items=[item])
    assets = VisualAssetsPackage(items=[])

    with pytest.raises(PackageValidationError, match="falta el HTML"):
        validate_package_inputs(chapters, charts, assets)


def test_validate_rechaza_imagen_local_faltante(tmp_path: Path) -> None:
    chapters = _chapters()
    charts = ChartsPackage(publish_date=date(2025, 11, 25), items=[])
    item = _visual(tmp_path)
    Path(item.local_image_path).unlink()
    assets = VisualAssetsPackage(items=[item])

    with pytest.raises(PackageValidationError, match="falta la imagen local"):
        validate_package_inputs(chapters, charts, assets)


def test_validate_rechaza_html_path_vacio(tmp_path: Path) -> None:
    chapters = _chapters()
    item = ChartArtifact(
        chapter_index=0,
        cue_index=1,
        timestamp="00:00:10",
        indicator_label="IPC",
        raw_value_text="2%",
        resolution_status="quoted_only",
        rationale="Solo cita textual",
        html_path=None,
    )
    charts = ChartsPackage(publish_date=date(2025, 11, 25), items=[item])
    assets = VisualAssetsPackage(items=[])

    with pytest.raises(PackageValidationError, match="html_path vacío"):
        validate_package_inputs(chapters, charts, assets)


def test_validate_rechaza_chapters_vacios(tmp_path: Path) -> None:
    chapters = ChapterizedTranscript.model_construct(chapters=[])
    charts = ChartsPackage(publish_date=date(2025, 11, 25), items=[])
    assets = VisualAssetsPackage(items=[])

    with pytest.raises(PackageValidationError, match="al menos un capítulo"):
        validate_package_inputs(chapters, charts, assets)


def test_validate_rechaza_verified_asset_sin_local_image_path(tmp_path: Path) -> None:
    chapters = _chapters()
    html_path = _write(tmp_path / "assets_src" / "orphan.html")
    item = VisualAssetArtifact.model_construct(
        chapter_index=0,
        cue_index=1,
        timestamp="00:00:10",
        subject_label="gobierno",
        asset_kind="event_photo",
        context_text="contexto",
        occurrences_count=1,
        search_query="gobierno",
        status="verified_asset",
        portrait_layout="sidebar",
        attribution=_attribution(),
        local_image_path="   ",
        html_path=str(html_path),
        error_message=None,
    )
    charts = ChartsPackage(publish_date=date(2025, 11, 25), items=[])
    assets = VisualAssetsPackage.model_construct(
        source_chapters_path=None,
        portrait_layout="sidebar",
        items=[item],
    )

    with pytest.raises(PackageValidationError, match="exige local_image_path poblado"):
        validate_package_inputs(chapters, charts, assets)


def test_validate_rechaza_chapter_index_en_assets(tmp_path: Path) -> None:
    chapters = _chapters()
    charts = ChartsPackage(publish_date=date(2025, 11, 25), items=[])
    assets = VisualAssetsPackage(
        items=[_visual(tmp_path, chapter_index=8, filename="bad_asset.html")]
    )

    with pytest.raises(PackageValidationError, match="chapter_index=8 no existe"):
        validate_package_inputs(chapters, charts, assets)


def test_assemble_propaga_validation_error(tmp_path: Path) -> None:
    chapters = _chapters()
    charts = ChartsPackage(
        publish_date=date(2025, 11, 25),
        items=[_chart(tmp_path, chapter_index=5, filename="ghost.html")],
    )
    assets = VisualAssetsPackage(items=[])

    with pytest.raises(PackageValidationError, match="chapter_index=5"):
        assemble_broadcast_package(
            chapters,
            charts,
            assets,
            output_dir=tmp_path / "package",
            video_title="Piloto",
        )


def test_fallback_card_se_copia_sin_imagen(tmp_path: Path) -> None:
    chapters = _chapters()
    charts = ChartsPackage(publish_date=date(2025, 11, 25), items=[])
    assets = VisualAssetsPackage(
        items=[
            _visual(
                tmp_path,
                status="fallback_card",
                filename="fallback.html",
                subject_label="concepto",
            )
        ]
    )

    manifest = assemble_broadcast_package(
        chapters,
        charts,
        assets,
        output_dir=tmp_path / "package",
        video_title="Piloto",
    )

    assert any(s.status == "fallback_card" for s in manifest.slides)
    assert (tmp_path / "package" / "slides" / "visuals" / "fallback.html").is_file()
    assert list((tmp_path / "package" / "slides" / "visuals" / "images").iterdir()) == []


def _promo_inputs() -> tuple[ChapterizedTranscript, ChartsPackage, VisualAssetsPackage]:
    chapters = ChapterizedTranscript(
        chapters=[
            Chapter(
                start_cue_index=0,
                end_cue_index=2,
                start_time="00:11:15",
                end_time="00:12:32",
                title="Cierre",
                summary="Invitación a la comunidad.",
                suggested_lower_third="Sumate",
                chapter_kind="promo_outro",
            )
        ]
    )
    charts = ChartsPackage(publish_date=date(2026, 11, 28), items=[])
    assets = VisualAssetsPackage(items=[])
    return chapters, charts, assets


def test_placa_de_cierre_sin_imagen(tmp_path: Path) -> None:
    chapters, charts, assets = _promo_inputs()
    manifest = assemble_broadcast_package(
        chapters,
        charts,
        assets,
        output_dir=tmp_path / "package",
        video_title="Caputo",
    )
    html_path = tmp_path / "package" / "slides" / "chapters" / "ch00_outro.html"
    html = html_path.read_text(encoding="utf-8")
    assert html_path.is_file()
    assert "Sumate a la comunidad · Nivel 1 y Nivel 2" in html
    assert "min-width: 960px" in html
    assert "max-width: 1920px" not in html
    assert "00:11:15" in html
    assert any(slide.kind == "promo_outro" for slide in manifest.slides)


def test_placa_de_cierre_con_imagen(tmp_path: Path) -> None:
    image = tmp_path / "outro.png"
    image.write_bytes(b"\x89PNG\r\n")
    chapters, charts, assets = _promo_inputs()
    manifest = assemble_broadcast_package(
        chapters,
        charts,
        assets,
        output_dir=tmp_path / "package",
        video_title="Caputo",
        outro_image=image,
    )
    html = (tmp_path / "package" / "slides" / "chapters" / "ch00_outro.html").read_text(
        encoding="utf-8"
    )
    assert 'src="../outro.png"' in html
    assert "object-fit: contain" in html
    assert (tmp_path / "package" / "slides" / "outro.png").is_file()
    assert manifest.slides[-1].kind == "promo_outro"
