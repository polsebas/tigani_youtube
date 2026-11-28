"""Cues normalizadas, contrato público de capítulos y propuesta plana del agente."""

import re
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_CLOCK = re.compile(r"^(?P<hours>\d{2,}):(?P<minutes>\d{2}):(?P<seconds>\d{2})$")

ChapterKind = Literal["editorial", "promo_outro"]


def canonical_timestamp(hours: int, minutes: int, seconds: int) -> str:
    """Arma `HH:MM:SS`. Las horas conservan su ancho a partir de dos dígitos."""
    if not 0 <= minutes <= 59 or not 0 <= seconds <= 59:
        raise ValueError(f"timestamp fuera de rango: {hours:02d}:{minutes:02d}:{seconds:02d}")
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _validated_timestamp(value: str) -> str:
    match = _CLOCK.fullmatch(value)
    if match is None:
        raise ValueError("el timestamp tiene que usar la forma HH:MM:SS")
    try:
        timestamp = canonical_timestamp(
            int(match.group("hours")),
            int(match.group("minutes")),
            int(match.group("seconds")),
        )
    except ValueError as exc:
        raise ValueError(f"timestamp fuera de rango: {value}") from exc
    if timestamp != value:
        raise ValueError("el timestamp tiene que usar la forma HH:MM:SS")
    return value


class Cue(BaseModel):
    """Una línea de la transcripción, con el reloj ya canónico y el texto limpio."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    cue_index: int = Field(ge=0)
    timestamp: str
    text: str

    @field_validator("timestamp")
    @classmethod
    def timestamp_is_canonical(cls, value: str) -> str:
        return _validated_timestamp(value)

    @field_validator("text")
    @classmethod
    def text_is_clean(cls, value: str) -> str:
        if value == "" or value != value.strip():
            raise ValueError("el texto de la cue tiene que ser limpio y no vacío")
        return value


def _content(value: str) -> str:
    if value.strip() == "":
        raise ValueError("tiene que tener contenido después de strip()")
    return value


def _blank_time_reference(value: object) -> object:
    if isinstance(value, str) and value.strip() == "":
        return None
    return value


class HardDataMention(BaseModel):
    """Magnitud dicha en una cue. `raw_value_text` se conserva tal como vino."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    cue_index: int = Field(ge=0)
    timestamp: str
    indicator_label: str
    raw_value_text: str
    time_reference: str | None = None

    @field_validator("timestamp")
    @classmethod
    def timestamp_is_canonical(cls, value: str) -> str:
        return _validated_timestamp(value)

    @field_validator("indicator_label", "raw_value_text")
    @classmethod
    def labels_have_content(cls, value: str) -> str:
        return _content(value)

    @field_validator("time_reference", mode="before")
    @classmethod
    def empty_time_reference_is_none(cls, value: object) -> object:
        return _blank_time_reference(value)


class VisualSubjectMention(BaseModel):
    """Sujeto o evento ilustrable. La foto y la ilustración conceptual no se mezclan."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    cue_index: int = Field(ge=0)
    timestamp: str
    subject_label: str
    asset_kind: Literal["event_photo", "conceptual_illustration"]
    context_text: str

    @field_validator("timestamp")
    @classmethod
    def timestamp_is_canonical(cls, value: str) -> str:
        return _validated_timestamp(value)

    @field_validator("subject_label", "context_text")
    @classmethod
    def labels_have_content(cls, value: str) -> str:
        return _content(value)


class Chapter(BaseModel):
    """Tramo de cues. Intro y outro pueden ir sin menciones."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    start_cue_index: int = Field(ge=0)
    end_cue_index: int = Field(ge=0)
    start_time: str
    end_time: str
    title: str
    summary: str
    suggested_lower_third: str
    hard_data: list[HardDataMention] = Field(default_factory=list)
    visual_subjects: list[VisualSubjectMention] = Field(default_factory=list)
    chapter_kind: ChapterKind = "editorial"

    @field_validator("start_time", "end_time")
    @classmethod
    def times_are_canonical(cls, value: str) -> str:
        return _validated_timestamp(value)

    @model_validator(mode="after")
    def cue_range_is_ordered(self) -> Self:
        if self.start_cue_index > self.end_cue_index:
            raise ValueError("start_cue_index no puede ser mayor que end_cue_index")
        return self


class ChapterizedTranscript(BaseModel):
    """Capítulos propuestos. Las cues de origen se validan aparte."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    chapters: list[Chapter] = Field(min_length=1)


class DraftChapter(BaseModel):
    """Rango de cues que propone el agente. Sin reloj y sin menciones adentro."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    start_cue_index: int = Field(ge=0, description="Primera cue del capítulo, inclusive.")
    end_cue_index: int = Field(ge=0, description="Última cue del capítulo, inclusive.")
    title: str = Field(description="Título breve del capítulo, en español de noticiero.")
    summary: str = Field(
        description=(
            "Resumen fiel a lo dicho. Toda cifra relevante que aparezca acá "
            "tiene que estar también en hard_data."
        )
    )
    suggested_lower_third: str = Field(
        description=(
            "Zócalo 16:9 para OBS, máximo 100 caracteres, fiel a lo dicho. "
            "No mezclar un monto de vencimiento con un monto colocado."
        )
    )
    chapter_kind: ChapterKind = "editorial"


class DraftHardDataMention(BaseModel):
    """Magnitud dicha en una cue. El timestamp lo copia el ensamblado."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    cue_index: int = Field(
        ge=0,
        description="Índice exacto de la cue donde aparece la cifra literal de raw_value_text.",
    )
    indicator_label: str = Field(
        description=(
            "Nombre de la magnitud, sin el año. Un año de cuatro dígitos va en time_reference, "
            "nunca acá con time_reference vacío."
        )
    )
    raw_value_text: str = Field(
        description="Cifra literal dicha en esa cue, sin reescribir separadores ni unidades."
    )
    time_reference: str | None = Field(
        default=None,
        description=(
            "Referencia temporal explícita dicha en la cue: hoy, 2015, último mes, "
            "9 de enero, enero 2018. No la conviertas en una fecha de calendario."
        ),
    )

    @field_validator("indicator_label", "raw_value_text")
    @classmethod
    def labels_have_content(cls, value: str) -> str:
        return _content(value)

    @field_validator("time_reference", mode="before")
    @classmethod
    def empty_time_reference_is_none(cls, value: object) -> object:
        return _blank_time_reference(value)


class DraftVisualSubjectMention(BaseModel):
    """Sujeto ilustrable, referenciado solo por cue_index."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    cue_index: int = Field(ge=0, description="Índice de la cue donde se nombra el sujeto.")
    subject_label: str = Field(description="Sujeto o evento ilustrable, como se lo nombró.")
    asset_kind: Literal["event_photo", "conceptual_illustration"] = Field(
        description="event_photo o conceptual_illustration. No es un dato oficial."
    )
    context_text: str = Field(description="Contexto breve dicho en la cue, sin inventar la escena.")

    @field_validator("subject_label", "context_text")
    @classmethod
    def labels_have_content(cls, value: str) -> str:
        return _content(value)


class DraftChapterizedTranscript(BaseModel):
    """Propuesta interna del agente. No es el contrato de chapters.json."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    chapters: list[DraftChapter] = Field(
        min_length=1,
        description="Rangos de cue_index. Sin timestamps y sin menciones adentro.",
    )
    hard_data: list[DraftHardDataMention] = Field(
        default_factory=list,
        description="Lista plana de cifras. Cada cue_index apunta a la cue de la cifra literal.",
    )
    visual_subjects: list[DraftVisualSubjectMention] = Field(
        default_factory=list,
        description="Lista plana de sujetos ilustrables, referenciada solo por cue_index.",
    )


class DraftChapterBoundary(BaseModel):
    """Frontera del paso 1. Solo rango y título, sin cifras ni zócalo."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    start_cue_index: int = Field(
        ge=0,
        description="Primera cue del bloque, inclusive. El primer bloque arranca en 0.",
    )
    end_cue_index: int = Field(
        ge=0,
        description="Última cue del bloque, inclusive. El siguiente bloque arranca en end + 1.",
    )
    title: str = Field(description="Título breve del bloque temático, en español de noticiero.")


class DraftChapterPlan(BaseModel):
    """Partición del paso 1. Python la rechaza si no cubre todas las cues."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    chapters: list[DraftChapterBoundary] = Field(
        min_length=1,
        description=(
            "Bloques temáticos contiguos. En un video de unos 5 minutos, entre 2 y 5 capítulos."
        ),
    )


class DraftChapterDetails(BaseModel):
    """Detalle del paso 2. Solo ve las cues de su capítulo."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    summary: str = Field(
        description=(
            "Resumen fiel al tramo, respetando el signo de cada cifra. "
            "Si dijo reservas negativas, no las escribas como positivas."
        )
    )
    suggested_lower_third: str = Field(
        description=(
            "Zócalo 16:9 para OBS, máximo 100 caracteres, fiel a lo dicho en este tramo. "
            "Sin texto meta: nada de (sin fecha), N/A ni aclaraciones entre paréntesis."
        )
    )
    hard_data: list[DraftHardDataMention] = Field(
        default_factory=list,
        description=(
            "Cifras dichas en este tramo. cue_index global, indicator_label específico "
            "y time_reference real, o null si no hubo marca temporal."
        ),
    )
    chapter_kind: ChapterKind = "editorial"
    visual_subjects: list[DraftVisualSubjectMention] = Field(
        default_factory=list,
        description=(
            "Actores, organismos o conceptos clave de este tramo. Lista vacía si no hay sujeto."
        ),
    )
