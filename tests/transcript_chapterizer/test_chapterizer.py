"""Chapterizer offline. El doble de Agent no abre red ni gasta tokens."""

from collections.abc import Sequence
from types import SimpleNamespace

import pytest
from agno.exceptions import CheckTrigger, OutputCheckError
from agno.run.base import RunStatus

from tigani_broadcast.transcript_chapterizer.chapterizer import (
    EXTRACTOR_EXPECTED_OUTPUT,
    EXTRACTOR_INSTRUCTIONS,
    SEGMENTER_EXPECTED_OUTPUT,
    SEGMENTER_INSTRUCTIONS,
    AgnoChapterizer,
    ChapterizerEngine,
    ChapterizerInputError,
    ChapterizerOutputError,
    assemble_chapterized_transcript,
    chapterize_transcript,
    format_chapterizer_input,
    format_cue_lines,
    is_promo_outro_text,
    promo_outro_details,
    validate_chapter_plan,
)
from tigani_broadcast.transcript_chapterizer.guardrails import (
    CueGroundingGuardrail,
    LowerThirdLengthGuardrail,
    SpanishLanguageGuardrail,
    SummaryHardDataConsistencyGuardrail,
    TimeReferenceGuardrail,
)
from tigani_broadcast.transcript_chapterizer.models import (
    Chapter,
    ChapterizedTranscript,
    Cue,
    DraftChapter,
    DraftChapterBoundary,
    DraftChapterDetails,
    DraftChapterizedTranscript,
    DraftChapterPlan,
    DraftHardDataMention,
    DraftVisualSubjectMention,
    HardDataMention,
)
from tigani_broadcast.transcript_chapterizer.validate import ChapterValidationError

_FILAS = [
    (0, "00:00:01", "Buen día, arranca el programa."),
    (1, "00:00:14", "El índice fue del  4,2 por ciento."),
    (2, "00:01:03", "Gracias y nos vemos."),
]


class _Modelo:
    def __init__(self, temperature: float = 0.7) -> None:
        self.temperature = temperature


class _AgentDoble:
    creados: list["_AgentDoble"] = []

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.prompts: list[str] = []
        self.content: object = None
        self.post_hooks = kwargs.get("post_hooks")
        _AgentDoble.creados.append(self)

    def run(self, prompt: str, **kwargs: object) -> SimpleNamespace:
        self.prompts.append(prompt)
        return SimpleNamespace(content=self.content)


class _Motor:
    def __init__(self, result: ChapterizedTranscript) -> None:
        self.result = result
        self.llamadas: list[Sequence[Cue]] = []

    def chapterize(self, cues: Sequence[Cue]) -> ChapterizedTranscript:
        self.llamadas.append(cues)
        return self.result


def _cues() -> list[Cue]:
    return [Cue(cue_index=index, timestamp=stamp, text=text) for index, stamp, text in _FILAS]


def _chapter(
    cues: list[Cue],
    start: int,
    end: int,
    *,
    title: str,
    hard_data: list[HardDataMention] | None = None,
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
    )


def _paquete_valido(cues: list[Cue]) -> ChapterizedTranscript:
    return ChapterizedTranscript(
        chapters=[
            _chapter(cues, 0, 0, title="Intro"),
            _chapter(
                cues,
                1,
                1,
                title="La inflación",
                hard_data=[
                    HardDataMention(
                        cue_index=1,
                        timestamp="00:00:14",
                        indicator_label="inflación",
                        raw_value_text="4,2 por ciento",
                        time_reference="el dato leído",
                    )
                ],
            ),
            _chapter(cues, 2, 2, title="Cierre"),
        ]
    )


def test_caso_feliz_con_motor_fake() -> None:
    cues = _cues()
    paquete = _paquete_valido(cues)
    motor = _Motor(paquete)

    accepted = chapterize_transcript(cues, motor)

    assert isinstance(motor, ChapterizerEngine)
    assert accepted is paquete
    assert len(motor.llamadas) == 1
    assert motor.llamadas[0][1].text == "El índice fue del  4,2 por ciento."
    assert accepted.chapters[0].hard_data == []
    assert accepted.chapters[2].visual_subjects == []


def test_rechaza_cues_vacias_sin_llamar_al_motor() -> None:
    class _NoDebeCorrer:
        def chapterize(self, cues: Sequence[Cue]) -> ChapterizedTranscript:
            raise AssertionError(cues)

    with pytest.raises(ChapterizerInputError, match="no hay cues para capitular"):
        chapterize_transcript([], _NoDebeCorrer())


def test_propaga_hueco_del_motor() -> None:
    cues = _cues()
    roto = ChapterizedTranscript(
        chapters=[
            _chapter(cues, 0, 0, title="Intro"),
            _chapter(cues, 2, 2, title="Saltea la del medio"),
        ]
    )

    with pytest.raises(ChapterValidationError, match="hay un hueco"):
        chapterize_transcript(cues, _Motor(roto))


def test_propaga_timestamp_alterado() -> None:
    cues = _cues()
    paquete = _paquete_valido(cues)
    chapters = list(paquete.chapters)
    chapters[1] = chapters[1].model_copy(update={"start_time": "09:09:09"})
    roto = paquete.model_copy(update={"chapters": chapters})

    with pytest.raises(ChapterValidationError, match="start_time 09:09:09"):
        chapterize_transcript(cues, _Motor(roto))


def test_propaga_mencion_fuera_de_rango() -> None:
    cues = _cues()
    paquete = _paquete_valido(cues)
    mention = HardDataMention(
        cue_index=2,
        timestamp="00:01:03",
        indicator_label="cierre",
        raw_value_text="Gracias",
    )
    chapters = list(paquete.chapters)
    chapters[0] = chapters[0].model_copy(update={"hard_data": [mention]})
    roto = paquete.model_copy(update={"chapters": chapters})

    with pytest.raises(ChapterValidationError, match="hard_data apunta a la cue 2, fuera de 0..0"):
        chapterize_transcript(cues, _Motor(roto))


def test_el_prompt_trae_indice_reloj_y_texto_literal() -> None:
    prompt = format_chapterizer_input(_cues())

    assert prompt == "\n".join(
        (
            "0 | [00:00:01] Buen día, arranca el programa.",
            "1 | [00:00:14] El índice fue del  4,2 por ciento.",
            "2 | [00:01:03] Gracias y nos vemos.",
            "Cues con cifras detectadas: [1]",
        )
    )


def _plan_de_dos_bloques() -> DraftChapterPlan:
    return DraftChapterPlan(
        chapters=[
            DraftChapterBoundary(start_cue_index=0, end_cue_index=1, title="La inflación"),
            DraftChapterBoundary(start_cue_index=2, end_cue_index=2, title="Cierre"),
        ]
    )


def _detalle(
    summary: str,
    lower: str,
    mentions: list[DraftHardDataMention] | None = None,
    visuals: list[DraftVisualSubjectMention] | None = None,
) -> DraftChapterDetails:
    return DraftChapterDetails(
        summary=summary,
        suggested_lower_third=lower,
        hard_data=mentions or [],
        visual_subjects=visuals or [],
    )


def test_el_workflow_de_dos_pasos_aisla_cada_capitulo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _AgentDoble.creados.clear()
    monkeypatch.setattr(
        "tigani_broadcast.transcript_chapterizer.chapterizer.Agent",
        _AgentDoble,
    )
    modelo = _Modelo(temperature=0.7)
    cues = _cues()
    chapterizer = AgnoChapterizer(modelo)  # type: ignore[arg-type]
    segmenter, extractor = _AgentDoble.creados
    segmenter.content = _plan_de_dos_bloques()
    extractor.content = None
    detalles = [
        _detalle(
            "El índice fue del 4,2 por ciento.",
            "Inflación: 4,2 por ciento",
            [
                DraftHardDataMention(
                    cue_index=1,
                    indicator_label="inflación",
                    raw_value_text="4,2 por ciento",
                    time_reference="el dato leído",
                )
            ],
            [
                DraftVisualSubjectMention(
                    cue_index=1,
                    subject_label="índice",
                    asset_kind="conceptual_illustration",
                    context_text="el dato leído",
                )
            ],
        ),
        _detalle("Cierra el programa.", "Cierre"),
    ]

    def _run(prompt: str, **kwargs: object) -> SimpleNamespace:
        extractor.prompts.append(prompt)
        return SimpleNamespace(content=detalles.pop(0))

    extractor.run = _run  # type: ignore[method-assign]
    accepted = chapterize_transcript(cues, chapterizer)

    assert modelo.temperature == 0.0
    assert segmenter.kwargs["output_schema"] is DraftChapterPlan
    assert segmenter.kwargs["instructions"] == SEGMENTER_INSTRUCTIONS
    assert segmenter.kwargs["expected_output"] == SEGMENTER_EXPECTED_OUTPUT
    assert "post_hooks" not in segmenter.kwargs
    assert "entre 2 y 5 capítulos" in SEGMENTER_INSTRUCTIONS
    assert extractor.kwargs["output_schema"] is DraftChapterDetails
    assert extractor.kwargs["instructions"] == EXTRACTOR_INSTRUCTIONS
    assert extractor.kwargs["expected_output"] == EXTRACTOR_EXPECTED_OUTPUT
    assert isinstance(extractor.kwargs["post_hooks"][0], CueGroundingGuardrail)
    assert isinstance(extractor.kwargs["post_hooks"][1], TimeReferenceGuardrail)
    assert isinstance(extractor.kwargs["post_hooks"][2], LowerThirdLengthGuardrail)
    assert isinstance(extractor.kwargs["post_hooks"][3], SummaryHardDataConsistencyGuardrail)
    assert isinstance(extractor.kwargs["post_hooks"][4], SpanishLanguageGuardrail)
    assert "100 % en español" in EXTRACTOR_INSTRUCTIONS
    assert "event_photo" in EXTRACTOR_INSTRUCTIONS
    assert extractor.kwargs["markdown"] is False
    assert extractor.kwargs["telemetry"] is False
    assert "temperature" not in extractor.kwargs
    assert "negativas" in EXTRACTOR_INSTRUCTIONS
    assert "(sin fecha)" in EXTRACTOR_INSTRUCTIONS
    assert "raw_value_text" in EXTRACTOR_INSTRUCTIONS
    assert "Ejemplo 1" in EXTRACTOR_INSTRUCTIONS
    assert segmenter.prompts == [format_cue_lines(cues)]
    assert "Cues con cifras detectadas" not in segmenter.prompts[0]
    assert extractor.prompts[0] == format_chapterizer_input(cues[:2])
    assert "Gracias y nos vemos." not in extractor.prompts[0]
    assert extractor.prompts[1] == format_chapterizer_input(cues[2:])
    assert "4,2 por ciento" not in extractor.prompts[1]
    assert chapterizer.grounding.start == 2
    assert chapterizer.grounding.end == 2
    assert chapterizer.extract_calls == 1
    assert isinstance(accepted, ChapterizedTranscript)
    assert accepted.chapters[0].start_time == "00:00:01"
    assert accepted.chapters[0].end_time == "00:00:14"
    mention = accepted.chapters[0].hard_data[0]
    assert mention.cue_index == 1
    assert mention.timestamp == "00:00:14"
    assert mention.raw_value_text == "4,2 por ciento"
    assert accepted.chapters[0].visual_subjects[0].timestamp == "00:00:14"
    assert accepted.chapters[1].hard_data == []
    assert accepted.chapters[1].start_time == "00:01:03"


@pytest.mark.parametrize("content", [None, "texto suelto", {"chapters": []}])
def test_agno_falla_si_el_contenido_no_es_el_esquema(
    monkeypatch: pytest.MonkeyPatch,
    content: object,
) -> None:
    _AgentDoble.creados.clear()
    monkeypatch.setattr(
        "tigani_broadcast.transcript_chapterizer.chapterizer.Agent",
        _AgentDoble,
    )
    chapterizer = AgnoChapterizer(_Modelo())  # type: ignore[arg-type]
    _AgentDoble.creados[0].content = content

    with pytest.raises(ChapterizerOutputError, match="no devolvió un DraftChapterPlan"):
        chapterizer.chapterize(_cues())


@pytest.mark.parametrize(
    ("chapters", "match"),
    [
        (
            [DraftChapterBoundary(start_cue_index=0, end_cue_index=0, title="Intro")],
            "tiene que terminar en la cue 2",
        ),
        (
            [
                DraftChapterBoundary(start_cue_index=0, end_cue_index=0, title="Intro"),
                DraftChapterBoundary(start_cue_index=2, end_cue_index=2, title="Saltea"),
            ],
            "hay un hueco",
        ),
        (
            [
                DraftChapterBoundary(start_cue_index=0, end_cue_index=1, title="Se come"),
                DraftChapterBoundary(start_cue_index=1, end_cue_index=2, title="Repite"),
            ],
            "se solapa",
        ),
        (
            [DraftChapterBoundary(start_cue_index=0, end_cue_index=9, title="Desborda")],
            "índice fuera de rango",
        ),
        (
            [DraftChapterBoundary(start_cue_index=2, end_cue_index=1, title="Invertido")],
            "no puede ser mayor",
        ),
        (
            [DraftChapterBoundary(start_cue_index=1, end_cue_index=2, title="Sin cero")],
            "cue 0",
        ),
    ],
)
def test_un_plan_invalido_no_invoca_el_paso_2(
    monkeypatch: pytest.MonkeyPatch,
    chapters: list[DraftChapterBoundary],
    match: str,
) -> None:
    _AgentDoble.creados.clear()
    monkeypatch.setattr(
        "tigani_broadcast.transcript_chapterizer.chapterizer.Agent",
        _AgentDoble,
    )
    chapterizer = AgnoChapterizer(_Modelo())  # type: ignore[arg-type]
    segmenter, extractor = _AgentDoble.creados
    segmenter.content = DraftChapterPlan(chapters=chapters)

    with pytest.raises(ChapterValidationError, match=match):
        chapterizer.chapterize(_cues())

    assert extractor.prompts == []
    assert chapterizer.extract_calls == 0


def test_el_paso_2_rechaza_un_detalle_invalido(monkeypatch: pytest.MonkeyPatch) -> None:
    _AgentDoble.creados.clear()
    monkeypatch.setattr(
        "tigani_broadcast.transcript_chapterizer.chapterizer.Agent",
        _AgentDoble,
    )
    chapterizer = AgnoChapterizer(_Modelo())  # type: ignore[arg-type]
    segmenter, extractor = _AgentDoble.creados
    segmenter.content = DraftChapterPlan(
        chapters=[DraftChapterBoundary(start_cue_index=0, end_cue_index=2, title="Todo")]
    )
    extractor.content = "texto suelto"

    with pytest.raises(ChapterizerOutputError, match="no devolvió un DraftChapterDetails"):
        chapterizer.chapterize(_cues())


def test_un_plan_sin_cues_no_se_valida() -> None:
    plan = DraftChapterPlan(
        chapters=[DraftChapterBoundary(start_cue_index=0, end_cue_index=0, title="Vacío")]
    )

    with pytest.raises(ChapterValidationError, match="no hay cues para particionar"):
        validate_chapter_plan(plan, [])


def test_agno_traduce_output_check_error_sin_ensamblar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _AgentDoble.creados.clear()

    class _Falla(OutputCheckError):
        pass

    class _AgentQueRevienta(_AgentDoble):
        def run(self, prompt: str, **kwargs: object) -> SimpleNamespace:
            raise _Falla("la cifra no aparece", check_trigger=CheckTrigger.VALIDATION_FAILED)

    monkeypatch.setattr(
        "tigani_broadcast.transcript_chapterizer.chapterizer.Agent",
        _AgentQueRevienta,
    )

    with pytest.raises(ChapterValidationError, match="la cifra no aparece"):
        AgnoChapterizer(_Modelo()).chapterize(_cues())  # type: ignore[arg-type]


def test_agno_traduce_run_status_error_sin_ensamblar(monkeypatch: pytest.MonkeyPatch) -> None:
    _AgentDoble.creados.clear()
    monkeypatch.setattr(
        "tigani_broadcast.transcript_chapterizer.chapterizer.Agent",
        _AgentDoble,
    )
    chapterizer = AgnoChapterizer(_Modelo())  # type: ignore[arg-type]
    segmenter, extractor = _AgentDoble.creados
    segmenter.content = DraftChapterPlan(
        chapters=[DraftChapterBoundary(start_cue_index=0, end_cue_index=2, title="Todo")]
    )

    def _run(prompt: str, **kwargs: object) -> SimpleNamespace:
        extractor.prompts.append(prompt)
        extractor.kwargs["post_hooks"][0].failure = "la cifra no aparece en la ventana ±1"
        return SimpleNamespace(status=RunStatus.error, content=_detalle("Resumen.", "Zócalo"))

    extractor.run = _run  # type: ignore[method-assign]

    with pytest.raises(ChapterValidationError, match="ventana ±1"):
        chapterizer.chapterize(_cues())


def test_agno_lee_el_mensaje_de_error_si_el_guardrail_no_lo_dejo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _AgentDoble.creados.clear()

    class _AgentConTexto(_AgentDoble):
        def run(self, prompt: str, **kwargs: object) -> SimpleNamespace:
            return SimpleNamespace(status=RunStatus.error, content="zócalo demasiado largo")

    monkeypatch.setattr(
        "tigani_broadcast.transcript_chapterizer.chapterizer.Agent",
        _AgentConTexto,
    )

    with pytest.raises(ChapterValidationError, match="zócalo demasiado largo"):
        AgnoChapterizer(_Modelo()).chapterize(_cues())  # type: ignore[arg-type]


def test_agno_lee_el_evento_de_error_o_un_mensaje_generico(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _AgentDoble.creados.clear()
    respuestas = [
        SimpleNamespace(
            status=RunStatus.error,
            content=None,
            events=[SimpleNamespace(content="   "), SimpleNamespace(content="desde el evento")],
        ),
        SimpleNamespace(status=RunStatus.error, content=None, events=[]),
    ]

    class _AgentConEvento(_AgentDoble):
        def run(self, prompt: str, **kwargs: object) -> SimpleNamespace:
            return respuestas.pop(0)

    monkeypatch.setattr(
        "tigani_broadcast.transcript_chapterizer.chapterizer.Agent",
        _AgentConEvento,
    )
    chapterizer = AgnoChapterizer(_Modelo())  # type: ignore[arg-type]

    with pytest.raises(ChapterValidationError, match="desde el evento"):
        chapterizer.chapterize(_cues())
    with pytest.raises(ChapterValidationError, match="rechazó la salida del agente"):
        chapterizer.chapterize(_cues())


def test_agno_rechaza_un_modelo_sin_temperature(monkeypatch: pytest.MonkeyPatch) -> None:
    _AgentDoble.creados.clear()
    monkeypatch.setattr(
        "tigani_broadcast.transcript_chapterizer.chapterizer.Agent",
        _AgentDoble,
    )

    class _SinTemperatura:
        pass

    with pytest.raises(ChapterizerInputError, match="temperature=0.0"):
        AgnoChapterizer(_SinTemperatura())  # type: ignore[arg-type]

    assert _AgentDoble.creados == []


def test_el_modulo_no_importa_sdks_de_proveedores() -> None:
    import sys

    import tigani_broadcast.transcript_chapterizer.chapterizer  # noqa: F401

    prefixes = ("openai", "anthropic")
    offenders = [
        name
        for name in sys.modules
        if name in prefixes or name.startswith(tuple(f"{prefix}." for prefix in prefixes))
    ]
    assert offenders == []


def test_detector_de_promo_outro_vacia_menciones() -> None:
    texto = (
        "Si todavía no estás en el nivel uno, sumate a la comunidad. "
        "Unirte al nivel dos incluye MicroMBA e Iniciativa Emprendedora."
    )
    assert is_promo_outro_text(texto) is True
    assert is_promo_outro_text("la inflación fue 2,5 por ciento") is False
    assert promo_outro_details().hard_data == []
    assert promo_outro_details().visual_subjects == []
    assert promo_outro_details().chapter_kind == "promo_outro"

    cues = [
        Cue(cue_index=0, timestamp="00:11:15", text="nivel uno y la comunidad"),
        Cue(cue_index=1, timestamp="00:11:52", text="cinco clases de entre 45 minutos"),
    ]
    draft = DraftChapterizedTranscript(
        chapters=[
            DraftChapter(
                start_cue_index=0,
                end_cue_index=1,
                title="Cierre",
                summary="Cierre promocional del canal, sin cifras económicas.",
                suggested_lower_third="Sumate a la comunidad",
                chapter_kind="promo_outro",
            )
        ],
        hard_data=[
            DraftHardDataMention(
                cue_index=1,
                indicator_label="clases",
                raw_value_text="5",
            )
        ],
        visual_subjects=[
            DraftVisualSubjectMention(
                cue_index=0,
                subject_label="comunidad",
                asset_kind="conceptual_illustration",
                context_text="nivel uno",
            )
        ],
    )
    # El ensamblado respeta lo que ya vació el detector: este draft ya viene limpio.
    limpio = draft.model_copy(update={"hard_data": [], "visual_subjects": []})
    transcript = assemble_chapterized_transcript(limpio, cues)
    assert transcript.chapters[0].chapter_kind == "promo_outro"
    assert transcript.chapters[0].hard_data == []
    assert transcript.chapters[0].visual_subjects == []
