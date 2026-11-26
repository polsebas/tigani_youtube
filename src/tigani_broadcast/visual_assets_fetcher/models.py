"""Contratos Pydantic del módulo visual-assets-fetcher (dedup, plan, atribución, salida)."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

VisualProviderId = Literal["wikimedia", "openverse"]
AssetStatus = Literal["verified_asset", "fallback_card", "fetch_error"]
PortraitLayout = Literal["sidebar", "contain"]
AssetKind = Literal["event_photo", "conceptual_illustration"]


class DeduplicatedVisualSubject(BaseModel):
    """Sujeto visual único por capítulo tras colapsar repeticiones de etiqueta."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    chapter_index: int = Field(ge=0)
    cue_index: int = Field(ge=0)
    timestamp: str = Field(min_length=1)
    subject_label: str = Field(min_length=1)
    normalized_label: str = Field(min_length=1)
    asset_kind: AssetKind
    context_text: str = Field(min_length=1)
    occurrences_count: int = Field(ge=1)


class VisualQueryPlan(BaseModel):
    """Plan de búsqueda. Solo query + proveedor; nunca URLs ni licencias inventadas."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    search_query: str = Field(min_length=1, max_length=160)
    preferred_provider: VisualProviderId
    rationale: str = Field(min_length=1, max_length=240)


class VisualAttribution(BaseModel):
    """Crédito auditable de una imagen descargada con licencia en lista blanca."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    provider: VisualProviderId
    author: str = Field(min_length=1)
    license_name: str = Field(min_length=1)
    license_code: str = Field(min_length=1)
    license_url: str | None = None
    source_page_url: str = Field(min_length=1)
    image_url: str = Field(min_length=1)
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    mime_type: str = Field(min_length=1)


class VisualAssetArtifact(BaseModel):
    """Un sujeto resuelto: imagen verificada, placa de fallback o error de fetch puntual."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    chapter_index: int = Field(ge=0)
    cue_index: int = Field(ge=0)
    timestamp: str = Field(min_length=1)
    subject_label: str = Field(min_length=1)
    asset_kind: AssetKind
    context_text: str = Field(min_length=1)
    occurrences_count: int = Field(ge=1)
    search_query: str = Field(min_length=1)
    status: AssetStatus
    portrait_layout: PortraitLayout = "sidebar"
    attribution: VisualAttribution | None = None
    local_image_path: str | None = None
    html_path: str | None = None
    error_message: str | None = None

    @model_validator(mode="after")
    def status_payload_is_consistent(self) -> Self:
        status = self.status
        if status == "verified_asset":
            if self.attribution is None:
                raise ValueError("verified_asset exige attribution presente")
            if self.local_image_path is None or self.local_image_path.strip() == "":
                raise ValueError("verified_asset exige local_image_path no vacío")
            if self.error_message is not None:
                raise ValueError("verified_asset exige error_message None")
        elif status == "fallback_card":
            if self.attribution is not None:
                raise ValueError("fallback_card exige attribution None")
            if self.local_image_path is not None:
                raise ValueError("fallback_card exige local_image_path None")
            if self.error_message is not None:
                raise ValueError("fallback_card exige error_message None")
        elif status == "fetch_error":
            if self.error_message is None or self.error_message.strip() == "":
                raise ValueError("fetch_error exige error_message no vacío")
            if self.attribution is not None:
                raise ValueError("fetch_error exige attribution None")
            if self.local_image_path is not None:
                raise ValueError("fetch_error exige local_image_path None")
        return self


class VisualAssetsPackage(BaseModel):
    """Salida agregada del módulo: un artefacto por sujeto deduplicado del video."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    source_chapters_path: str | None = None
    portrait_layout: PortraitLayout = "sidebar"
    items: list[VisualAssetArtifact]
