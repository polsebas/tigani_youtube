"""Contratos Pydantic del orquestador del pipeline (config, etapas, reporte)."""

from datetime import date
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from tigani_broadcast.visual_assets_fetcher.models import PortraitLayout

StageName = Literal["chapterizer", "charts", "visuals", "package"]
StageStatus = Literal["executed", "skipped", "failed"]


class PipelineConfig(BaseModel):
    """Configuración de una corrida del pipeline completo."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    transcript_path: Path
    publish_date: date
    video_title: str = Field(min_length=1)
    output_dir: Path
    video_url: str | None = None
    resume: bool = False
    rerender_only: bool = False
    no_llm_visuals: bool = False
    portrait_layout: PortraitLayout = "sidebar"
    include_chapter_covers: bool = True
    include_errors: bool = False
    cache_dir: Path | None = None
    outro_image: Path | None = None


class StageResult(BaseModel):
    """Resultado de una etapa del orquestador."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    stage: StageName
    status: StageStatus
    duration_seconds: float = Field(ge=0.0)
    output_path: str | None = None
    error_message: str | None = None

    @model_validator(mode="after")
    def status_error_is_consistent(self) -> Self:
        if self.status == "failed":
            if self.error_message is None or self.error_message.strip() == "":
                raise ValueError("failed exige error_message no vacío")
        elif self.error_message is not None:
            raise ValueError(f"{self.status} exige error_message None")
        return self


class PipelineReport(BaseModel):
    """Reporte agregado de una corrida (éxito o fail-fast)."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    transcript_path: str = Field(min_length=1)
    publish_date: date
    video_title: str = Field(min_length=1)
    output_dir: str = Field(min_length=1)
    resume: bool
    succeeded: bool
    total_duration_seconds: float = Field(ge=0.0)
    stages: list[StageResult]
    deck_html_path: str | None = None
    youtube_description_path: str | None = None
    social_post_path: str | None = None
