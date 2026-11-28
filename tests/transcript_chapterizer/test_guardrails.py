"""Guardrails offline. No hay red ni una segunda llamada al modelo."""

from types import SimpleNamespace

import pytest
from agno.exceptions import OutputCheckError

from tigani_broadcast.transcript_chapterizer.chapterizer import format_chapterizer_input
from tigani_broadcast.transcript_chapterizer.guardrails import (
    MAX_LOWER_THIRD_LENGTH,
    CueGroundingGuardrail,
    LowerThirdLengthGuardrail,
    SpanishLanguageGuardrail,
    SummaryHardDataConsistencyGuardrail,
    TimeReferenceGuardrail,
    normalized_numbers,
    numeric_cue_indexes,
)
from tigani_broadcast.transcript_chapterizer.models import (
    Cue,
    DraftChapter,
    DraftChapterDetails,
    DraftChapterizedTranscript,
    DraftHardDataMention,
)


def _cues(*texts: str) -> list[Cue]:
    return [
        Cue(cue_index=index, timestamp=f"00:00:{index:02d}", text=text)
        for index, text in enumerate(texts)
    ]


def _draft(*texts: str, mentions: list[DraftHardDataMention], lower: str = "Zócalo") -> object:
    last = len(texts) - 1
    draft = DraftChapterizedTranscript(
        chapters=[
            DraftChapter(
                start_cue_index=0,
                end_cue_index=last,
                title="Tramo",
                summary="Resumen.",
                suggested_lower_third=lower,
            )
        ],
        hard_data=mentions,
    )
    return SimpleNamespace(content=draft)


def _hard(
    cue_index: int,
    raw_value_text: str,
    indicator_label: str = "reservas netas",
    time_reference: str | None = None,
) -> DraftHardDataMention:
    return DraftHardDataMention(
        cue_index=cue_index,
        indicator_label=indicator_label,
        raw_value_text=raw_value_text,
        time_reference=time_reference,
    )


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("8,000", "8.000"),
        ("8,000", "8000"),
        ("8.000", "8000"),
        ("2.5%", "2,5%"),
        ("2.5", "2,5"),
        ("1.234,56", "1234.56"),
        ("1,234.56", "1234.56"),
        ("1.234.567", "1234567"),
        ("1.234.56", "1234.56"),
    ],
)
def test_normaliza_separadores_de_miles_y_decimales(left: str, right: str) -> None:
    assert normalized_numbers(left) == normalized_numbers(right)
    assert normalized_numbers(left)


def test_no_confunde_26_000_con_8_000() -> None:
    assert normalized_numbers("26,000").isdisjoint(normalized_numbers("8,000"))


def test_coincidencia_exacta_no_cambia_el_indice() -> None:
    cues = _cues("el índice dio 2.5% hoy", "otra cue sin esa cifra")
    run = _draft(
        *[cue.text for cue in cues],
        mentions=[_hard(0, "2,5%", "índice de inflación", "hoy")],
    )
    guard = CueGroundingGuardrail()
    guard.bind(cues)

    guard.check(run)  # type: ignore[arg-type]

    assert run.content.hard_data[0].cue_index == 0


@pytest.mark.parametrize("raw_value_text", ["8,000 millones", "8.000 millones", "8000"])
def test_reancla_8_000_de_la_cue_9_a_la_cue_10(raw_value_text: str) -> None:
    texts = ["sin cifra"] * 11
    texts[9] = (
        "alto de Latinoamérica, teníamos las reservas 26,000 millones de dólares "
        "más altas las reservas netas que"
    )
    texts[10] = "hoy son negativas en 17,000 millones teníamos 8,000 de reservas netas. En en"
    cues = _cues(*texts)
    run = _draft(*texts, mentions=[_hard(9, raw_value_text, time_reference="hoy")])
    guard = CueGroundingGuardrail()
    guard.bind(cues)

    guard.check(run)  # type: ignore[arg-type]

    assert run.content.hard_data[0].cue_index == 10
    assert run.content.hard_data[0].raw_value_text == raw_value_text


def test_reancla_hacia_la_cue_anterior_si_es_la_unica() -> None:
    cues = _cues("el índice dio 2,5%", "acá no está la cifra")
    run = _draft(*[cue.text for cue in cues], mentions=[_hard(1, "2.5%", "índice de inflación")])
    guard = CueGroundingGuardrail()
    guard.bind(cues)

    guard.check(run)  # type: ignore[arg-type]

    assert run.content.hard_data[0].cue_index == 0


def test_reancla_hacia_la_cue_siguiente_si_es_la_unica() -> None:
    cues = _cues("acá no está la cifra", "el índice dio 2.5%")
    run = _draft(*[cue.text for cue in cues], mentions=[_hard(0, "2,5%", "índice de inflación")])
    guard = CueGroundingGuardrail()
    guard.bind(cues)

    guard.check(run)  # type: ignore[arg-type]

    assert run.content.hard_data[0].cue_index == 1


def test_reancla_4600_de_la_cue_17_a_la_cue_19() -> None:
    texts = ["sin cifra"] * 20
    texts[17] = (
        "De los mercados lo echaron a Caputo en enero del año 2018 "
        "y desde que lo echaron a Caputo con"
    )
    texts[18] = (
        "Macri, nunca más volvimos al mercado voluntario de colocación de deuda. "
        "Lo que hicieron ahora fue sacar un bono"
    )
    texts[19] = (
        "para que lo compren en forma interna algunos para poder pagar la deuda "
        "de 4600 millones de dólares que vence el 9 de enero."
    )
    cues = _cues(*texts)
    run = _draft(*texts, mentions=[_hard(17, "4600 millones de dólares", "deuda", "9 de enero")])
    guard = CueGroundingGuardrail()
    guard.bind(cues, start=17, end=19)

    guard.check(run)  # type: ignore[arg-type]

    assert run.content.hard_data[0].cue_index == 19


def test_descarta_si_la_cifra_aparece_en_dos_cues_lejanas_del_capitulo() -> None:
    cues = _cues(
        "deuda de 4600 millones",
        "sin cifra",
        "tampoco",
        "sigue sin la cifra",
        "otra vez 4600 millones",
    )
    run = _draft(
        *[cue.text for cue in cues],
        mentions=[_hard(2, "4600 millones", "deuda")],
    )
    guard = CueGroundingGuardrail()
    guard.bind(cues)

    guard.check(run)  # type: ignore[arg-type]

    assert run.content.hard_data == []


def test_descarta_si_la_cifra_no_esta_en_el_capitulo() -> None:
    cues = _cues("teníamos 8,000", "sin cifra", "tampoco hay cifra escrita")
    run = _draft(
        *[cue.text for cue in cues],
        mentions=[_hard(2, "5", "clases"), _hard(0, "8,000")],
    )
    guard = CueGroundingGuardrail()
    guard.bind(cues, start=1, end=2)

    guard.check(run)  # type: ignore[arg-type]

    assert run.content.hard_data == []


def test_descarta_si_la_cifra_esta_en_las_dos_cues_adyacentes() -> None:
    cues = _cues("teníamos 8,000", "sin cifra", "también 8.000")
    run = _draft(*[cue.text for cue in cues], mentions=[_hard(1, "8000")])
    guard = CueGroundingGuardrail()
    guard.bind(cues)

    guard.check(run)  # type: ignore[arg-type]

    assert run.content.hard_data == []


def test_descarta_raw_value_text_sin_digito() -> None:
    cues = _cues("la mitad del relato", "la tasa fue 34,5%")
    run = _draft(
        *[cue.text for cue in cues],
        mentions=[
            _hard(0, "la mitad", "relato"),
            _hard(1, "34,5%", "tasa"),
        ],
    )
    guard = CueGroundingGuardrail()
    guard.bind(cues)

    guard.check(run)  # type: ignore[arg-type]

    assert [mention.raw_value_text for mention in run.content.hard_data] == ["34,5%"]


def test_cinco_equivale_a_5_y_se_ancla_en_la_cue() -> None:
    assert normalized_numbers("cinco") == normalized_numbers("5")
    assert normalized_numbers("diez") == normalized_numbers("10")
    cues = _cues("cinco clases de entre 45 minutos", "sin otra cifra dicha")
    run = _draft(*[cue.text for cue in cues], mentions=[_hard(1, "5", "clases")])
    guard = CueGroundingGuardrail()
    guard.bind(cues)

    guard.check(run)  # type: ignore[arg-type]

    assert len(run.content.hard_data) == 1
    assert run.content.hard_data[0].cue_index == 0
    assert run.content.hard_data[0].raw_value_text == "5"


def test_rechaza_anio_en_indicator_label_sin_time_reference() -> None:
    run = _draft("en 2015 había 8,000", mentions=[_hard(0, "8,000", "Reservas netas 2015")])
    guard = TimeReferenceGuardrail()

    with pytest.raises(OutputCheckError, match="time_reference es None"):
        guard.check(run)  # type: ignore[arg-type]


def test_acepta_el_anio_cuando_time_reference_lo_guarda() -> None:
    run = _draft(
        "en 2015 había 8,000",
        mentions=[_hard(0, "8,000", "Reservas netas 2015", "2015")],
    )

    TimeReferenceGuardrail().check(run)  # type: ignore[arg-type]

    assert run.content.hard_data[0].time_reference == "2015"


def test_rechaza_zocalo_de_mas_de_100_caracteres() -> None:
    run = _draft("sin cifra", mentions=[], lower="x" * (MAX_LOWER_THIRD_LENGTH + 1))

    with pytest.raises(OutputCheckError, match="101 caracteres"):
        LowerThirdLengthGuardrail().check(run)  # type: ignore[arg-type]


def test_rechaza_el_zocalo_de_un_detalle_aislado() -> None:
    run = SimpleNamespace(
        content=DraftChapterDetails(
            summary="Resumen.",
            suggested_lower_third="x" * (MAX_LOWER_THIRD_LENGTH + 1),
        )
    )

    with pytest.raises(OutputCheckError, match="101 caracteres"):
        LowerThirdLengthGuardrail().check(run)  # type: ignore[arg-type]


def test_acepta_zocalo_de_100_caracteres() -> None:
    run = _draft("sin cifra", mentions=[], lower="x" * MAX_LOWER_THIRD_LENGTH)

    LowerThirdLengthGuardrail().check(run)  # type: ignore[arg-type]


def test_el_preescaneo_lista_solo_las_cues_con_cifras() -> None:
    cues = _cues("hola", "dio 2,5%", "cierra", "otro 8,000")

    assert numeric_cue_indexes(cues) == [1, 3]
    assert format_chapterizer_input(cues).endswith("Cues con cifras detectadas: [1, 3]")
    assert format_chapterizer_input(cues).splitlines()[0] == "0 | [00:00:00] hola"


def test_reancla_dentro_del_tramo_y_rechaza_la_coincidencia_de_afuera() -> None:
    cues = _cues("afuera 8,000", "sin cifra", "acá sí 8.000")
    dentro = _draft(*[cue.text for cue in cues], mentions=[_hard(1, "8000")])
    guard = CueGroundingGuardrail()
    guard.bind(cues, start=1, end=2)

    guard.check(dentro)  # type: ignore[arg-type]

    assert dentro.content.hard_data[0].cue_index == 2

    afuera = _draft(*[cue.text for cue in cues], mentions=[_hard(1, "8000")])
    guard.bind(cues, start=1, end=1)
    guard.check(afuera)  # type: ignore[arg-type]
    assert afuera.content.hard_data == []


_RESUMEN_EN_INGLES = (
    "The text highlights key economic indicators, including a current inflation rate of 2.5% "
    "and historical reserve data. Reserves were previously 26,000 millones, which is "
    "significantly higher than the current negative balance of 17,000 millones."
)
_ZOCALO_EN_INGLES = (
    "Economic Indicators: 2.5% Inflation, 26,000 M Reserves (Past), -17,000 M (Current)"
)
_CIERRE_CUALITATIVO = (
    "El tramo habla de comisiones bancarias por colocación de bonos y promociona "
    "una suscripción especial."
)


def _detalle_simple(
    summary: str,
    lower: str,
    hard: list[DraftHardDataMention] | None = None,
) -> object:
    return SimpleNamespace(
        content=DraftChapterDetails(
            summary=summary,
            suggested_lower_third=lower,
            hard_data=hard or [],
        )
    )


def test_rechaza_resumen_con_cifras_si_hard_data_esta_vacio() -> None:
    run = _detalle_simple(
        "La inflación de hoy fue 2.5% y las reservas eran 26,000 millones.",
        "Cifras del día",
    )

    with pytest.raises(OutputCheckError, match="hard_data está vacío"):
        SummaryHardDataConsistencyGuardrail().check(run)  # type: ignore[arg-type]


def test_acepta_un_cierre_cualitativo_sin_hard_data() -> None:
    run = _detalle_simple(_CIERRE_CUALITATIVO, "Comisiones por bonos y suscripción especial")

    SummaryHardDataConsistencyGuardrail().check(run)  # type: ignore[arg-type]


def test_acepta_cifras_en_el_resumen_cuando_hard_data_las_tiene() -> None:
    run = _detalle_simple(
        "La inflación fue 2.5%.",
        "Inflación: 2.5%",
        [_hard(1, "2.5%", "índice de inflación", "hoy")],
    )

    SummaryHardDataConsistencyGuardrail().check(run)  # type: ignore[arg-type]


def test_rechaza_el_capitulo_1_en_ingles() -> None:
    run = _detalle_simple(_RESUMEN_EN_INGLES, "Zócalo en español del día")
    zocalo = _detalle_simple(_CIERRE_CUALITATIVO, _ZOCALO_EN_INGLES)

    with pytest.raises(OutputCheckError, match="summary está redactado en inglés"):
        SpanishLanguageGuardrail().check(run)  # type: ignore[arg-type]
    with pytest.raises(OutputCheckError, match="suggested_lower_third está redactado en inglés"):
        SpanishLanguageGuardrail().check(zocalo)  # type: ignore[arg-type]


def test_acepta_espanol_con_anglicismos_tecnicos() -> None:
    run = _detalle_simple(
        "El swap con Estados Unidos y el default no se pagan en USD.",
        "Swap y default en USD",
    )

    SpanishLanguageGuardrail().check(run)  # type: ignore[arg-type]


def test_ignora_un_contenido_que_no_es_el_borrador() -> None:
    import asyncio

    run = SimpleNamespace(content="texto suelto")
    guards = (
        CueGroundingGuardrail(),
        TimeReferenceGuardrail(),
        LowerThirdLengthGuardrail(),
    )
    for guard in guards:
        guard.check(run)  # type: ignore[arg-type]
        asyncio.run(guard.async_check(run))  # type: ignore[arg-type]


def test_las_descripciones_piden_anio_fuera_del_rotulo_y_zocalo_corto() -> None:
    hard = DraftHardDataMention.model_fields
    chapter = DraftChapter.model_fields

    assert hard["time_reference"].description is not None
    assert "9 de enero" in hard["time_reference"].description
    assert "time_reference" in hard["indicator_label"].description
    assert "cifra literal" in hard["cue_index"].description
    assert "hard_data" in chapter["summary"].description
    assert str(MAX_LOWER_THIRD_LENGTH) in chapter["suggested_lower_third"].description
