"""Contratos Pydantic del módulo official-data-charts (resolución, series, métricas, salida)."""

from datetime import date
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

SourceTier = Literal["official_primary", "market_secondary"]
ProviderId = Literal[
    "bcra",
    "indec",
    "datos_ar",
    "argentinadatos",
    "bcb",
    "fred",
    "ecb",
    "imf",
    "worldbank",
    "us_adrs",
]
Geography = Literal["AR", "BR", "US", "EU", "GLOBAL"]
ResolutionStatus = Literal["verified_series", "quoted_only", "fetch_error"]
SeriesFrequency = Literal["daily", "monthly", "quarterly", "annual"]


class CatalogEntry(BaseModel):
    """Indicador curado del catálogo cerrado. Solo estos IDs son resolubles a serie."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    catalog_id: str = Field(min_length=1, description="Identificador estable del indicador curado.")
    label: str = Field(min_length=1, description="Etiqueta periodística del indicador.")
    provider: ProviderId
    source_tier: SourceTier
    geography: Geography
    series_id: str = Field(
        min_length=1,
        description="ID de serie en la API del proveedor primario.",
    )
    frequency: SeriesFrequency
    unit: str = Field(
        min_length=1,
        description="Unidad publicada (millones USD, índice, %, etc.).",
    )
    description: str = Field(min_length=1)
    source_attribution: str = Field(
        min_length=1,
        description="Cita de fuente para placa HTML (incluye vía intermediario si aplica).",
    )
    fallback_provider: ProviderId | None = None
    fallback_series_id: str | None = None
    aliases: tuple[str, ...] = ()

    @model_validator(mode="after")
    def fallback_fields_come_together(self) -> Self:
        has_provider = self.fallback_provider is not None
        has_series = self.fallback_series_id is not None
        if has_provider != has_series:
            raise ValueError(
                "fallback_provider y fallback_series_id tienen que venir ambos o ninguno"
            )
        if self.fallback_series_id is not None and self.fallback_series_id.strip() == "":
            raise ValueError("fallback_series_id no puede ser vacío")
        return self


class SeriesObservation(BaseModel):
    """Un punto de la serie. `flag` conserva signos convencionales del INDEC."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    obs_date: date
    value: float | None
    flag: str | None = Field(
        default=None,
        description="Signo convencional INDEC u otro: *, **, e, ..., s, i.",
    )


class SeriesData(BaseModel):
    """Serie trazable ya bajada de un proveedor. Sin cálculos derivados."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    catalog_id: str = Field(min_length=1)
    provider: ProviderId
    source_tier: SourceTier
    series_id: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    source_attribution: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    frequency: SeriesFrequency
    observations: list[SeriesObservation]


class SeriesMetrics(BaseModel):
    """Resumen numérico calculado en Python determinista sobre observaciones válidas."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    observation_count: int = Field(ge=0)
    valid_count: int = Field(ge=0)
    start_date: date
    end_date: date
    first_value: float
    latest_value: float
    min_value: float
    min_date: date
    max_value: float
    max_date: date
    absolute_change: float | None
    percent_change: float | None
    has_provisional_flags: bool
    flags_present: list[str]


class ChartResolutionDraft(BaseModel):
    """Propuesta interna del agente (Corte 3). Sin fetch_error: eso lo asigna el pipeline."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    resolution_status: Literal["verified_series", "quoted_only"]
    catalog_id: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    rationale: str = Field(min_length=1, max_length=240)

    @model_validator(mode="after")
    def status_fields_are_consistent(self) -> Self:
        if self.resolution_status == "verified_series":
            if self.catalog_id is None or self.catalog_id.strip() == "":
                raise ValueError("verified_series exige catalog_id no vacío")
        elif self.resolution_status == "quoted_only":
            if self.catalog_id is not None:
                raise ValueError("quoted_only exige catalog_id None")
            if self.start_date is not None or self.end_date is not None:
                raise ValueError("quoted_only exige start_date y end_date None")

        if (
            self.start_date is not None
            and self.end_date is not None
            and self.start_date > self.end_date
        ):
            raise ValueError("start_date no puede ser mayor que end_date")
        return self


class ChartArtifact(BaseModel):
    """Una mención resuelta: serie verificada, cita textual o error de fetch puntual."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    chapter_index: int = Field(ge=0)
    cue_index: int = Field(ge=0)
    timestamp: str = Field(min_length=1)
    indicator_label: str = Field(min_length=1)
    raw_value_text: str = Field(min_length=1)
    time_reference: str | None = None
    resolution_status: ResolutionStatus
    rationale: str = Field(min_length=1)
    series: SeriesData | None = None
    metrics: SeriesMetrics | None = None
    error_message: str | None = None
    html_path: str | None = None

    @model_validator(mode="after")
    def status_payload_is_consistent(self) -> Self:
        status = self.resolution_status
        if status == "verified_series":
            if self.series is None or self.metrics is None:
                raise ValueError("verified_series exige series y metrics presentes")
            if self.error_message is not None:
                raise ValueError("verified_series exige error_message None")
        elif status == "quoted_only":
            if self.series is not None or self.metrics is not None:
                raise ValueError("quoted_only exige series y metrics None")
            if self.error_message is not None:
                raise ValueError("quoted_only exige error_message None")
        elif status == "fetch_error":
            if self.error_message is None or self.error_message.strip() == "":
                raise ValueError("fetch_error exige error_message no vacío")
            if self.series is not None or self.metrics is not None:
                raise ValueError("fetch_error exige series y metrics None")
        return self


class ChartsPackage(BaseModel):
    """Salida agregada del módulo: un artefacto por HardDataMention del video."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    publish_date: date
    source_chapters_path: str | None = None
    items: list[ChartArtifact]
