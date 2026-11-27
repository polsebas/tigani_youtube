"""Validación fail-closed, créditos deduplicados y ensamblado portable del paquete OBS."""

from __future__ import annotations

import shutil
from pathlib import Path

from tigani_broadcast.broadcast_package_builder.models import (
    BroadcastPackageManifest,
    DataSourceCredit,
    ExcludedErrorRecord,
    PackageSlide,
    SlideKind,
    VisualLicenseCredit,
)
from tigani_broadcast.official_data_charts.models import ChartsPackage
from tigani_broadcast.transcript_chapterizer.models import ChapterizedTranscript
from tigani_broadcast.visual_assets_fetcher.models import VisualAssetsPackage

KIND_PRIORITY: dict[SlideKind, int] = {
    "chapter_cover": 0,
    "chart": 1,
    "visual": 2,
}


class PackageValidationError(ValueError):
    """Entradas del paquete inconsistentes o archivos faltantes en disco."""


def validate_package_inputs(
    chapters: ChapterizedTranscript,
    charts: ChartsPackage,
    assets: VisualAssetsPackage,
) -> None:
    """Valida índices de capítulo y existencia física de HTML/imágenes. Fail-closed."""
    chapter_count = len(chapters.chapters)
    if chapter_count < 1:
        raise PackageValidationError("chapters.json tiene que tener al menos un capítulo")

    for item in charts.items:
        _assert_chapter_index(item.chapter_index, chapter_count, origin="charts")
        _assert_html_path(item.html_path, origin="charts", label=item.indicator_label)

    for item in assets.items:
        _assert_chapter_index(item.chapter_index, chapter_count, origin="assets")
        _assert_html_path(item.html_path, origin="assets", label=item.subject_label)
        if item.status == "verified_asset":
            if item.local_image_path is None or item.local_image_path.strip() == "":
                raise PackageValidationError(
                    "verified_asset exige local_image_path poblado: "
                    f"capítulo {item.chapter_index} cue {item.cue_index} ({item.subject_label})"
                )
            image_path = Path(item.local_image_path)
            if not image_path.is_file():
                raise PackageValidationError(
                    "falta la imagen local de verified_asset: "
                    f"{item.local_image_path} "
                    f"(capítulo {item.chapter_index} cue {item.cue_index}, {item.subject_label})"
                )


def collect_data_sources(charts: ChartsPackage) -> list[DataSourceCredit]:
    """Créditos de series verificadas, deduplicados preservando orden de aparición."""
    credits: list[DataSourceCredit] = []
    seen: set[tuple[str, str, str]] = set()
    for item in charts.items:
        if item.resolution_status != "verified_series" or item.series is None:
            continue
        series = item.series
        key = (series.provider, series.series_id, series.source_url)
        if key in seen:
            continue
        seen.add(key)
        credits.append(
            DataSourceCredit(
                provider=series.provider,
                source_tier=series.source_tier,
                series_id=series.series_id,
                source_attribution=series.source_attribution,
                source_url=series.source_url,
            )
        )
    return credits


def collect_visual_credits(assets: VisualAssetsPackage) -> list[VisualLicenseCredit]:
    """Créditos CC de imágenes verificadas, deduplicados preservando orden de aparición."""
    credits: list[VisualLicenseCredit] = []
    seen: set[tuple[str, str, str]] = set()
    for item in assets.items:
        if item.status != "verified_asset" or item.attribution is None:
            continue
        attr = item.attribution
        key = (attr.provider, attr.source_page_url, attr.license_code)
        if key in seen:
            continue
        seen.add(key)
        credits.append(
            VisualLicenseCredit(
                provider=attr.provider,
                author=attr.author,
                license_name=attr.license_name,
                license_code=attr.license_code,
                license_url=attr.license_url,
                source_page_url=attr.source_page_url,
            )
        )
    return credits


def assemble_broadcast_package(
    chapters: ChapterizedTranscript,
    charts: ChartsPackage,
    assets: VisualAssetsPackage,
    *,
    output_dir: Path,
    video_title: str,
    video_url: str | None = None,
    include_chapter_covers: bool = True,
    include_errors: bool = False,
) -> BroadcastPackageManifest:
    """Valida entradas, copia activos portables y construye el manifiesto ordenado."""
    validate_package_inputs(chapters, charts, assets)

    output_dir = Path(output_dir)
    charts_dir = output_dir / "slides" / "charts"
    visuals_dir = output_dir / "slides" / "visuals"
    images_dir = visuals_dir / "images"
    chapters_dir = output_dir / "slides" / "chapters"

    charts_dir.mkdir(parents=True, exist_ok=True)
    visuals_dir.mkdir(parents=True, exist_ok=True)
    images_dir.mkdir(parents=True, exist_ok=True)
    if include_chapter_covers:
        chapters_dir.mkdir(parents=True, exist_ok=True)

    draft_slides: list[tuple[int, int, int, int, PackageSlide]] = []
    excluded_errors: list[ExcludedErrorRecord] = []
    original_index = 0

    if include_chapter_covers:
        for chapter_index, chapter in enumerate(chapters.chapters):
            relative = f"slides/chapters/ch{chapter_index:02d}_cover.html"
            slide = PackageSlide(
                slide_index=0,
                chapter_index=chapter_index,
                chapter_title=chapter.title,
                cue_index=chapter.start_cue_index,
                timestamp=chapter.start_time,
                kind="chapter_cover",
                status="chapter_cover",
                title=chapter.title,
                relative_html_path=relative,
                source_ref=None,
            )
            draft_slides.append(
                (
                    chapter_index,
                    chapter.start_cue_index,
                    KIND_PRIORITY["chapter_cover"],
                    original_index,
                    slide,
                )
            )
            original_index += 1

    echarts_copied = False
    for item in charts.items:
        if item.resolution_status == "fetch_error" and not include_errors:
            excluded_errors.append(
                ExcludedErrorRecord(
                    chapter_index=item.chapter_index,
                    cue_index=item.cue_index,
                    timestamp=item.timestamp,
                    kind="chart",
                    title=item.indicator_label,
                    error_message=item.error_message or "fetch_error",
                )
            )
            continue

        assert item.html_path is not None
        filename = Path(item.html_path).name
        dest = charts_dir / filename
        shutil.copy2(item.html_path, dest)
        if not echarts_copied:
            sibling = Path(item.html_path).parent / "echarts.min.js"
            if sibling.is_file():
                shutil.copy2(sibling, charts_dir / "echarts.min.js")
                echarts_copied = True
        relative = f"slides/charts/{filename}"
        chapter_title = chapters.chapters[item.chapter_index].title
        source_ref = None
        if item.series is not None:
            source_ref = item.series.series_id
        slide = PackageSlide(
            slide_index=0,
            chapter_index=item.chapter_index,
            chapter_title=chapter_title,
            cue_index=item.cue_index,
            timestamp=item.timestamp,
            kind="chart",
            status=item.resolution_status,
            title=item.indicator_label,
            relative_html_path=relative,
            source_ref=source_ref,
        )
        draft_slides.append(
            (
                item.chapter_index,
                item.cue_index,
                KIND_PRIORITY["chart"],
                original_index,
                slide,
            )
        )
        original_index += 1

    for item in assets.items:
        if item.status == "fetch_error" and not include_errors:
            excluded_errors.append(
                ExcludedErrorRecord(
                    chapter_index=item.chapter_index,
                    cue_index=item.cue_index,
                    timestamp=item.timestamp,
                    kind="visual",
                    title=item.subject_label,
                    error_message=item.error_message or "fetch_error",
                )
            )
            continue

        assert item.html_path is not None
        filename = Path(item.html_path).name
        dest = visuals_dir / filename
        shutil.copy2(item.html_path, dest)

        if item.status == "verified_asset" and item.local_image_path is not None:
            image_name = Path(item.local_image_path).name
            shutil.copy2(item.local_image_path, images_dir / image_name)

        relative = f"slides/visuals/{filename}"
        chapter_title = chapters.chapters[item.chapter_index].title
        source_ref = None
        if item.attribution is not None:
            source_ref = item.attribution.source_page_url
        slide = PackageSlide(
            slide_index=0,
            chapter_index=item.chapter_index,
            chapter_title=chapter_title,
            cue_index=item.cue_index,
            timestamp=item.timestamp,
            kind="visual",
            status=item.status,
            title=item.subject_label,
            relative_html_path=relative,
            source_ref=source_ref,
        )
        draft_slides.append(
            (
                item.chapter_index,
                item.cue_index,
                KIND_PRIORITY["visual"],
                original_index,
                slide,
            )
        )
        original_index += 1

    draft_slides.sort(key=lambda row: (row[0], row[1], row[2], row[3]))
    slides = [
        row[4].model_copy(update={"slide_index": index}) for index, row in enumerate(draft_slides)
    ]

    return BroadcastPackageManifest(
        video_title=video_title,
        video_url=video_url,
        publish_date=charts.publish_date,
        include_chapter_covers=include_chapter_covers,
        include_errors=include_errors,
        chapter_count=len(chapters.chapters),
        slides=slides,
        excluded_errors=excluded_errors,
        data_sources=collect_data_sources(charts),
        visual_credits=collect_visual_credits(assets),
    )


def _assert_chapter_index(chapter_index: int, chapter_count: int, *, origin: str) -> None:
    if chapter_index < 0 or chapter_index >= chapter_count:
        raise PackageValidationError(
            f"{origin}: chapter_index={chapter_index} no existe en chapters.json "
            f"(válidos: 0..{chapter_count - 1})"
        )


def _assert_html_path(html_path: str | None, *, origin: str, label: str) -> None:
    if html_path is None or html_path.strip() == "":
        raise PackageValidationError(f"{origin}: html_path vacío para {label!r}")
    path = Path(html_path)
    if not path.is_file():
        raise PackageValidationError(
            f"{origin}: falta el HTML en disco para {label!r}: {html_path}"
        )


__all__ = [
    "KIND_PRIORITY",
    "PackageValidationError",
    "assemble_broadcast_package",
    "collect_data_sources",
    "collect_visual_credits",
    "validate_package_inputs",
]
