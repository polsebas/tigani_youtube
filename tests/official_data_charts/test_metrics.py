"""Métricas deterministas: orden, flags INDEC, bordes y fail-closed."""

from datetime import date

import pytest

from tigani_broadcast.official_data_charts.metrics import (
    MetricsCalculationError,
    _value_date_key,
    compute_series_metrics,
)
from tigani_broadcast.official_data_charts.models import SeriesObservation


def test_compute_ordena_sin_mutar_y_calcula_cambios() -> None:
    original = [
        SeriesObservation(obs_date=date(2025, 1, 3), value=110.0),
        SeriesObservation(obs_date=date(2025, 1, 1), value=100.0),
        SeriesObservation(obs_date=date(2025, 1, 2), value=105.0),
    ]
    snapshot = list(original)

    metrics = compute_series_metrics(original)

    assert original == snapshot
    assert metrics.observation_count == 3
    assert metrics.valid_count == 3
    assert metrics.start_date == date(2025, 1, 1)
    assert metrics.end_date == date(2025, 1, 3)
    assert metrics.first_value == 100.0
    assert metrics.latest_value == 110.0
    assert metrics.min_value == 100.0
    assert metrics.min_date == date(2025, 1, 1)
    assert metrics.max_value == 110.0
    assert metrics.max_date == date(2025, 1, 3)
    assert metrics.absolute_change == 10.0
    assert metrics.percent_change == 10.0
    assert metrics.has_provisional_flags is False
    assert metrics.flags_present == []


def test_value_none_no_entra_al_calculo_pero_cuenta_en_observation_count() -> None:
    metrics = compute_series_metrics(
        [
            SeriesObservation(obs_date=date(2025, 2, 1), value=None, flag="..."),
            SeriesObservation(obs_date=date(2025, 2, 2), value=50.0),
            SeriesObservation(obs_date=date(2025, 2, 3), value=None, flag="s"),
            SeriesObservation(obs_date=date(2025, 2, 4), value=55.0, flag="*"),
        ]
    )
    assert metrics.observation_count == 4
    assert metrics.valid_count == 2
    assert metrics.first_value == 50.0
    assert metrics.latest_value == 55.0
    assert metrics.absolute_change == 5.0
    assert metrics.percent_change == 10.0
    assert metrics.flags_present == ["*", "...", "s"]
    assert metrics.has_provisional_flags is True


def test_un_solo_punto_valido_deja_cambios_en_none() -> None:
    metrics = compute_series_metrics(
        [SeriesObservation(obs_date=date(2025, 3, 1), value=2.5, flag="e")]
    )
    assert metrics.valid_count == 1
    assert metrics.absolute_change is None
    assert metrics.percent_change is None
    assert metrics.has_provisional_flags is True
    assert metrics.flags_present == ["e"]


def test_first_value_cero_deja_percent_change_none() -> None:
    metrics = compute_series_metrics(
        [
            SeriesObservation(obs_date=date(2025, 4, 1), value=0.0),
            SeriesObservation(obs_date=date(2025, 4, 2), value=10.0),
        ]
    )
    assert metrics.absolute_change == 10.0
    assert metrics.percent_change is None


def test_percent_change_con_first_negativo_usa_abs() -> None:
    metrics = compute_series_metrics(
        [
            SeriesObservation(obs_date=date(2025, 5, 1), value=-50.0),
            SeriesObservation(obs_date=date(2025, 5, 2), value=-40.0),
        ]
    )
    assert metrics.absolute_change == 10.0
    assert metrics.percent_change == 20.0


def test_signos_provisorios_indec() -> None:
    metrics = compute_series_metrics(
        [
            SeriesObservation(obs_date=date(2025, 6, 1), value=1.0, flag="**"),
            SeriesObservation(obs_date=date(2025, 6, 2), value=2.0, flag="i"),
            SeriesObservation(obs_date=date(2025, 6, 3), value=1.5, flag="*"),
        ]
    )
    assert metrics.flags_present == ["*", "**", "i"]
    assert metrics.has_provisional_flags is True
    assert metrics.min_value == 1.0
    assert metrics.max_value == 2.0


def test_sin_valores_validos_falla_cerrado() -> None:
    with pytest.raises(MetricsCalculationError, match="no hay observaciones"):
        compute_series_metrics([])
    with pytest.raises(MetricsCalculationError, match="no hay observaciones"):
        compute_series_metrics(
            [
                SeriesObservation(obs_date=date(2025, 7, 1), value=None, flag="s"),
                SeriesObservation(obs_date=date(2025, 7, 2), value=None),
            ]
        )


def test_value_date_key_rechaza_value_none() -> None:
    with pytest.raises(AssertionError, match="value numérico"):
        _value_date_key(SeriesObservation(obs_date=date(2025, 1, 1), value=None))


def test_empate_en_min_max_elige_fecha_mas_temprana() -> None:
    metrics = compute_series_metrics(
        [
            SeriesObservation(obs_date=date(2025, 8, 2), value=10.0),
            SeriesObservation(obs_date=date(2025, 8, 1), value=10.0),
            SeriesObservation(obs_date=date(2025, 8, 3), value=10.0),
        ]
    )
    assert metrics.min_date == date(2025, 8, 1)
    assert metrics.max_date == date(2025, 8, 1)
    assert metrics.absolute_change == 0.0
    assert metrics.percent_change == 0.0
