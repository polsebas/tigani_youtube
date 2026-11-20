"""Serialización determinista del paquete para los módulos siguientes."""

import json
from pathlib import Path

from tigani_broadcast.transcript_chapterizer.models import (
    ChapterizedTranscript,
    HardDataMention,
    VisualSubjectMention,
)


def render_json(transcript: ChapterizedTranscript) -> str:
    """JSON UTF-8, con indentado fijo y los acentos intactos."""
    payload = transcript.model_dump(mode="json")
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def render_markdown(transcript: ChapterizedTranscript) -> str:
    """Escaleta legible. Cada capítulo conserva el rango y los timestamps de origen."""
    blocks = ["# Capítulos", ""]
    for number, chapter in enumerate(transcript.chapters, start=1):
        blocks.append(f"## {number}. {_single_line(chapter.title)}")
        blocks.append("")
        blocks.append("| Campo | Contenido |")
        blocks.append("| --- | --- |")
        blocks.append(f"| Rango | [{chapter.start_time} - {chapter.end_time}] |")
        blocks.append(f"| Zócalo | {_cell(chapter.suggested_lower_third)} |")
        blocks.append("")
        blocks.append(_single_line(chapter.summary))
        blocks.append("")
        blocks.append("### Datos duros")
        blocks.append("")
        blocks.extend(_mention_lines(chapter.hard_data, _hard_line))
        blocks.append("")
        blocks.append("### Apoyos visuales")
        blocks.append("")
        blocks.extend(_mention_lines(chapter.visual_subjects, _visual_line))
        blocks.append("")
    return "\n".join(blocks).rstrip() + "\n"


def write_json(path: Path, transcript: ChapterizedTranscript) -> None:
    path.write_text(render_json(transcript), encoding="utf-8")


def write_markdown(path: Path, transcript: ChapterizedTranscript) -> None:
    path.write_text(render_markdown(transcript), encoding="utf-8")


def _mention_lines(
    items: list[HardDataMention] | list[VisualSubjectMention],
    line_for,
) -> list[str]:
    if not items:
        return ["Sin menciones."]
    return [line_for(item) for item in items]


def _hard_line(item: HardDataMention) -> str:
    line = (
        f"- [{item.timestamp}] cue {item.cue_index}: {item.indicator_label}: {item.raw_value_text}"
    )
    if item.time_reference:
        line = f"{line} ({item.time_reference})"
    return line


def _visual_line(item: VisualSubjectMention) -> str:
    return (
        f"- [{item.timestamp}] cue {item.cue_index}: {item.asset_kind}: "
        f"{item.subject_label} — {item.context_text}"
    )


def _cell(value: str) -> str:
    return _single_line(value).replace("|", "\\|")


def _single_line(value: str) -> str:
    return " ".join(value.split())
