"""Segmentación con un motor inyectable. Agno 3.2.1 usa `output_schema`, no `response_model`."""

from collections.abc import Callable, Sequence
from typing import Protocol, TypeVar, runtime_checkable

from agno.agent import Agent
from agno.models.base import Model

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
from tigani_broadcast.transcript_chapterizer.validate import (
    ChapterValidationError,
    validate_chapterized_transcript,
)

CHAPTERIZER_INSTRUCTIONS = "\n".join(
    (
        "Segmentá la transcripción en capítulos para un noticiero.",
        "Cada línea de la entrada ya trae el índice: `indice | [HH:MM:SS] texto`.",
        "Proponé capítulos por rangos de cue_index: start_cue_index y end_cue_index.",
        "La partición es completa, ordenada y contigua: cubre el 100 % de las cues.",
        "El primer capítulo arranca en la cue 0, sin huecos ni solapes.",
        (
            "Las menciones van en dos listas planas, hard_data y visual_subjects, "
            "referenciadas solo por cue_index."
        ),
        "No anides menciones dentro de los capítulos y no copies timestamps.",
        "Prohibido inventar cifras, series históricas o timestamps.",
        "Copiá literalmente lo dicho en raw_value_text.",
        "Una intro o un cierre pueden llevar las listas de menciones vacías.",
        "Redactá title, summary y suggested_lower_third en español claro, estilo noticiero.",
        "Si hay time_reference, es una expresión dicha en la cue. No la vuelvas una fecha.",
        "asset_kind es event_photo o conceptual_illustration. No es un dato oficial.",
    )
)

_DraftMention = TypeVar("_DraftMention", DraftHardDataMention, DraftVisualSubjectMention)
_PublicMention = TypeVar("_PublicMention")


class ChapterizerError(ValueError):
    """Fallo cerrado del chapterizer. No se repara la salida."""


class ChapterizerInputError(ChapterizerError):
    """La entrada no se puede capitular."""


class ChapterizerOutputError(ChapterizerError):
    """El agente no devolvió un DraftChapterizedTranscript."""


@runtime_checkable
class ChapterizerEngine(Protocol):
    """Puerto del segmentador. Recibe las cues ya normalizadas."""

    def chapterize(self, cues: Sequence[Cue]) -> ChapterizedTranscript:
        """Devuelve el contrato público. `chapterize_transcript` lo vuelve a validar."""
        ...


def format_chapterizer_input(cues: Sequence[Cue]) -> str:
    """Arma el texto que ve el modelo, con índice y reloj ya resueltos."""
    return "\n".join(f"{cue.cue_index} | [{cue.timestamp}] {cue.text}" for cue in cues)


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
            )
            for position, chapter in enumerate(draft.chapters)
        ]
    )
    return validate_chapterized_transcript(transcript, cues)


class AgnoChapterizer:
    """Adaptador de Agno. El modelo llega inyectado; acá no se elige proveedor."""

    def __init__(self, model: Model) -> None:
        _set_temperature_zero(model)
        self.agent = Agent(
            model=model,
            output_schema=DraftChapterizedTranscript,
            instructions=CHAPTERIZER_INSTRUCTIONS,
            markdown=False,
            telemetry=False,
        )

    def chapterize(self, cues: Sequence[Cue]) -> ChapterizedTranscript:
        """Ensambla el borrador plano del agente y devuelve el contrato público."""
        result = self.agent.run(format_chapterizer_input(cues))
        content = result.content
        if isinstance(content, DraftChapterizedTranscript):
            return assemble_chapterized_transcript(content, cues)
        received = type(content).__name__
        raise ChapterizerOutputError(
            f"el agente no devolvió un DraftChapterizedTranscript (recibido: {received})"
        )


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


def _set_temperature_zero(model: Model) -> None:
    """En Agno 3.2.1 `Agent` no recibe temperature. Se fija en el modelo."""
    if not hasattr(model, "temperature"):
        raise ChapterizerInputError("el modelo inyectado no permite fijar temperature=0.0")
    model.temperature = 0.0
