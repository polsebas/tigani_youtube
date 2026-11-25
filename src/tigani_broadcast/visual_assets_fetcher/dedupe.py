"""Normalización y deduplicación determinista de visual_subjects por capítulo."""

from __future__ import annotations

import re
import unicodedata

from tigani_broadcast.transcript_chapterizer.models import ChapterizedTranscript
from tigani_broadcast.visual_assets_fetcher.models import DeduplicatedVisualSubject

_WHITESPACE = re.compile(r"\s+")


def normalize_subject_label(label: str) -> str:
    """Minúsculas, sin acentos/diacríticos y con espacios internos colapsados."""
    decomposed = unicodedata.normalize("NFKD", label)
    without_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return _WHITESPACE.sub(" ", without_marks.casefold()).strip()


def deduplicate_visual_subjects(
    chapters: ChapterizedTranscript,
) -> list[DeduplicatedVisualSubject]:
    """Agrupa por (chapter_index, label normalizada) conservando la primera aparición."""
    results: list[DeduplicatedVisualSubject] = []
    index_by_key: dict[tuple[int, str], int] = {}

    for chapter_index, chapter in enumerate(chapters.chapters):
        for subject in chapter.visual_subjects:
            normalized = normalize_subject_label(subject.subject_label)
            key = (chapter_index, normalized)
            existing = index_by_key.get(key)
            if existing is None:
                index_by_key[key] = len(results)
                results.append(
                    DeduplicatedVisualSubject(
                        chapter_index=chapter_index,
                        cue_index=subject.cue_index,
                        timestamp=subject.timestamp,
                        subject_label=subject.subject_label,
                        normalized_label=normalized,
                        asset_kind=subject.asset_kind,
                        context_text=subject.context_text,
                        occurrences_count=1,
                    )
                )
                continue

            previous = results[existing]
            results[existing] = previous.model_copy(
                update={"occurrences_count": previous.occurrences_count + 1}
            )

    return results
