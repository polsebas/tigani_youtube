"""Ingesta de transcripciones, capítulos validados y segmentación con Agno inyectable."""

from tigani_broadcast.transcript_chapterizer.chapterizer import (
    AgnoChapterizer,
    ChapterizerEngine,
    ChapterizerError,
    ChapterizerInputError,
    ChapterizerOutputError,
    chapterize_transcript,
    format_chapterizer_input,
)
from tigani_broadcast.transcript_chapterizer.cli import (
    ModelConfigError,
    build_agno_model_from_env,
    main,
)
from tigani_broadcast.transcript_chapterizer.models import ChapterizedTranscript, Cue
from tigani_broadcast.transcript_chapterizer.render import render_json, render_markdown
from tigani_broadcast.transcript_chapterizer.validate import (
    ChapterValidationError,
    validate_chapterized_transcript,
)

__all__ = [
    "AgnoChapterizer",
    "ChapterValidationError",
    "ChapterizedTranscript",
    "ChapterizerEngine",
    "ChapterizerError",
    "ChapterizerInputError",
    "ChapterizerOutputError",
    "Cue",
    "ModelConfigError",
    "build_agno_model_from_env",
    "chapterize_transcript",
    "format_chapterizer_input",
    "main",
    "render_json",
    "render_markdown",
    "validate_chapterized_transcript",
]
