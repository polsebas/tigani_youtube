"""JSON y Markdown deterministas, sin red."""

import json

from tigani_broadcast.transcript_chapterizer.models import (
    Chapter,
    ChapterizedTranscript,
    HardDataMention,
    VisualSubjectMention,
)
from tigani_broadcast.transcript_chapterizer.render import render_json, render_markdown


def _paquete() -> ChapterizedTranscript:
    return ChapterizedTranscript(
        chapters=[
            Chapter(
                start_cue_index=0,
                end_cue_index=0,
                start_time="00:00:01",
                end_time="00:00:01",
                title="Intro",
                summary="Apertura del día.",
                suggested_lower_third="Arranca el análisis.",
            ),
            Chapter(
                start_cue_index=1,
                end_cue_index=1,
                start_time="00:00:14",
                end_time="00:00:14",
                title="A | B",
                summary="El índice fue del 4,2 por ciento.",
                suggested_lower_third="dato | oficial",
                hard_data=[
                    HardDataMention(
                        cue_index=1,
                        timestamp="00:00:14",
                        indicator_label="inflación",
                        raw_value_text="4,2 por ciento",
                        time_reference="marzo",
                    )
                ],
                visual_subjects=[
                    VisualSubjectMention(
                        cue_index=1,
                        timestamp="00:00:14",
                        subject_label="Banco Central",
                        asset_kind="event_photo",
                        context_text="publicó el dato",
                    )
                ],
            ),
        ]
    )


def test_json_es_utf8_indentado_y_estable() -> None:
    transcript = _paquete()
    rendered = render_json(transcript)

    assert rendered == render_json(transcript)
    assert rendered.endswith("\n")
    assert "\n  " in rendered
    assert "día" in rendered
    assert "\\u" not in rendered
    assert json.loads(rendered) == transcript.model_dump(mode="json")


def test_markdown_lista_rango_zocalo_resumen_y_timestamps() -> None:
    text = render_markdown(_paquete())

    assert "[00:00:01 - 00:00:01]" in text
    assert "[00:00:14 - 00:00:14]" in text
    assert "Arranca el análisis." in text
    assert "Apertura del día." in text
    assert "El índice fue del 4,2 por ciento." in text
    assert "[00:00:14] cue 1: inflación: 4,2 por ciento (marzo)" in text
    assert "[00:00:14] cue 1: event_photo: Banco Central — publicó el dato" in text
    assert "Sin menciones." in text
    assert "## 2. A | B" in text
    assert "dato \\| oficial" in text
    assert text.endswith("\n")
