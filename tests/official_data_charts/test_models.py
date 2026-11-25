"""Contratos Pydantic: casos felices, bordes y rechazos fail-closed."""

from datetime import date

import pytest
from pydantic import ValidationError

from tigani_broadcast.official_data_charts.models import (
    CatalogEntry,
    ChartArtifact,
    ChartResolutionDraft,
    ChartsPackage,
    SeriesData,
    SeriesMetrics,
    SeriesObservation,
)


def _sample_series() -> SeriesData:
    return SeriesData(
        catalog_id="ar_bcra_reservas_brutas",
        provider="bcra",
        source_tier="official_primary",
        series_id="1",
        source_url="https://api.bcra.gob.ar/estadisticas/v4.0/Monetarias/1",
        source_attribution="Fuente: BCRA",
        unit="millones de USD",
        frequency="daily",
        observations=[
            SeriesObservation(obs_date=date(2025, 1, 2), value=20_000.0),
            SeriesObservation(obs_date=date(2025, 1, 3), value=21_000.0),
        ],
    )


def _sample_metrics() -> SeriesMetrics:
    return SeriesMetrics(
        observation_count=2,
        valid_count=2,
        start_date=date(2025, 1, 2),
        end_date=date(2025, 1, 3),
        first_value=20_000.0,
        latest_value=21_000.0,
        min_value=20_000.0,
        min_date=date(2025, 1, 2),
        max_value=21_000.0,
        max_date=date(2025, 1, 3),
        absolute_change=1_000.0,
        percent_change=5.0,
        has_provisional_flags=False,
        flags_present=[],
    )


def test_catalog_entry_acepta_sin_fallback() -> None:
    entry = CatalogEntry(
        catalog_id="ar_bcra_cer",
        label="CER",
        provider="bcra",
        source_tier="official_primary",
        geography="AR",
        series_id="30",
        frequency="daily",
        unit="índice",
        description="CER",
        source_attribution="Fuente: BCRA",
    )
    assert entry.fallback_provider is None
    assert entry.fallback_series_id is None
    assert entry.aliases == ()


def test_catalog_entry_acepta_fallback_completo() -> None:
    entry = CatalogEntry(
        catalog_id="ar_indec_ipc_mensual",
        label="IPC",
        provider="indec",
        source_tier="official_primary",
        geography="AR",
        series_id="ipc",
        frequency="monthly",
        unit="%",
        description="IPC",
        source_attribution="Fuente: INDEC",
        fallback_provider="datos_ar",
        fallback_series_id="ipc-datos",
        aliases=("inflación",),
    )
    assert entry.fallback_provider == "datos_ar"
    assert entry.fallback_series_id == "ipc-datos"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"fallback_provider": "datos_ar"},
        {"fallback_series_id": "ipc"},
    ],
)
def test_catalog_entry_rechaza_fallback_incompleto(kwargs: dict) -> None:
    base = {
        "catalog_id": "x",
        "label": "x",
        "provider": "indec",
        "source_tier": "official_primary",
        "geography": "AR",
        "series_id": "1",
        "frequency": "monthly",
        "unit": "%",
        "description": "x",
        "source_attribution": "INDEC",
    }
    with pytest.raises(ValidationError, match="fallback_provider y fallback_series_id"):
        CatalogEntry(**base, **kwargs)


def test_catalog_entry_rechaza_fallback_series_id_vacio() -> None:
    with pytest.raises(ValidationError, match="fallback_series_id no puede ser vacío"):
        CatalogEntry(
            catalog_id="x",
            label="x",
            provider="indec",
            source_tier="official_primary",
            geography="AR",
            series_id="1",
            frequency="monthly",
            unit="%",
            description="x",
            source_attribution="INDEC",
            fallback_provider="datos_ar",
            fallback_series_id="",
        )


def test_catalog_entry_rechaza_extra_y_provider_invalido() -> None:
    with pytest.raises(ValidationError, match="extra"):
        CatalogEntry.model_validate(
            {
                "catalog_id": "x",
                "label": "x",
                "provider": "bcra",
                "source_tier": "official_primary",
                "geography": "AR",
                "series_id": "1",
                "frequency": "daily",
                "unit": "u",
                "description": "x",
                "source_attribution": "BCRA",
                "inventado": True,
            }
        )
    with pytest.raises(ValidationError):
        CatalogEntry(
            catalog_id="x",
            label="x",
            provider="bloomberg",  # type: ignore[arg-type]
            source_tier="official_primary",
            geography="AR",
            series_id="1",
            frequency="daily",
            unit="u",
            description="x",
            source_attribution="x",
        )


def test_series_observation_acepta_flag_y_value_none() -> None:
    obs = SeriesObservation(obs_date=date(2025, 3, 1), value=None, flag="*")
    assert obs.value is None
    assert obs.flag == "*"


def test_chart_resolution_draft_verified_ok() -> None:
    draft = ChartResolutionDraft(
        resolution_status="verified_series",
        catalog_id="ar_indec_ipc_mensual",
        start_date=date(2024, 1, 1),
        end_date=date(2025, 1, 1),
        rationale="Coincide con IPC mensual del INDEC.",
    )
    assert draft.catalog_id == "ar_indec_ipc_mensual"


def test_chart_resolution_draft_quoted_only_ok() -> None:
    draft = ChartResolutionDraft(
        resolution_status="quoted_only",
        rationale="Monto puntual de colocación, sin serie en catálogo.",
    )
    assert draft.catalog_id is None
    assert draft.start_date is None


def test_chart_resolution_draft_verified_exige_catalog_id() -> None:
    with pytest.raises(ValidationError, match="verified_series exige catalog_id"):
        ChartResolutionDraft(
            resolution_status="verified_series",
            catalog_id=None,
            rationale="falta id",
        )
    with pytest.raises(ValidationError, match="verified_series exige catalog_id"):
        ChartResolutionDraft(
            resolution_status="verified_series",
            catalog_id="   ",
            rationale="id vacío",
        )


def test_chart_resolution_draft_quoted_only_rechaza_campos() -> None:
    with pytest.raises(ValidationError, match="quoted_only exige catalog_id None"):
        ChartResolutionDraft(
            resolution_status="quoted_only",
            catalog_id="ar_bcra_cer",
            rationale="no debería llevar id",
        )
    with pytest.raises(ValidationError, match="quoted_only exige start_date y end_date None"):
        ChartResolutionDraft(
            resolution_status="quoted_only",
            start_date=date(2025, 1, 1),
            rationale="no debería llevar fechas",
        )


def test_chart_resolution_draft_rechaza_fechas_invertidas() -> None:
    with pytest.raises(ValidationError, match="start_date no puede ser mayor"):
        ChartResolutionDraft(
            resolution_status="verified_series",
            catalog_id="ar_bcra_cer",
            start_date=date(2025, 6, 1),
            end_date=date(2025, 1, 1),
            rationale="rango invertido",
        )


def test_chart_artifact_verified_series_ok() -> None:
    artifact = ChartArtifact(
        chapter_index=0,
        cue_index=12,
        timestamp="00:01:20",
        indicator_label="reservas brutas",
        raw_value_text="20.000 millones",
        resolution_status="verified_series",
        rationale="Serie BCRA de reservas brutas.",
        series=_sample_series(),
        metrics=_sample_metrics(),
    )
    assert artifact.error_message is None
    assert artifact.html_path is None


def test_chart_artifact_quoted_only_ok() -> None:
    artifact = ChartArtifact(
        chapter_index=1,
        cue_index=20,
        timestamp="00:02:10",
        indicator_label="reservas netas",
        raw_value_text="negativas",
        time_reference="hoy",
        resolution_status="quoted_only",
        rationale="No hay serie de reservas netas en catálogo v0.",
    )
    assert artifact.series is None
    assert artifact.metrics is None


def test_chart_artifact_fetch_error_ok() -> None:
    artifact = ChartArtifact(
        chapter_index=0,
        cue_index=3,
        timestamp="00:00:40",
        indicator_label="IPC",
        raw_value_text="2,5%",
        resolution_status="fetch_error",
        rationale="Mapeado a INDEC pero falló la API.",
        error_message="timeout al consultar INDEC",
    )
    assert artifact.error_message == "timeout al consultar INDEC"


def test_chart_artifact_verified_rechaza_inconsistencias() -> None:
    with pytest.raises(ValidationError, match="verified_series exige series y metrics"):
        ChartArtifact(
            chapter_index=0,
            cue_index=0,
            timestamp="00:00:01",
            indicator_label="x",
            raw_value_text="1",
            resolution_status="verified_series",
            rationale="sin payload",
        )
    with pytest.raises(ValidationError, match="verified_series exige error_message None"):
        ChartArtifact(
            chapter_index=0,
            cue_index=0,
            timestamp="00:00:01",
            indicator_label="x",
            raw_value_text="1",
            resolution_status="verified_series",
            rationale="con error",
            series=_sample_series(),
            metrics=_sample_metrics(),
            error_message="no debería",
        )


def test_chart_artifact_quoted_only_rechaza_payload() -> None:
    with pytest.raises(ValidationError, match="quoted_only exige series y metrics None"):
        ChartArtifact(
            chapter_index=0,
            cue_index=0,
            timestamp="00:00:01",
            indicator_label="x",
            raw_value_text="1",
            resolution_status="quoted_only",
            rationale="con serie",
            series=_sample_series(),
        )
    with pytest.raises(ValidationError, match="quoted_only exige error_message None"):
        ChartArtifact(
            chapter_index=0,
            cue_index=0,
            timestamp="00:00:01",
            indicator_label="x",
            raw_value_text="1",
            resolution_status="quoted_only",
            rationale="con error",
            error_message="no",
        )


def test_chart_artifact_fetch_error_rechaza_inconsistencias() -> None:
    with pytest.raises(ValidationError, match="fetch_error exige error_message no vacío"):
        ChartArtifact(
            chapter_index=0,
            cue_index=0,
            timestamp="00:00:01",
            indicator_label="x",
            raw_value_text="1",
            resolution_status="fetch_error",
            rationale="sin mensaje",
        )
    with pytest.raises(ValidationError, match="fetch_error exige error_message no vacío"):
        ChartArtifact(
            chapter_index=0,
            cue_index=0,
            timestamp="00:00:01",
            indicator_label="x",
            raw_value_text="1",
            resolution_status="fetch_error",
            rationale="mensaje vacío",
            error_message="   ",
        )
    with pytest.raises(ValidationError, match="fetch_error exige series y metrics None"):
        ChartArtifact(
            chapter_index=0,
            cue_index=0,
            timestamp="00:00:01",
            indicator_label="x",
            raw_value_text="1",
            resolution_status="fetch_error",
            rationale="con serie",
            error_message="falló",
            series=_sample_series(),
        )


def test_charts_package_acepta_items_mixtos() -> None:
    package = ChartsPackage(
        publish_date=date(2025, 12, 11),
        source_chapters_path="out/video.chapters.json",
        items=[
            ChartArtifact(
                chapter_index=0,
                cue_index=1,
                timestamp="00:00:10",
                indicator_label="IPC",
                raw_value_text="2,5%",
                resolution_status="verified_series",
                rationale="INDEC",
                series=_sample_series(),
                metrics=_sample_metrics(),
            ),
            ChartArtifact(
                chapter_index=1,
                cue_index=5,
                timestamp="00:01:00",
                indicator_label="swap",
                raw_value_text="900 M",
                resolution_status="quoted_only",
                rationale="puntual",
            ),
        ],
    )
    assert len(package.items) == 2
    assert package.publish_date == date(2025, 12, 11)
