"""Ensamblado determinista. El borrador plano no trae relojes ni menciones anidadas."""

from typing import Literal

import pytest

from tigani_broadcast.transcript_chapterizer.chapterizer import assemble_chapterized_transcript
from tigani_broadcast.transcript_chapterizer.models import (
    Cue,
    DraftChapter,
    DraftChapterizedTranscript,
    DraftHardDataMention,
    DraftVisualSubjectMention,
)
from tigani_broadcast.transcript_chapterizer.validate import (
    ChapterValidationError,
    validate_chapterized_transcript,
)


def _cues(count: int = 36) -> list[Cue]:
    return [
        Cue(cue_index=index, timestamp=f"00:00:{index:02d}", text=f"Texto {index}.")
        for index in range(count)
    ]


def _chapter(start: int, end: int, title: str | None = None) -> DraftChapter:
    label = title if title is not None else f"Tramo {start}-{end}"
    return DraftChapter(
        start_cue_index=start,
        end_cue_index=end,
        title=label,
        summary=f"Resumen de {label}.",
        suggested_lower_third=label,
    )


def _hard(
    cue_index: int,
    label: str,
    raw_value_text: str,
    time_reference: str | None = None,
) -> DraftHardDataMention:
    return DraftHardDataMention(
        cue_index=cue_index,
        indicator_label=label,
        raw_value_text=raw_value_text,
        time_reference=time_reference,
    )


def _visual(
    cue_index: int,
    label: str,
    asset_kind: Literal["event_photo", "conceptual_illustration"],
) -> DraftVisualSubjectMention:
    return DraftVisualSubjectMention(
        cue_index=cue_index,
        subject_label=label,
        asset_kind=asset_kind,
        context_text=f"contexto de {label}",
    )


def _borrador(
    chapters: list[DraftChapter],
    hard_data: list[DraftHardDataMention] | None = None,
    visual_subjects: list[DraftVisualSubjectMention] | None = None,
) -> DraftChapterizedTranscript:
    return DraftChapterizedTranscript(
        chapters=chapters,
        hard_data=hard_data or [],
        visual_subjects=visual_subjects or [],
    )


def test_ubica_la_cue_20_en_su_capitulo_y_copia_el_timestamp_real() -> None:
    cues = _cues()
    draft = _borrador(
        chapters=[
            _chapter(0, 19, "Apertura"),
            _chapter(20, 25, "La deuda"),
            _chapter(26, 35, "El swap"),
        ],
        hard_data=[
            _hard(25, "deuda", "4600 millones"),
            _hard(20, "inflación", "2,5%"),
            _hard(20, "reservas", "17.000 millones", "hoy"),
        ],
        visual_subjects=[
            _visual(35, "cierre", "conceptual_illustration"),
            _visual(26, "swap", "event_photo"),
        ],
    )

    accepted = assemble_chapterized_transcript(draft, cues)

    assert validate_chapterized_transcript(accepted, cues) is accepted
    assert accepted.chapters[0].hard_data == []
    assert accepted.chapters[0].visual_subjects == []
    assert accepted.chapters[0].start_time == "00:00:00"
    assert accepted.chapters[0].end_time == "00:00:19"
    deuda = accepted.chapters[1]
    assert deuda.start_time == "00:00:20"
    assert deuda.end_time == "00:00:25"
    assert [item.cue_index for item in deuda.hard_data] == [20, 20, 25]
    assert [item.indicator_label for item in deuda.hard_data] == ["inflación", "reservas", "deuda"]
    assert [item.timestamp for item in deuda.hard_data] == ["00:00:20", "00:00:20", "00:00:25"]
    assert [item.raw_value_text for item in deuda.hard_data] == [
        "2,5%",
        "17.000 millones",
        "4600 millones",
    ]
    assert [item.time_reference for item in deuda.hard_data] == [None, "hoy", None]
    assert deuda.visual_subjects == []
    swap = accepted.chapters[2]
    assert swap.start_time == "00:00:26"
    assert swap.end_time == "00:00:35"
    assert swap.hard_data == []
    assert [item.cue_index for item in swap.visual_subjects] == [26, 35]
    assert [item.timestamp for item in swap.visual_subjects] == ["00:00:26", "00:00:35"]
    assert [item.asset_kind for item in swap.visual_subjects] == [
        "event_photo",
        "conceptual_illustration",
    ]
    assert all(item.cue_index != 20 for item in swap.hard_data)


def test_rechaza_cues_vacias() -> None:
    draft = _borrador(chapters=[_chapter(0, 0)])

    with pytest.raises(ChapterValidationError, match="no hay cues para particionar"):
        assemble_chapterized_transcript(draft, [])


@pytest.mark.parametrize(
    ("start", "end", "match"),
    [
        (36, 36, r"capítulo 0: start_cue_index 36 fuera de 0\.\.35"),
        (0, 36, r"capítulo 0: end_cue_index 36 fuera de 0\.\.35"),
        (2, 1, r"capítulo 0: start_cue_index no puede ser mayor que end_cue_index"),
    ],
)
def test_rechaza_rango_de_capitulo_inutilizable(start: int, end: int, match: str) -> None:
    draft = _borrador(chapters=[_chapter(start, end)])

    with pytest.raises(ChapterValidationError, match=match):
        assemble_chapterized_transcript(draft, _cues())


@pytest.mark.parametrize("field_name", ["hard_data", "visual_subjects"])
def test_rechaza_cue_index_de_mencion_fuera_de_rango(field_name: str) -> None:
    if field_name == "hard_data":
        draft = _borrador(
            chapters=[_chapter(0, 35)],
            hard_data=[_hard(36, "inflación", "2,5%")],
        )
    else:
        draft = _borrador(
            chapters=[_chapter(0, 35)],
            visual_subjects=[_visual(36, "swap", "event_photo")],
        )

    with pytest.raises(
        ChapterValidationError,
        match=rf"{field_name} apunta a la cue 36, fuera de 0\.\.35",
    ):
        assemble_chapterized_transcript(draft, _cues())


@pytest.mark.parametrize("field_name", ["hard_data", "visual_subjects"])
def test_rechaza_mencion_que_no_cae_en_ningun_capitulo(field_name: str) -> None:
    chapters = [_chapter(0, 0, "Intro"), _chapter(2, 2, "Cierre")]
    if field_name == "hard_data":
        draft = _borrador(chapters=chapters, hard_data=[_hard(1, "inflación", "2,5%")])
    else:
        draft = _borrador(chapters=chapters, visual_subjects=[_visual(1, "swap", "event_photo")])

    with pytest.raises(
        ChapterValidationError,
        match=rf"{field_name} de la cue 1 no cae en ningún capítulo",
    ):
        assemble_chapterized_transcript(draft, _cues(3))


@pytest.mark.parametrize("field_name", ["hard_data", "visual_subjects"])
def test_rechaza_mencion_en_mas_de_un_capitulo(field_name: str) -> None:
    chapters = [_chapter(0, 1, "Se solapa"), _chapter(1, 2, "También")]
    if field_name == "hard_data":
        draft = _borrador(chapters=chapters, hard_data=[_hard(1, "inflación", "2,5%")])
    else:
        draft = _borrador(chapters=chapters, visual_subjects=[_visual(1, "swap", "event_photo")])

    with pytest.raises(
        ChapterValidationError,
        match=rf"{field_name} de la cue 1 cae en más de un capítulo",
    ):
        assemble_chapterized_transcript(draft, _cues(3))


def test_rechaza_un_hueco_aunque_las_menciones_queden_ubicadas() -> None:
    draft = _borrador(
        chapters=[_chapter(0, 19, "Apertura"), _chapter(26, 35, "El swap")],
        hard_data=[_hard(0, "apertura", "hola")],
    )

    with pytest.raises(ChapterValidationError, match=r"capítulo 1: hay un hueco"):
        assemble_chapterized_transcript(draft, _cues())


def test_rechaza_un_solape_aunque_la_mencion_tenga_un_solo_capitulo() -> None:
    draft = _borrador(
        chapters=[_chapter(0, 25, "La deuda"), _chapter(20, 35, "El swap")],
        hard_data=[_hard(0, "apertura", "hola")],
    )

    with pytest.raises(ChapterValidationError, match=r"capítulo 1: se solapa"):
        assemble_chapterized_transcript(draft, _cues())


def test_rechaza_una_particion_que_no_cubre_todas_las_cues() -> None:
    draft = _borrador(chapters=[_chapter(0, 25, "Incompleto")])

    with pytest.raises(
        ChapterValidationError,
        match=r"el último capítulo termina en la cue 25; tiene que terminar en la cue 35",
    ):
        assemble_chapterized_transcript(draft, _cues())
