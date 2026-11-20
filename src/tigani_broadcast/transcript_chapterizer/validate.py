"""Validación fail-closed de capítulos contra la secuencia real de cues."""

from collections.abc import Sequence

from tigani_broadcast.transcript_chapterizer.models import Chapter, ChapterizedTranscript, Cue


class ChapterValidationError(ValueError):
    """Los capítulos no coinciden con las cues. No se repara la propuesta."""


def validate_chapterized_transcript(
    transcript: ChapterizedTranscript,
    cues: Sequence[Cue],
) -> ChapterizedTranscript:
    """Acepta el paquete solo si la partición y las menciones salen de `cues`."""
    if len(cues) == 0:
        raise ChapterValidationError("no hay cues para particionar")

    last_index = len(cues) - 1
    previous_end: int | None = None
    for position, chapter in enumerate(transcript.chapters):
        _require_bounds(position, chapter, last_index)
        if previous_end is None:
            if chapter.start_cue_index != 0:
                raise ChapterValidationError("el primer capítulo tiene que arrancar en la cue 0")
        elif chapter.start_cue_index != previous_end + 1:
            _raise_break(position, chapter.start_cue_index, previous_end)
        _require_times(position, chapter, cues)
        _require_mentions(position, chapter, cues)
        previous_end = chapter.end_cue_index

    if previous_end != last_index:
        raise ChapterValidationError(
            f"el último capítulo termina en la cue {previous_end}; "
            f"tiene que terminar en la cue {last_index}"
        )
    return transcript


def _require_bounds(position: int, chapter: Chapter, last_index: int) -> None:
    if chapter.start_cue_index > last_index or chapter.end_cue_index > last_index:
        raise ChapterValidationError(
            f"capítulo {position}: índice fuera de rango "
            f"({chapter.start_cue_index}..{chapter.end_cue_index}; última cue {last_index})"
        )


def _raise_break(position: int, start: int, previous_end: int) -> None:
    expected = previous_end + 1
    if start > expected:
        raise ChapterValidationError(
            f"capítulo {position}: hay un hueco entre la cue {previous_end} y la cue {start}"
        )
    raise ChapterValidationError(
        f"capítulo {position}: se solapa; arranca en la cue {start} "
        f"y el anterior termina en la cue {previous_end}"
    )


def _require_times(position: int, chapter: Chapter, cues: Sequence[Cue]) -> None:
    start_cue = cues[chapter.start_cue_index]
    end_cue = cues[chapter.end_cue_index]
    if chapter.start_time != start_cue.timestamp:
        raise ChapterValidationError(
            f"capítulo {position}: start_time {chapter.start_time} "
            f"no coincide con la cue {chapter.start_cue_index} ({start_cue.timestamp})"
        )
    if chapter.end_time != end_cue.timestamp:
        raise ChapterValidationError(
            f"capítulo {position}: end_time {chapter.end_time} "
            f"no coincide con la cue {chapter.end_cue_index} ({end_cue.timestamp})"
        )


def _require_mentions(position: int, chapter: Chapter, cues: Sequence[Cue]) -> None:
    for mention in chapter.hard_data:
        _require_mention(
            position=position,
            field_name="hard_data",
            cue_index=mention.cue_index,
            timestamp=mention.timestamp,
            start=chapter.start_cue_index,
            end=chapter.end_cue_index,
            cues=cues,
        )
    for mention in chapter.visual_subjects:
        _require_mention(
            position=position,
            field_name="visual_subjects",
            cue_index=mention.cue_index,
            timestamp=mention.timestamp,
            start=chapter.start_cue_index,
            end=chapter.end_cue_index,
            cues=cues,
        )


def _require_mention(
    *,
    position: int,
    field_name: str,
    cue_index: int,
    timestamp: str,
    start: int,
    end: int,
    cues: Sequence[Cue],
) -> None:
    if cue_index < start or cue_index > end:
        raise ChapterValidationError(
            f"capítulo {position}: {field_name} apunta a la cue {cue_index}, "
            f"fuera de {start}..{end}"
        )
    actual = cues[cue_index].timestamp
    if timestamp != actual:
        raise ChapterValidationError(
            f"capítulo {position}: {field_name} en la cue {cue_index} "
            f"tiene timestamp {timestamp}, distinto de {actual}"
        )
