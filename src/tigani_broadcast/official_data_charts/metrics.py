"""Cálculo determinista de métricas de serie. Cero participación del LLM."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from tigani_broadcast.official_data_charts.models import SeriesMetrics, SeriesObservation

# Signos convencionales tratados como provisorios / estimados (INDEC y afines).
_PROVISIONAL_FLAGS: frozenset[str] = frozenset({"*", "**", "e", "i"})


class MetricsCalculationError(ValueError):
    """No hay observaciones numéricas válidas para calcular métricas."""


def _value_date_key(obs: SeriesObservation) -> tuple[float, date]:
    value = obs.value
    if value is None:
        raise AssertionError("solo observaciones con value numérico")
    return (value, obs.obs_date)


def _max_value_earliest_date_key(obs: SeriesObservation) -> tuple[float, int]:
    """En empate de valor, `max` elige la fecha más temprana (ordinal negado)."""
    value, obs_date = _value_date_key(obs)
    return (value, -obs_date.toordinal())


def compute_series_metrics(observations: Sequence[SeriesObservation]) -> SeriesMetrics:
    """
    Resume una serie ordenando por fecha sin mutar la entrada.

    - `observation_count` cuenta todos los puntos recibidos.
    - El cálculo numérico usa solo observaciones con `value is not None`.
    - Si no hay ningún valor válido, falla cerrado con `MetricsCalculationError`.
    - Con un solo punto válido, `absolute_change` y `percent_change` quedan en `None`.
    - Si `first_value == 0`, `percent_change` queda en `None` (división por cero).
    - Los valores crudos de las observaciones no se redondean; el redondeo de
      presentación queda para la capa de render (HTML/Markdown).
    """
    ordered = sorted(observations, key=lambda obs: obs.obs_date)
    flags_present = sorted({obs.flag for obs in ordered if obs.flag is not None})
    has_provisional = any(flag in _PROVISIONAL_FLAGS for flag in flags_present)

    valid = [obs for obs in ordered if obs.value is not None]
    if not valid:
        raise MetricsCalculationError(
            "no hay observaciones con value numérico para calcular métricas"
        )

    first = valid[0]
    latest = valid[-1]
    min_obs = min(valid, key=_value_date_key)
    max_obs = max(valid, key=_max_value_earliest_date_key)

    first_value, _ = _value_date_key(first)
    latest_value, _ = _value_date_key(latest)
    min_value, min_date = _value_date_key(min_obs)
    max_value, max_date = _value_date_key(max_obs)

    absolute_change: float | None
    percent_change: float | None
    if len(valid) >= 2:
        absolute_change = latest_value - first_value
        if first_value == 0:
            percent_change = None
        else:
            percent_change = ((latest_value - first_value) / abs(first_value)) * 100.0
    else:
        absolute_change = None
        percent_change = None

    return SeriesMetrics(
        observation_count=len(ordered),
        valid_count=len(valid),
        start_date=first.obs_date,
        end_date=latest.obs_date,
        first_value=first_value,
        latest_value=latest_value,
        min_value=min_value,
        min_date=min_date,
        max_value=max_value,
        max_date=max_date,
        absolute_change=absolute_change,
        percent_change=percent_change,
        has_provisional_flags=has_provisional,
        flags_present=flags_present,
    )
