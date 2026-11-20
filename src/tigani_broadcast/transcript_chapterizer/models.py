"""Cues normalizadas, contrato público de capítulos y propuesta plana del agente."""

import re
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_CLOCK = re.compile(r"^(?P<hours>\d{2,}):(?P<minutes>\d{2}):(?P<seconds>\d{2})$")


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

    start_cue_index: int = Field(ge=0)
    end_cue_index: int = Field(ge=0)
    title: str
    summary: str
    suggested_lower_third: str


class DraftHardDataMention(BaseModel):
    """Magnitud dicha en una cue. El timestamp lo copia el ensamblado."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    cue_index: int = Field(ge=0)
    indicator_label: str
    raw_value_text: str
    time_reference: str | None = None

    @field_validator("indicator_label", "raw_value_text")
    @classmethod
    def labels_have_content(cls, value: str) -> str:
        return _content(value)


class DraftVisualSubjectMention(BaseModel):
    """Sujeto ilustrable, referenciado solo por cue_index."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    cue_index: int = Field(ge=0)
    subject_label: str
    asset_kind: Literal["event_photo", "conceptual_illustration"]
    context_text: str

    @field_validator("subject_label", "context_text")
    @classmethod
    def labels_have_content(cls, value: str) -> str:
        return _content(value)


class DraftChapterizedTranscript(BaseModel):
    """Propuesta interna del agente. No es el contrato de chapters.json."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    chapters: list[DraftChapter] = Field(min_length=1)
    hard_data: list[DraftHardDataMention] = Field(default_factory=list)
    visual_subjects: list[DraftVisualSubjectMention] = Field(default_factory=list)
