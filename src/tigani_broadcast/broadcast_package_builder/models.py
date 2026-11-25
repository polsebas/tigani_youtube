"""Contratos Pydantic del módulo broadcast-package-builder (timeline, créditos, manifiesto)."""

from datetime import date
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

SlideKind = Literal["chapter_cover", "chart", "visual"]


class PackageSlide(BaseModel):
    """Una placa de la línea de tiempo del paquete OBS."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    slide_index: int = Field(ge=0)
    chapter_index: int = Field(ge=0)
    chapter_title: str = Field(min_length=1)
    cue_index: int = Field(ge=0)
    timestamp: str = Field(min_length=1)
    kind: SlideKind
    status: str = Field(min_length=1)
    title: str = Field(min_length=1)
    relative_html_path: str = Field(min_length=1)
    source_ref: str | None = None


class DataSourceCredit(BaseModel):
    """Crédito deduplicado de una serie de datos verificada."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    provider: str = Field(min_length=1)
    source_tier: str = Field(min_length=1)
    series_id: str = Field(min_length=1)
    source_attribution: str = Field(min_length=1)
    source_url: str = Field(min_length=1)


class VisualLicenseCredit(BaseModel):
    """Crédito deduplicado de una imagen con licencia segura para YouTube."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    provider: str = Field(min_length=1)
    author: str = Field(min_length=1)
    license_name: str = Field(min_length=1)
    license_code: str = Field(min_length=1)
    license_url: str | None = None
    source_page_url: str = Field(min_length=1)


class ExcludedErrorRecord(BaseModel):
    """Placa `fetch_error` excluida de la rotación al aire."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    chapter_index: int = Field(ge=0)
    cue_index: int = Field(ge=0)
    timestamp: str = Field(min_length=1)
    kind: Literal["chart", "visual"]
    title: str = Field(min_length=1)
    error_message: str = Field(min_length=1)


class BroadcastPackageManifest(BaseModel):
    """Manifiesto maestro del paquete portable para OBS y publicación."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    video_title: str = Field(min_length=1)
    video_url: str | None = None
    publish_date: date
    include_chapter_covers: bool = True
    include_errors: bool = False
    chapter_count: int = Field(ge=1)
    slides: list[PackageSlide]
    excluded_errors: list[ExcludedErrorRecord]
    data_sources: list[DataSourceCredit]
    visual_credits: list[VisualLicenseCredit]

    @model_validator(mode="after")
    def slides_are_sequential_and_relative(self) -> Self:
        for expected_index, slide in enumerate(self.slides):
            if slide.slide_index != expected_index:
                raise ValueError(
                    "slide_index tiene que ser secuencial 0..len(slides)-1; "
                    f"en posición {expected_index} llegó slide_index={slide.slide_index}"
                )
            if _is_absolute_path(slide.relative_html_path):
                raise ValueError(
                    f"relative_html_path no puede ser ruta absoluta: {slide.relative_html_path!r}"
                )
        return self


def _is_absolute_path(path: str) -> bool:
    candidate = Path(path)
    return candidate.is_absolute() or path.startswith(("/", "\\"))
