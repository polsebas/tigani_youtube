"""Kit de publicación YouTube/redes y escaleta operativa `rundown.md`."""

from __future__ import annotations

from pathlib import Path

from tigani_broadcast.broadcast_package_builder.models import BroadcastPackageManifest
from tigani_broadcast.official_data_charts.models import ChartsPackage
from tigani_broadcast.transcript_chapterizer.models import ChapterizedTranscript


def render_youtube_description(
    chapters: ChapterizedTranscript,
    manifest: BroadcastPackageManifest,
) -> str:
    """Descripción lista para YouTube: resumen, capítulos, fuentes y créditos CC."""
    lines: list[str] = [
        manifest.video_title,
        "",
        f"Fecha de publicación: {manifest.publish_date.isoformat()}",
        "",
    ]

    if chapters.chapters:
        summaries = " · ".join(chapter.title for chapter in chapters.chapters)
        lines.extend([summaries, ""])

    lines.append("Capítulos")
    for index, chapter in enumerate(chapters.chapters):
        stamp = _youtube_chapter_timestamp(chapter.start_time, force_zero=(index == 0))
        lines.append(f"{stamp} {chapter.title}")
    lines.append("")

    if manifest.data_sources:
        lines.append("Fuentes de datos")
        for credit in manifest.data_sources:
            lines.append(
                f"- {credit.source_attribution} · series_id={credit.series_id} · "
                f"{credit.source_url}"
            )
        lines.append("")

    if manifest.visual_credits:
        lines.append("Créditos y licencias de imágenes")
        for credit in manifest.visual_credits:
            lines.append(
                f"- {credit.author} · {credit.license_name} · {credit.provider} · "
                f"{credit.source_page_url}"
            )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def render_social_post(
    chapters: ChapterizedTranscript,
    charts: ChartsPackage,
    manifest: BroadcastPackageManifest,
) -> str:
    """Post promocional determinista sin inventar cifras."""
    link = manifest.video_url if manifest.video_url else "[LINK_VIDEO]"
    lines: list[str] = [
        f"{manifest.video_title}",
        "",
        "En este análisis repasamos:",
    ]

    bullets = _social_bullets(chapters, charts)
    lines.extend(bullets)
    lines.extend(
        [
            "",
            f"Mirá el video completo: {link}",
            "",
            "#Economía #Argentina #AnálisisEconómico",
            "",
        ]
    )
    return "\n".join(lines)


def render_rundown_markdown(manifest: BroadcastPackageManifest) -> str:
    """Escaleta operativa Markdown con slides y advertencias de errores excluidos."""
    lines: list[str] = [
        f"# Rundown · {manifest.video_title}",
        "",
        f"- Fecha: `{manifest.publish_date.isoformat()}`",
        f"- Capítulos: **{manifest.chapter_count}**",
        f"- Slides al aire: **{len(manifest.slides)}**",
        f"- Errores excluidos: **{len(manifest.excluded_errors)}**",
        f"- Portadas de capítulo: **{'sí' if manifest.include_chapter_covers else 'no'}**",
        f"- Incluye fetch_error: **{'sí' if manifest.include_errors else 'no'}**",
        "",
        "## Línea de tiempo",
        "",
        "| # | Cap | Timestamp | Tipo | Estado | Título | Ruta relativa |",
        "|---|-----|-----------|------|--------|--------|---------------|",
    ]
    for slide in manifest.slides:
        lines.append(
            "| "
            f"{slide.slide_index} | "
            f"{slide.chapter_index} | "
            f"{slide.timestamp} | "
            f"{slide.kind} | "
            f"{_cell(slide.status)} | "
            f"{_cell(slide.title)} | "
            f"`{_cell(slide.relative_html_path)}` |"
        )

    if manifest.excluded_errors:
        lines.extend(
            [
                "",
                "## Advertencia · placas `fetch_error` excluidas",
                "",
                "| Cap | Cue | Timestamp | Tipo | Título | Error |",
                "|-----|-----|-----------|------|--------|-------|",
            ]
        )
        for error in manifest.excluded_errors:
            lines.append(
                "| "
                f"{error.chapter_index} | "
                f"{error.cue_index} | "
                f"{error.timestamp} | "
                f"{error.kind} | "
                f"{_cell(error.title)} | "
                f"{_cell(error.error_message)} |"
            )

    lines.append("")
    return "\n".join(lines)


def write_publishing_files(
    chapters: ChapterizedTranscript,
    charts: ChartsPackage,
    manifest: BroadcastPackageManifest,
    output_dir: Path,
) -> None:
    """Escribe `rundown.md`, `youtube_description.txt` y `social_post.txt`."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "rundown.md").write_text(render_rundown_markdown(manifest), encoding="utf-8")
    (output_dir / "youtube_description.txt").write_text(
        render_youtube_description(chapters, manifest),
        encoding="utf-8",
    )
    (output_dir / "social_post.txt").write_text(
        render_social_post(chapters, charts, manifest),
        encoding="utf-8",
    )


def _youtube_chapter_timestamp(timestamp: str, *, force_zero: bool) -> str:
    if force_zero:
        return "00:00"
    hours, minutes, seconds = (int(part) for part in timestamp.split(":"))
    total = hours * 3600 + minutes * 60 + seconds
    if total >= 3600:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def _social_bullets(chapters: ChapterizedTranscript, charts: ChartsPackage) -> list[str]:
    bullets: list[str] = []
    for chapter in chapters.chapters[:2]:
        bullets.append(f"• {chapter.title}")

    verified: list[str] = []
    quoted: list[str] = []
    for item in charts.items:
        if item.resolution_status == "verified_series" and item.metrics is not None:
            latest = _format_number(item.metrics.latest_value)
            unit = item.series.unit if item.series is not None else ""
            unit_bit = f" {unit}" if unit else ""
            verified.append(f"• {item.indicator_label}: último dato oficial {latest}{unit_bit}")
        elif item.resolution_status == "quoted_only":
            quoted.append(
                f"• {item.indicator_label}: «{item.raw_value_text}» (citado en exposición)"
            )

    for candidate in [*verified, *quoted]:
        if len(bullets) >= 4:
            break
        if candidate not in bullets:
            bullets.append(candidate)

    if len(bullets) < 2:
        for chapter in chapters.chapters:
            summary_bullet = f"• {chapter.summary}"
            if summary_bullet not in bullets:
                bullets.append(summary_bullet)
            if len(bullets) >= 2:
                break

    return bullets[:4]


def _format_number(value: float) -> str:
    if abs(value - round(value)) < 1e-9:
        return f"{value:.0f}"
    return f"{value:.4g}"


def _cell(value: str) -> str:
    return " ".join(value.split()).replace("|", "\\|")
