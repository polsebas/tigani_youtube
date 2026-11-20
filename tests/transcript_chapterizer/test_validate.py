"""El paquete de capítulos se acepta solo si coincide con las cues."""

import pytest

from tigani_broadcast.transcript_chapterizer.models import (
    Chapter,
    ChapterizedTranscript,
    Cue,
    HardDataMention,
    VisualSubjectMention,
)
from tigani_broadcast.transcript_chapterizer.validate import (
    ChapterValidationError,
    validate_chapterized_transcript,
)

_CUADRO = [
    (0, "00:00:01", "Buen día, arranca el programa."),
    (1, "00:00:14", "El índice fue del 4,2 por ciento."),
    (2, "00:00:21", "El Banco Central publicó el dato."),
    (3, "00:01:03", "Gracias y nos vemos."),
]


def _cues() -> list[Cue]:
    return [Cue(cue_index=index, timestamp=stamp, text=text) for index, stamp, text in _CUADRO]


def _chapter(
    cues: list[Cue],
    start: int,
    end: int,
    *,
    title: str,
    hard_data: list[HardDataMention] | None = None,
    visual_subjects: list[VisualSubjectMention] | None = None,
) -> Chapter:
    return Chapter(
        start_cue_index=start,
        end_cue_index=end,
        start_time=cues[start].timestamp,
        end_time=cues[end].timestamp,
        title=title,
        summary=f"Resumen de {title}.",
        suggested_lower_third=title,
        hard_data=hard_data or [],
        visual_subjects=visual_subjects or [],
    )


def _hard(cue_index: int, timestamp: str) -> HardDataMention:
    return HardDataMention(
        cue_index=cue_index,
        timestamp=timestamp,
        indicator_label="inflación",
        raw_value_text="4,2 por ciento",
        time_reference="marzo",
    )


def _visual(cue_index: int, timestamp: str) -> VisualSubjectMention:
    return VisualSubjectMention(
        cue_index=cue_index,
        timestamp=timestamp,
        subject_label="Banco Central",
        asset_kind="event_photo",
        context_text="publicó el dato",
    )


def _valido() -> tuple[ChapterizedTranscript, list[Cue]]:
    cues = _cues()
    transcript = ChapterizedTranscript(
        chapters=[
            _chapter(cues, 0, 0, title="Intro"),
            _chapter(
                cues,
                1,
                2,
                title="La inflación de marzo",
                hard_data=[_hard(1, "00:00:14")],
                visual_subjects=[_visual(2, "00:00:21")],
            ),
            _chapter(cues, 3, 3, title="Cierre"),
        ]
    )
    return transcript, cues


def _reemplazar(
    transcript: ChapterizedTranscript,
    position: int,
    **changes: object,
) -> ChapterizedTranscript:
    chapters = list(transcript.chapters)
    chapters[position] = chapters[position].model_copy(update=changes)
    return transcript.model_copy(update={"chapters": chapters})


def test_acepta_particion_completa_con_intro_y_cierre_vacios() -> None:
    transcript, cues = _valido()

    accepted = validate_chapterized_transcript(transcript, cues)

    assert accepted is transcript
    assert accepted.chapters[0].hard_data == []
    assert accepted.chapters[0].visual_subjects == []
    assert accepted.chapters[2].hard_data == []
    assert accepted.chapters[2].visual_subjects == []
    assert accepted.chapters[0].end_time == "00:00:01"
    assert accepted.chapters[1].start_time == "00:00:14"
    assert accepted.chapters[1].end_time == "00:00:21"
    assert accepted.chapters[2].start_time == "00:01:03"


def test_rechaza_un_hueco_entre_capitulos() -> None:
    cues = _cues()
    transcript = ChapterizedTranscript(
        chapters=[
            _chapter(cues, 0, 0, title="Intro"),
            _chapter(cues, 2, 2, title="Saltea una cue"),
            _chapter(cues, 3, 3, title="Cierre"),
        ]
    )

    with pytest.raises(
        ChapterValidationError,
        match=r"capítulo 1: hay un hueco entre la cue 0 y la cue 2",
    ):
        validate_chapterized_transcript(transcript, cues)


def test_rechaza_un_solape() -> None:
    cues = _cues()
    transcript = ChapterizedTranscript(
        chapters=[
            _chapter(cues, 0, 1, title="Se come el dato"),
            _chapter(cues, 1, 3, title="Lo repite"),
        ]
    )

    with pytest.raises(ChapterValidationError, match=r"capítulo 1: se solapa; arranca en la cue 1"):
        validate_chapterized_transcript(transcript, cues)


def test_rechaza_si_el_primero_no_arranca_en_cero() -> None:
    cues = _cues()
    transcript = ChapterizedTranscript(chapters=[_chapter(cues, 1, 3, title="Sin intro")])

    with pytest.raises(
        ChapterValidationError,
        match="el primer capítulo tiene que arrancar en la cue 0",
    ):
        validate_chapterized_transcript(transcript, cues)


def test_rechaza_si_el_ultimo_no_cubre_la_cue_final() -> None:
    cues = _cues()
    transcript = ChapterizedTranscript(chapters=[_chapter(cues, 0, 2, title="Sin cierre")])

    with pytest.raises(
        ChapterValidationError,
        match=r"el último capítulo termina en la cue 2; tiene que terminar en la cue 3",
    ):
        validate_chapterized_transcript(transcript, cues)


def test_rechaza_indice_de_capitulo_fuera_de_las_cues() -> None:
    transcript = ChapterizedTranscript(
        chapters=[
            Chapter(
                start_cue_index=0,
                end_cue_index=9,
                start_time="00:00:01",
                end_time="00:00:01",
                title="Desborda",
                summary="No hay tantas cues.",
                suggested_lower_third="Desborda.",
            )
        ]
    )

    with pytest.raises(ChapterValidationError, match=r"capítulo 0: índice fuera de rango \(0\.\.9"):
        validate_chapterized_transcript(transcript, _cues())


@pytest.mark.parametrize("field_name", ["start_time", "end_time"])
def test_rechaza_reloj_alterado(field_name: str) -> None:
    transcript, cues = _valido()
    broken = _reemplazar(transcript, 1, **{field_name: "09:09:09"})

    with pytest.raises(ChapterValidationError, match=rf"capítulo 1: {field_name} 09:09:09"):
        validate_chapterized_transcript(broken, cues)


@pytest.mark.parametrize("field_name", ["hard_data", "visual_subjects"])
@pytest.mark.parametrize("cue_index", [3, 99])
def test_rechaza_mencion_fuera_del_capitulo(field_name: str, cue_index: int) -> None:
    transcript, cues = _valido()
    if field_name == "hard_data":
        mention = _hard(cue_index, "00:00:01")
    else:
        mention = _visual(cue_index, "00:00:01")
    broken = _reemplazar(transcript, 1, **{field_name: [mention]})

    with pytest.raises(
        ChapterValidationError,
        match=rf"capítulo 1: {field_name} apunta a la cue {cue_index}, fuera de 1\.\.2",
    ):
        validate_chapterized_transcript(broken, cues)


@pytest.mark.parametrize(
    ("field_name", "cue_index", "timestamp"),
    [
        ("hard_data", 1, "00:00:15"),
        ("visual_subjects", 2, "00:00:22"),
    ],
)
def test_rechaza_timestamp_distinto_al_de_la_cue(
    field_name: str,
    cue_index: int,
    timestamp: str,
) -> None:
    transcript, cues = _valido()
    if field_name == "hard_data":
        mention: HardDataMention | VisualSubjectMention = _hard(cue_index, timestamp)
    else:
        mention = _visual(cue_index, timestamp)
    broken = _reemplazar(transcript, 1, **{field_name: [mention]})

    with pytest.raises(
        ChapterValidationError,
        match=rf"capítulo 1: {field_name} en la cue {cue_index} tiene timestamp {timestamp}",
    ):
        validate_chapterized_transcript(broken, cues)


def test_sin_cues_no_hay_particion() -> None:
    transcript, _cues_ignoradas = _valido()

    with pytest.raises(ChapterValidationError, match="no hay cues para particionar"):
        validate_chapterized_transcript(transcript, [])
