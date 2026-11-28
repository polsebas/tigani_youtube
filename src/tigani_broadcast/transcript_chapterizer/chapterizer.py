"""Segmentación con un motor inyectable. Agno 3.2.1 usa `output_schema`, no `response_model`."""

import re
import unicodedata
from collections.abc import Callable, Sequence
from typing import Protocol, TypeVar, runtime_checkable

from agno.agent import Agent
from agno.exceptions import OutputCheckError
from agno.models.base import Model
from agno.run.base import RunStatus
from agno.workflow import HumanReview, OnError, Step, StepInput, StepOutput, Workflow

from tigani_broadcast.transcript_chapterizer.guardrails import (
    CueGroundingGuardrail,
    LowerThirdLengthGuardrail,
    SpanishLanguageGuardrail,
    SummaryHardDataConsistencyGuardrail,
    TimeReferenceGuardrail,
    numeric_cue_indexes,
)
from tigani_broadcast.transcript_chapterizer.models import (
    Chapter,
    ChapterizedTranscript,
    Cue,
    DraftChapter,
    DraftChapterDetails,
    DraftChapterizedTranscript,
    DraftChapterPlan,
    DraftHardDataMention,
    DraftVisualSubjectMention,
    HardDataMention,
    VisualSubjectMention,
)
from tigani_broadcast.transcript_chapterizer.validate import (
    ChapterValidationError,
    validate_chapterized_transcript,
)

_PROMO_SIGNALS = (
    "nivel uno",
    "nivel dos",
    "unirte",
    "membresia",
    "comunidad",
    "microba",
    "iniciativa emprendedora",
    "macroeconomia facil",
    "entrenamientos",
)
_WORD_GAP = re.compile(r"\s+")


def _fold_text(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    without_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return _WORD_GAP.sub(" ", without_marks.casefold()).strip()


def is_promo_outro_text(text: str) -> bool:
    """True si hay al menos dos señales de cierre promocional del canal."""
    folded = _fold_text(text)
    hits = sum(1 for signal in _PROMO_SIGNALS if signal in folded)
    return hits >= 2


def promo_outro_details() -> DraftChapterDetails:
    """Detalle vacío: el cierre no cataloga clases, minutos ni niveles."""
    return DraftChapterDetails(
        summary="Cierre promocional del canal, sin cifras económicas.",
        suggested_lower_third="Sumate a la comunidad",
        hard_data=[],
        visual_subjects=[],
        chapter_kind="promo_outro",
    )


def _segment_text(cues: Sequence[Cue]) -> str:
    return " ".join(cue.text for cue in cues)


SEGMENTER_INSTRUCTIONS = "\n".join(
    (
        "Dividí la transcripción en bloques temáticos para un noticiero.",
        "Cada línea ya trae el índice global: `indice | [HH:MM:SS] texto`.",
        "Devolvé solo start_cue_index, end_cue_index y title.",
        "La partición es completa, ordenada y contigua: cubre el 100 % de las cues.",
        "El primer capítulo arranca en la cue 0, sin huecos ni solapes.",
        "Para un video de unos 5 minutos, proponé entre 2 y 5 capítulos.",
        "No fragmentes de más: un bloque junta un mismo tema.",
        "Redactá title en español claro, estilo noticiero.",
        "No extraigas cifras, zócalos ni sujetos visuales.",
    )
)

SEGMENTER_EXPECTED_OUTPUT = "\n".join(
    (
        "DraftChapterPlan con capítulos contiguos.",
        "Cada capítulo tiene start_cue_index, end_cue_index y title.",
        "Sin timestamps, sin hard_data y sin visual_subjects.",
    )
)

EXTRACTOR_INSTRUCTIONS = "\n".join(
    (
        "Describí solo el tramo de cues que recibís. Los índices son los globales.",
        "Respetá el signo de cada dato: si dijo reservas negativas, no las pongas como positivas.",
        "suggested_lower_third es un zócalo 16:9 de hasta 100 caracteres, fiel a este tramo.",
        "Prohibido el texto meta en el zócalo: nada de (sin fecha) ni N/A.",
        "No mezcles un monto de vencimiento con un monto colocado.",
        (
            "hard_data y visual_subjects son listas planas del tramo, "
            "referenciadas solo por cue_index."
        ),
        "No copies timestamps.",
        "Copiá literalmente lo dicho en raw_value_text.",
        "La cifra va en dígitos (45, 2.5%, 30,000), nunca en palabras: «cinco clases» no vale.",
        "indicator_label nombra la magnitud, sin el año.",
        "Si hay time_reference, es una expresión dicha en la cue. Si no hay, dejala en null.",
        "Incluí visual_subjects cuando haya actores, organismos o conceptos clave.",
        "Una intro o un cierre pueden llevar las listas vacías.",
        (
            "Si el tramo es el cierre promocional del canal (suscripción, membresías "
            '"Nivel 1" / "Nivel 2", cursos como MicroMBA, Iniciativa Emprendedora o '
            'Macroeconomía Fácil), poné chapter_kind="promo_outro".'
        ),
        (
            "Un promo_outro no lleva hard_data ni visual_subjects: ni cantidad de clases, "
            "ni minutos, ni niveles."
        ),
        'Si el tramo es editorial, chapter_kind="editorial".',
        (
            "summary, suggested_lower_third, indicator_label, subject_label y context_text "
            "van 100 % en español."
        ),
        "Prohibido redactar esos campos en inglés.",
        "Toda métrica económica (%, millones, reservas, tasas, montos) va en hard_data.",
        "Nunca vuelques una cifra económica como event_photo en visual_subjects.",
        "Redactá summary y suggested_lower_third en español claro, estilo noticiero.",
        "asset_kind es event_photo o conceptual_illustration. No es un dato oficial.",
        (
            "Ejemplo 1. La cue dice «8,000 de reservas netas» y «hoy»: "
            "indicator_label=reservas netas, raw_value_text=8,000, time_reference=hoy. "
            "El año no va en indicator_label."
        ),
        (
            "Ejemplo 2. La cue dice «2.5%» y «hoy»: "
            "indicator_label=índice de inflación, raw_value_text=2.5%, time_reference=hoy. "
            "cue_index es la cue de la cifra literal."
        ),
    )
)

EXTRACTOR_EXPECTED_OUTPUT = "\n".join(
    (
        "DraftChapterDetails del tramo, sin timestamps.",
        "summary respeta el signo de lo dicho.",
        "suggested_lower_third es un zócalo 16:9 de hasta 100 caracteres, sin texto meta.",
        "hard_data trae cue_index global, indicator_label sin el año y time_reference o null.",
        "visual_subjects trae actores, organismos o conceptos del tramo.",
    )
)

_DraftMention = TypeVar("_DraftMention", DraftHardDataMention, DraftVisualSubjectMention)
_PublicMention = TypeVar("_PublicMention")


class ChapterizerError(ValueError):
    """Fallo cerrado del chapterizer. No se repara la salida."""


class ChapterizerInputError(ChapterizerError):
    """La entrada no se puede capitular."""


class ChapterizerOutputError(ChapterizerError):
    """El workflow no devolvió el borrador o el contrato público esperados."""


@runtime_checkable
class ChapterizerEngine(Protocol):
    """Puerto del segmentador. Recibe las cues ya normalizadas."""

    def chapterize(self, cues: Sequence[Cue]) -> ChapterizedTranscript:
        """Devuelve el contrato público. `chapterize_transcript` lo vuelve a validar."""
        ...


def format_cue_lines(cues: Sequence[Cue]) -> str:
    """Líneas literales `indice | [HH:MM:SS] texto`, con el índice global."""
    return "\n".join(f"{cue.cue_index} | [{cue.timestamp}] {cue.text}" for cue in cues)


def format_chapterizer_input(cues: Sequence[Cue]) -> str:
    """Líneas literales más el pre-escaneo de cifras de este tramo."""
    body = format_cue_lines(cues)
    scan = f"Cues con cifras detectadas: {numeric_cue_indexes(cues)}"
    return f"{body}\n{scan}" if body else scan


def assemble_chapterized_transcript(
    draft: DraftChapterizedTranscript,
    cues: Sequence[Cue],
) -> ChapterizedTranscript:
    """Copia los relojes reales y ubica cada mención en el capítulo que contiene su cue."""
    if len(cues) == 0:
        raise ChapterValidationError("no hay cues para particionar")

    last = len(cues) - 1
    for position, chapter in enumerate(draft.chapters):
        _require_draft_bound(position, "start_cue_index", chapter.start_cue_index, last)
        _require_draft_bound(position, "end_cue_index", chapter.end_cue_index, last)
        if chapter.start_cue_index > chapter.end_cue_index:
            raise ChapterValidationError(
                f"capítulo {position}: start_cue_index no puede ser mayor que end_cue_index"
            )
    for mention in draft.hard_data:
        _require_draft_mention("hard_data", mention.cue_index, last)
    for mention in draft.visual_subjects:
        _require_draft_mention("visual_subjects", mention.cue_index, last)

    hard_data = _mentions_by_chapter(
        draft.chapters,
        _by_cue_index(draft.hard_data),
        "hard_data",
        lambda mention: _public_hard_data(mention, cues),
    )
    visual_subjects = _mentions_by_chapter(
        draft.chapters,
        _by_cue_index(draft.visual_subjects),
        "visual_subjects",
        lambda mention: _public_visual_subject(mention, cues),
    )
    transcript = ChapterizedTranscript(
        chapters=[
            Chapter(
                start_cue_index=chapter.start_cue_index,
                end_cue_index=chapter.end_cue_index,
                start_time=cues[chapter.start_cue_index].timestamp,
                end_time=cues[chapter.end_cue_index].timestamp,
                title=chapter.title,
                summary=chapter.summary,
                suggested_lower_third=chapter.suggested_lower_third,
                hard_data=hard_data[position],
                visual_subjects=visual_subjects[position],
                chapter_kind=chapter.chapter_kind,
            )
            for position, chapter in enumerate(draft.chapters)
        ]
    )
    return validate_chapterized_transcript(transcript, cues)


class AgnoChapterizer:
    """Workflow de dos pasos. El modelo llega inyectado; acá no se elige proveedor."""

    def __init__(self, model: Model) -> None:
        _set_temperature_zero(model)
        self._cues: tuple[Cue, ...] = ()
        self.extract_calls = 0
        self.grounding = CueGroundingGuardrail()
        self.time_reference = TimeReferenceGuardrail()
        self.lower_third = LowerThirdLengthGuardrail()
        self.summary_hard_data = SummaryHardDataConsistencyGuardrail()
        self.spanish = SpanishLanguageGuardrail()
        self.guardrails = (
            self.grounding,
            self.time_reference,
            self.lower_third,
            self.summary_hard_data,
            self.spanish,
        )
        self.segmenter = Agent(
            model=model,
            output_schema=DraftChapterPlan,
            instructions=SEGMENTER_INSTRUCTIONS,
            expected_output=SEGMENTER_EXPECTED_OUTPUT,
            markdown=False,
            telemetry=False,
        )
        self.extractor = Agent(
            model=model,
            output_schema=DraftChapterDetails,
            instructions=EXTRACTOR_INSTRUCTIONS,
            expected_output=EXTRACTOR_EXPECTED_OUTPUT,
            post_hooks=list(self.guardrails),
            markdown=False,
            telemetry=False,
        )
        self.workflow = Workflow(
            name="transcript-chapterizer",
            steps=[
                Step(
                    name="segmentar",
                    executor=self._segment,
                    max_retries=0,
                    human_review=HumanReview(on_error=OnError.fail),
                ),
                Step(
                    name="extraer",
                    executor=self._extract,
                    max_retries=0,
                    human_review=HumanReview(on_error=OnError.fail),
                ),
            ],
            telemetry=False,
        )

    def chapterize(self, cues: Sequence[Cue]) -> ChapterizedTranscript:
        """Segmenta, extrae cada capítulo aislado y devuelve el contrato público."""
        self._cues = tuple(cues)
        try:
            result = self.workflow.run(format_cue_lines(cues))
        except OutputCheckError as exc:
            raise ChapterValidationError(str(exc)) from exc
        if getattr(result, "status", None) == RunStatus.error:
            raise ChapterValidationError(_guardrail_failure_message(result, self.guardrails))
        content = result.content
        if isinstance(content, ChapterizedTranscript):
            return content
        received = type(content).__name__
        raise ChapterizerOutputError(
            f"el workflow no devolvió un ChapterizedTranscript (recibido: {received})"
        )

    def _segment(self, step_input: StepInput) -> StepOutput:
        del step_input
        content = _checked_content(self.segmenter, format_cue_lines(self._cues), ())
        if not isinstance(content, DraftChapterPlan):
            received = type(content).__name__
            raise ChapterizerOutputError(
                f"el agente no devolvió un DraftChapterPlan (recibido: {received})"
            )
        validate_chapter_plan(content, self._cues)
        return StepOutput(content=content)

    def _extract(self, step_input: StepInput) -> StepOutput:
        self.extract_calls += 1
        plan = step_input.previous_step_content
        if not isinstance(plan, DraftChapterPlan):
            received = type(plan).__name__
            raise ChapterizerOutputError(
                f"el paso 2 no recibió un DraftChapterPlan (recibido: {received})"
            )
        details: list[DraftChapterDetails] = []
        last_index = len(plan.chapters) - 1
        for position, boundary in enumerate(plan.chapters):
            segment = [
                cue
                for cue in self._cues
                if boundary.start_cue_index <= cue.cue_index <= boundary.end_cue_index
            ]
            if position == last_index and is_promo_outro_text(_segment_text(segment)):
                details.append(promo_outro_details())
                continue
            self.grounding.bind(
                self._cues,
                start=boundary.start_cue_index,
                end=boundary.end_cue_index,
            )
            content = _checked_content(
                self.extractor,
                format_chapterizer_input(segment),
                self.guardrails,
            )
            if not isinstance(content, DraftChapterDetails):
                received = type(content).__name__
                raise ChapterizerOutputError(
                    f"el agente no devolvió un DraftChapterDetails (recibido: {received})"
                )
            if content.chapter_kind == "promo_outro":
                content = content.model_copy(
                    update={"hard_data": [], "visual_subjects": [], "chapter_kind": "promo_outro"}
                )
            details.append(content)
        draft = _merge_plan(plan, details)
        return StepOutput(content=assemble_chapterized_transcript(draft, self._cues))


def chapterize_transcript(
    cues: Sequence[Cue],
    engine: ChapterizerEngine,
) -> ChapterizedTranscript:
    """Capitula y recién entonces acepta el paquete si coincide con las cues."""
    if len(cues) == 0:
        raise ChapterizerInputError("no hay cues para capitular")
    result = engine.chapterize(cues)
    return validate_chapterized_transcript(result, cues)


def _require_draft_bound(position: int, field_name: str, index: int, last: int) -> None:
    if index < 0 or index > last:
        raise ChapterValidationError(
            f"capítulo {position}: {field_name} {index} fuera de 0..{last}"
        )


def _require_draft_mention(field_name: str, index: int, last: int) -> None:
    if index < 0 or index > last:
        raise ChapterValidationError(f"{field_name} apunta a la cue {index}, fuera de 0..{last}")


def _owning_chapter(chapters: Sequence[DraftChapter], cue_index: int, field_name: str) -> int:
    owners = [
        position
        for position, chapter in enumerate(chapters)
        if chapter.start_cue_index <= cue_index <= chapter.end_cue_index
    ]
    if len(owners) == 1:
        return owners[0]
    if not owners:
        raise ChapterValidationError(
            f"{field_name} de la cue {cue_index} no cae en ningún capítulo"
        )
    raise ChapterValidationError(f"{field_name} de la cue {cue_index} cae en más de un capítulo")


def _by_cue_index(mentions: Sequence[_DraftMention]) -> list[_DraftMention]:
    ranked = sorted(enumerate(mentions), key=lambda item: (item[1].cue_index, item[0]))
    return [mention for _, mention in ranked]


def _mentions_by_chapter(
    chapters: Sequence[DraftChapter],
    mentions: Sequence[_DraftMention],
    field_name: str,
    publish: Callable[[_DraftMention], _PublicMention],
) -> list[list[_PublicMention]]:
    buckets: list[list] = [[] for _ in chapters]
    for mention in mentions:
        buckets[_owning_chapter(chapters, mention.cue_index, field_name)].append(publish(mention))
    return buckets


def _public_hard_data(mention: DraftHardDataMention, cues: Sequence[Cue]) -> HardDataMention:
    return HardDataMention(
        cue_index=mention.cue_index,
        timestamp=cues[mention.cue_index].timestamp,
        indicator_label=mention.indicator_label,
        raw_value_text=mention.raw_value_text,
        time_reference=mention.time_reference,
    )


def _public_visual_subject(
    mention: DraftVisualSubjectMention,
    cues: Sequence[Cue],
) -> VisualSubjectMention:
    return VisualSubjectMention(
        cue_index=mention.cue_index,
        timestamp=cues[mention.cue_index].timestamp,
        subject_label=mention.subject_label,
        asset_kind=mention.asset_kind,
        context_text=mention.context_text,
    )


def validate_chapter_plan(plan: DraftChapterPlan, cues: Sequence[Cue]) -> None:
    """Rechaza una partición incompleta antes de abrir el paso 2."""
    if len(cues) == 0:
        raise ChapterValidationError("no hay cues para particionar")
    last = len(cues) - 1
    previous_end: int | None = None
    for position, chapter in enumerate(plan.chapters):
        if chapter.start_cue_index > last or chapter.end_cue_index > last:
            raise ChapterValidationError(
                f"capítulo {position}: índice fuera de rango "
                f"({chapter.start_cue_index}..{chapter.end_cue_index}; última cue {last})"
            )
        if chapter.start_cue_index > chapter.end_cue_index:
            raise ChapterValidationError(
                f"capítulo {position}: start_cue_index no puede ser mayor que end_cue_index"
            )
        if previous_end is None:
            if chapter.start_cue_index != 0:
                raise ChapterValidationError("el primer capítulo tiene que arrancar en la cue 0")
        elif chapter.start_cue_index > previous_end + 1:
            raise ChapterValidationError(
                f"capítulo {position}: hay un hueco entre la cue {previous_end} "
                f"y la cue {chapter.start_cue_index}"
            )
        elif chapter.start_cue_index < previous_end + 1:
            raise ChapterValidationError(
                f"capítulo {position}: se solapa; arranca en la cue {chapter.start_cue_index} "
                f"y el anterior termina en la cue {previous_end}"
            )
        previous_end = chapter.end_cue_index
    if previous_end != last:
        raise ChapterValidationError(
            f"el último capítulo termina en la cue {previous_end}; "
            f"tiene que terminar en la cue {last}"
        )


def _checked_content(agent: object, prompt: str, guards: Sequence[object]) -> object:
    for guard in guards:
        if hasattr(guard, "failure"):
            guard.failure = None
    try:
        result = agent.run(prompt)  # type: ignore[attr-defined]
    except OutputCheckError as exc:
        raise ChapterValidationError(str(exc)) from exc
    if getattr(result, "status", None) == RunStatus.error:
        raise ChapterValidationError(_guardrail_failure_message(result, guards))
    if hasattr(result, "content"):
        return result.content
    return result


def _merge_plan(
    plan: DraftChapterPlan,
    details: Sequence[DraftChapterDetails],
) -> DraftChapterizedTranscript:
    return DraftChapterizedTranscript(
        chapters=[
            DraftChapter(
                start_cue_index=boundary.start_cue_index,
                end_cue_index=boundary.end_cue_index,
                title=boundary.title,
                summary=detail.summary,
                suggested_lower_third=detail.suggested_lower_third,
                chapter_kind=detail.chapter_kind,
            )
            for boundary, detail in zip(plan.chapters, details, strict=True)
        ],
        hard_data=[mention for detail in details for mention in detail.hard_data],
        visual_subjects=[mention for detail in details for mention in detail.visual_subjects],
    )


def _guardrail_failure_message(result: object, guards: Sequence[object]) -> str:
    for guard in guards:
        failure = getattr(guard, "failure", None)
        if isinstance(failure, str) and failure.strip():
            return failure
    content = getattr(result, "content", None)
    if isinstance(content, str) and content.strip():
        return content
    for event in getattr(result, "events", None) or []:
        text = getattr(event, "content", None)
        if isinstance(text, str) and text.strip():
            return text
    return "el guardrail rechazó la salida del agente"


def _set_temperature_zero(model: Model) -> None:
    """En Agno 3.2.1 `Agent` no recibe temperature. Se fija en el modelo."""
    if not hasattr(model, "temperature"):
        raise ChapterizerInputError("el modelo inyectado no permite fijar temperature=0.0")
    model.temperature = 0.0
