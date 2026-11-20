"""Chapterizer offline. El doble de Agent no abre red ni gasta tokens."""

from collections.abc import Sequence
from types import SimpleNamespace

import pytest

from tigani_broadcast.transcript_chapterizer.chapterizer import (
    CHAPTERIZER_INSTRUCTIONS,
    AgnoChapterizer,
    ChapterizerEngine,
    ChapterizerInputError,
    ChapterizerOutputError,
    chapterize_transcript,
    format_chapterizer_input,
)
from tigani_broadcast.transcript_chapterizer.models import (
    Chapter,
    ChapterizedTranscript,
    Cue,
    DraftChapter,
    DraftChapterizedTranscript,
    DraftHardDataMention,
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
        )
    )


def test_agno_arma_el_agente_con_esquema_instrucciones_y_temperatura_cero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _AgentDoble.creados.clear()
    monkeypatch.setattr(
        "tigani_broadcast.transcript_chapterizer.chapterizer.Agent",
        _AgentDoble,
    )
    modelo = _Modelo(temperature=0.7)
    cues = _cues()
    borrador = DraftChapterizedTranscript(
        chapters=[
            DraftChapter(
                start_cue_index=0,
                end_cue_index=0,
                title="Intro",
                summary="Resumen de Intro.",
                suggested_lower_third="Intro",
            ),
            DraftChapter(
                start_cue_index=1,
                end_cue_index=1,
                title="La inflación",
                summary="Resumen de La inflación.",
                suggested_lower_third="La inflación",
            ),
            DraftChapter(
                start_cue_index=2,
                end_cue_index=2,
                title="Cierre",
                summary="Resumen de Cierre.",
                suggested_lower_third="Cierre",
            ),
        ],
        hard_data=[
            DraftHardDataMention(
                cue_index=1,
                indicator_label="inflación",
                raw_value_text="4,2 por ciento",
                time_reference="el dato leído",
            )
        ],
    )

    chapterizer = AgnoChapterizer(modelo)  # type: ignore[arg-type]
    agent = _AgentDoble.creados[-1]
    agent.content = borrador
    accepted = chapterize_transcript(cues, chapterizer)

    assert modelo.temperature == 0.0
    assert agent.kwargs["output_schema"] is DraftChapterizedTranscript
    assert agent.kwargs["instructions"] == CHAPTERIZER_INSTRUCTIONS
    assert agent.kwargs["markdown"] is False
    assert agent.kwargs["telemetry"] is False
    assert "temperature" not in agent.kwargs
    assert "sin huecos ni solapes" in CHAPTERIZER_INSTRUCTIONS
    assert "raw_value_text" in CHAPTERIZER_INSTRUCTIONS
    assert "estilo noticiero" in CHAPTERIZER_INSTRUCTIONS
    assert "listas planas" in CHAPTERIZER_INSTRUCTIONS
    assert "referenciadas solo por cue_index" in CHAPTERIZER_INSTRUCTIONS
    assert "no copies timestamps" in CHAPTERIZER_INSTRUCTIONS
    assert agent.prompts == [format_chapterizer_input(cues)]
    assert isinstance(accepted, ChapterizedTranscript)
    assert accepted.chapters[1].start_time == "00:00:14"
    assert accepted.chapters[1].end_time == "00:00:14"
    mention = accepted.chapters[1].hard_data[0]
    assert mention.cue_index == 1
    assert mention.timestamp == "00:00:14"
    assert mention.raw_value_text == "4,2 por ciento"
    assert accepted.chapters[0].hard_data == []
    assert accepted.chapters[2].visual_subjects == []


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
    _AgentDoble.creados[-1].content = content

    with pytest.raises(ChapterizerOutputError, match="no devolvió un DraftChapterizedTranscript"):
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
