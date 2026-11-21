"""Validación de cues, menciones y capítulos, independiente del archivo."""

import pytest
from pydantic import ValidationError

from tigani_broadcast.transcript_chapterizer.models import (
    Chapter,
    ChapterizedTranscript,
    Cue,
    DraftChapter,
    DraftChapterizedTranscript,
    DraftHardDataMention,
    DraftVisualSubjectMention,
    HardDataMention,
    VisualSubjectMention,
)


def test_cue_acepta_reloj_canonico_y_texto_limpio() -> None:
    cue = Cue(cue_index=0, timestamp="00:00:03", text="El índice fue del 4,2 por ciento.")

    assert cue.cue_index == 0
    assert cue.timestamp == "00:00:03"
    assert cue.text == "El índice fue del 4,2 por ciento."


def test_cue_acepta_horas_de_tres_digitos() -> None:
    cue = Cue(cue_index=2, timestamp="100:00:00", text="sigue el programa")

    assert cue.timestamp == "100:00:00"


def test_cue_rechaza_indice_negativo() -> None:
    with pytest.raises(ValidationError):
        Cue(cue_index=-1, timestamp="00:00:01", text="hola")


def test_cue_rechaza_timestamp_fuera_de_rango() -> None:
    with pytest.raises(ValidationError, match="timestamp fuera de rango: 00:65:00"):
        Cue(cue_index=0, timestamp="00:65:00", text="dato")


def test_cue_rechaza_segundos_fuera_de_rango() -> None:
    with pytest.raises(ValidationError, match="timestamp fuera de rango: 00:00:60"):
        Cue(cue_index=0, timestamp="00:00:60", text="dato")


def test_cue_rechaza_forma_no_canonica() -> None:
    with pytest.raises(ValidationError, match="forma HH:MM:SS"):
        Cue(cue_index=0, timestamp="1:02:03", text="dato")


def test_cue_rechaza_ceros_de_hora_que_no_son_la_forma_canonica() -> None:
    with pytest.raises(ValidationError, match="forma HH:MM:SS"):
        Cue(cue_index=0, timestamp="000:00:01", text="dato")


def test_cue_rechaza_texto_vacio_o_con_bordes() -> None:
    with pytest.raises(ValidationError, match="limpio y no vacío"):
        Cue(cue_index=0, timestamp="00:00:01", text="")
    with pytest.raises(ValidationError, match="limpio y no vacío"):
        Cue(cue_index=0, timestamp="00:00:01", text="  hola")
    with pytest.raises(ValidationError, match="limpio y no vacío"):
        Cue(cue_index=0, timestamp="00:00:01", text="hola  ")


def test_cue_rechaza_campos_extra_y_no_se_puede_mutar() -> None:
    with pytest.raises(ValidationError, match="extra"):
        Cue.model_validate(
            {"cue_index": 0, "timestamp": "00:00:01", "text": "hola", "source": "youtube"}
        )

    cue = Cue(cue_index=0, timestamp="00:00:01", text="hola")
    with pytest.raises(ValidationError):
        cue.text = "otro"


@pytest.mark.parametrize("blank", ["", "   ", "\t"])
@pytest.mark.parametrize("model", [HardDataMention, DraftHardDataMention])
def test_time_reference_vacio_se_normaliza_a_none(blank: str, model: type) -> None:
    if model is HardDataMention:
        mention = model(
            cue_index=1,
            timestamp="00:00:14",
            indicator_label="inflación",
            raw_value_text="4,2 por ciento",
            time_reference=blank,
        )
    else:
        mention = model(
            cue_index=1,
            indicator_label="inflación",
            raw_value_text="4,2 por ciento",
            time_reference=blank,
        )

    assert mention.time_reference is None


def test_hard_data_acepta_time_reference_opcional_y_conserva_el_texto() -> None:
    sin_periodo = HardDataMention(
        cue_index=1,
        timestamp="00:00:14",
        indicator_label=" inflación ",
        raw_value_text="4,2 por ciento",
    )
    con_periodo = sin_periodo.model_copy(update={"time_reference": "marzo"})

    assert sin_periodo.time_reference is None
    assert sin_periodo.indicator_label == " inflación "
    assert con_periodo.time_reference == "marzo"


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("indicator_label", ""),
        ("indicator_label", "   "),
        ("raw_value_text", "\t"),
    ],
)
def test_hard_data_rechaza_texto_vacio(field_name: str, value: str) -> None:
    payload = {
        "cue_index": 0,
        "timestamp": "00:00:01",
        "indicator_label": "inflación",
        "raw_value_text": "4,2",
        field_name: value,
    }
    with pytest.raises(ValidationError, match="después de strip"):
        HardDataMention.model_validate(payload)


@pytest.mark.parametrize("asset_kind", ["event_photo", "conceptual_illustration"])
def test_visual_subject_acepta_los_dos_tipos_de_asset(asset_kind: str) -> None:
    mention = VisualSubjectMention.model_validate(
        {
            "cue_index": 0,
            "timestamp": "00:00:21",
            "subject_label": "Banco Central",
            "asset_kind": asset_kind,
            "context_text": "publicó el dato",
        }
    )

    assert mention.asset_kind == asset_kind


def test_visual_subject_rechaza_asset_desconocido_y_texto_vacio() -> None:
    with pytest.raises(ValidationError):
        VisualSubjectMention.model_validate(
            {
                "cue_index": 0,
                "timestamp": "00:00:21",
                "subject_label": "Banco Central",
                "asset_kind": "foto",
                "context_text": "publicó el dato",
            }
        )
    with pytest.raises(ValidationError, match="después de strip"):
        VisualSubjectMention(
            cue_index=0,
            timestamp="00:00:21",
            subject_label="   ",
            asset_kind="event_photo",
            context_text="publicó el dato",
        )


def test_capitulo_de_una_cue_puede_ir_sin_menciones() -> None:
    primero = _chapter(0, 0)
    segundo = _chapter(1, 1)

    assert primero.hard_data == []
    assert primero.visual_subjects == []
    assert primero.hard_data is not segundo.hard_data
    assert primero.visual_subjects is not segundo.visual_subjects


def test_capitulo_rechaza_rango_invertido_y_reloj_invalido() -> None:
    with pytest.raises(ValidationError, match="start_cue_index no puede ser mayor"):
        _chapter(2, 1)
    with pytest.raises(ValidationError, match="timestamp fuera de rango"):
        Chapter(
            start_cue_index=0,
            end_cue_index=0,
            start_time="00:65:00",
            end_time="00:00:01",
            title="Intro",
            summary="Apertura.",
            suggested_lower_third="Apertura del programa.",
        )


def test_el_paquete_exige_al_menos_un_capitulo() -> None:
    with pytest.raises(ValidationError, match="at least 1"):
        ChapterizedTranscript(chapters=[])


def test_el_borrador_no_lleva_timestamps_ni_menciones_anidadas() -> None:
    chapter_fields = set(DraftChapter.model_fields)
    hard_fields = set(DraftHardDataMention.model_fields)
    visual_fields = set(DraftVisualSubjectMention.model_fields)
    package_fields = set(DraftChapterizedTranscript.model_fields)

    assert chapter_fields == {
        "start_cue_index",
        "end_cue_index",
        "title",
        "summary",
        "suggested_lower_third",
    }
    assert hard_fields == {"cue_index", "indicator_label", "raw_value_text", "time_reference"}
    assert visual_fields == {"cue_index", "subject_label", "asset_kind", "context_text"}
    assert package_fields == {"chapters", "hard_data", "visual_subjects"}
    assert "timestamp" not in chapter_fields | hard_fields | visual_fields


def test_el_borrador_separa_las_listas_y_rechaza_un_reloj_colado() -> None:
    primero = DraftChapterizedTranscript(chapters=[_draft_chapter()])
    segundo = DraftChapterizedTranscript(chapters=[_draft_chapter()])

    assert primero.hard_data == []
    assert primero.visual_subjects == []
    assert primero.hard_data is not segundo.hard_data
    assert primero.visual_subjects is not segundo.visual_subjects
    with pytest.raises(ValidationError, match="extra"):
        DraftHardDataMention.model_validate(
            {
                "cue_index": 0,
                "indicator_label": "inflación",
                "raw_value_text": "4,2",
                "timestamp": "00:00:01",
            }
        )
    with pytest.raises(ValidationError, match="extra"):
        DraftChapter.model_validate(
            {
                "start_cue_index": 0,
                "end_cue_index": 0,
                "title": "Intro",
                "summary": "Apertura.",
                "suggested_lower_third": "Apertura.",
                "hard_data": [],
            }
        )


def test_el_borrador_rechaza_etiquetas_vacias() -> None:
    with pytest.raises(ValidationError, match="después de strip"):
        DraftHardDataMention(cue_index=0, indicator_label="   ", raw_value_text="4,2")
    with pytest.raises(ValidationError, match="después de strip"):
        DraftVisualSubjectMention(
            cue_index=0,
            subject_label="Banco Central",
            asset_kind="event_photo",
            context_text="  ",
        )


def _draft_chapter() -> DraftChapter:
    return DraftChapter(
        start_cue_index=0,
        end_cue_index=0,
        title="Intro",
        summary="Apertura.",
        suggested_lower_third="Apertura del programa.",
    )


def _chapter(start: int, end: int) -> Chapter:
    return Chapter(
        start_cue_index=start,
        end_cue_index=end,
        start_time="00:00:01",
        end_time="00:00:01",
        title="Intro",
        summary="Apertura.",
        suggested_lower_third="Apertura del programa.",
    )
