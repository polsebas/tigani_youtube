"""Deduplicación determinista por (chapter_index, label normalizada)."""

from typing import Literal

from tigani_broadcast.transcript_chapterizer.models import (
    Chapter,
    ChapterizedTranscript,
    VisualSubjectMention,
)
from tigani_broadcast.visual_assets_fetcher.dedupe import (
    deduplicate_visual_subjects,
    normalize_subject_label,
)

AssetKind = Literal["event_photo", "conceptual_illustration"]


def test_normalize_subject_label_minúsculas_sin_acentos_y_espacios() -> None:
    assert normalize_subject_label("  Gobierno  ") == "gobierno"
    assert normalize_subject_label("Ámbito Financiero") == "ambito financiero"
    assert normalize_subject_label("CRISTINA\tKIRCHNER") == "cristina kirchner"
    assert normalize_subject_label("  a   b  ") == "a b"


def _subject(
    cue_index: int,
    label: str,
    *,
    timestamp: str | None = None,
    asset_kind: AssetKind = "event_photo",
    context_text: str | None = None,
) -> VisualSubjectMention:
    return VisualSubjectMention(
        cue_index=cue_index,
        timestamp=timestamp or f"00:00:{cue_index:02d}",
        subject_label=label,
        asset_kind=asset_kind,
        context_text=context_text or f"contexto de {label}",
    )


def _chapter(
    start: int,
    end: int,
    subjects: list[VisualSubjectMention],
    *,
    title: str = "Capítulo",
) -> Chapter:
    return Chapter(
        start_cue_index=start,
        end_cue_index=end,
        start_time=f"00:00:{start:02d}",
        end_time=f"00:00:{end:02d}",
        title=title,
        summary="Resumen del capítulo.",
        suggested_lower_third="Zócalo de prueba",
        visual_subjects=subjects,
    )


def test_dedupe_colapsa_cinco_gobiernos_en_mismo_capitulo() -> None:
    subjects = [
        _subject(10, "gobierno", timestamp="00:01:10", context_text="primera"),
        _subject(11, "Gobierno", timestamp="00:01:20", context_text="segunda"),
        _subject(12, "  gobierno  ", timestamp="00:01:30", context_text="tercera"),
        _subject(13, "GOBIERNO", timestamp="00:01:40", context_text="cuarta"),
        _subject(14, "gobierno", timestamp="00:01:50", context_text="quinta"),
        _subject(15, "BCRA", timestamp="00:02:00", context_text="banco"),
    ]
    transcript = ChapterizedTranscript(
        chapters=[
            _chapter(0, 5, [], title="Intro"),
            _chapter(6, 9, [], title="Bridge"),
            _chapter(10, 20, subjects, title="Coyuntura"),
        ]
    )

    result = deduplicate_visual_subjects(transcript)

    assert len(result) == 2
    gobierno = result[0]
    assert gobierno.chapter_index == 2
    assert gobierno.cue_index == 10
    assert gobierno.timestamp == "00:01:10"
    assert gobierno.subject_label == "gobierno"
    assert gobierno.normalized_label == "gobierno"
    assert gobierno.context_text == "primera"
    assert gobierno.occurrences_count == 5
    assert result[1].subject_label == "BCRA"
    assert result[1].occurrences_count == 1


def test_dedupe_preserva_mismo_sujeto_en_capitulos_distintos() -> None:
    transcript = ChapterizedTranscript(
        chapters=[
            _chapter(0, 2, [_subject(0, "gobierno", timestamp="00:00:00")], title="A"),
            _chapter(3, 5, [_subject(3, "Gobierno", timestamp="00:00:03")], title="B"),
        ]
    )

    result = deduplicate_visual_subjects(transcript)

    assert len(result) == 2
    assert result[0].chapter_index == 0
    assert result[0].occurrences_count == 1
    assert result[1].chapter_index == 1
    assert result[1].occurrences_count == 1
    assert result[0].normalized_label == result[1].normalized_label == "gobierno"


def test_dedupe_respeta_orden_original_de_primera_aparicion() -> None:
    subjects = [
        _subject(1, "inflación", asset_kind="conceptual_illustration"),
        _subject(2, "gobierno"),
        _subject(3, "INFLACIÓN", asset_kind="conceptual_illustration"),
        _subject(4, "BCRA"),
        _subject(5, "Gobierno"),
    ]
    transcript = ChapterizedTranscript(chapters=[_chapter(1, 5, subjects)])

    result = deduplicate_visual_subjects(transcript)
    assert [item.subject_label for item in result] == ["inflación", "gobierno", "BCRA"]
    assert [item.occurrences_count for item in result] == [2, 2, 1]
