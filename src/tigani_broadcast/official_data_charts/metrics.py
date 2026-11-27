"""Cálculo determinista de métricas de serie y narrativa editorial. Cero LLM."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta
from math import isclose, prod

from tigani_broadcast.official_data_charts.models import (
    ChartNarrative,
    DeltaDirection,
    EditorialKpi,
    NarrativeMode,
    SeriesMetrics,
    SeriesObservation,
)
from tigani_broadcast.official_data_charts.regimes import resolve_regime_bands

# Signos convencionales tratados como provisorios / estimados (INDEC y afines).
_PROVISIONAL_FLAGS: frozenset[str] = frozenset({"*", "**", "e", "i"})
_FLAT_EPS = 1e-9
_YOY_MIN_DAYS = 330
_YOY_MAX_DAYS = 395
_MAX_KPIS = 3


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


def build_chart_narrative(
    points: Sequence[SeriesObservation],
    *,
    unit: str,
    frequency: str,
    mode: NarrativeMode,
    publish_date: date,
    scope: str,
    is_monthly_pct_change: bool = False,
) -> ChartNarrative:
    """
    Construye la narrativa editorial determinista (badge + KPIs + bandas).

    Recorta a `<= publish_date`, ancla en el último punto válido y nunca inventa
    ni interpola valores. Sin divisiones por cero.
    """
    del frequency  # reservado para ventanas por modo en Corte 2
    valid = _valid_points_on_or_before(points, publish_date)
    if not valid:
        raise MetricsCalculationError(
            "no hay observaciones con value numérico <= publish_date para narrativa"
        )

    anchor = valid[-1]
    anchor_value = _require_value(anchor)
    prior = valid[-2] if len(valid) >= 2 else None

    use_pp = _uses_percentage_points(is_monthly_pct_change=is_monthly_pct_change, unit=unit)
    headline_badge, delta_direction = _delta_badge(
        anchor_value=anchor_value,
        prior_value=_require_value(prior) if prior is not None else None,
        use_pp=use_pp,
    )

    kpis = _build_kpis(
        valid,
        anchor=anchor,
        prior=prior,
        is_monthly_pct_change=is_monthly_pct_change,
        use_pp=use_pp,
        unit=unit,
    )

    window_start = valid[0].obs_date
    window_end = anchor.obs_date
    regime_bands = resolve_regime_bands(
        window_start,
        window_end,
        publish_date=publish_date,
        scope=scope,
        include_single=False,
    )

    return ChartNarrative(
        mode=mode,
        headline_badge=headline_badge,
        delta_direction=delta_direction,
        anchor_date=anchor.obs_date.isoformat(),
        anchor_label=_anchor_label(anchor.obs_date),
        kpis=kpis,
        regime_bands=regime_bands,
    )


def _valid_points_on_or_before(
    points: Sequence[SeriesObservation],
    publish_date: date,
) -> list[SeriesObservation]:
    clipped = [obs for obs in points if obs.value is not None and obs.obs_date <= publish_date]
    return sorted(clipped, key=lambda obs: obs.obs_date)


def _require_value(obs: SeriesObservation) -> float:
    value = obs.value
    if value is None:
        raise AssertionError("punto narrativo sin value")
    return value


def _uses_percentage_points(*, is_monthly_pct_change: bool, unit: str) -> bool:
    if is_monthly_pct_change:
        return True
    normalized = unit.strip().casefold()
    return normalized in {"%", "p.p.", "pp", "puntos porcentuales"} or "tasa" in normalized


def _delta_badge(
    *,
    anchor_value: float,
    prior_value: float | None,
    use_pp: bool,
) -> tuple[str | None, DeltaDirection | None]:
    if prior_value is None:
        return None, None

    if use_pp:
        delta = anchor_value - prior_value
        direction = _direction_from_delta(delta)
        arrow = _arrow(direction)
        return f"{arrow} {_fmt_signed(delta)} p.p. vs. mes ant.", direction

    if isclose(prior_value, 0.0, abs_tol=_FLAT_EPS):
        return None, None

    pct = ((anchor_value - prior_value) / abs(prior_value)) * 100.0
    direction = _direction_from_delta(pct)
    arrow = _arrow(direction)
    return f"{arrow} {_fmt_signed(pct)} % vs. dato ant.", direction


def _direction_from_delta(delta: float) -> DeltaDirection:
    if abs(delta) < _FLAT_EPS:
        return "flat"
    return "up" if delta > 0 else "down"


def _arrow(direction: DeltaDirection) -> str:
    if direction == "up":
        return "▲"
    if direction == "down":
        return "▼"
    return "="


def _build_kpis(
    valid: Sequence[SeriesObservation],
    *,
    anchor: SeriesObservation,
    prior: SeriesObservation | None,
    is_monthly_pct_change: bool,
    use_pp: bool,
    unit: str,
) -> list[EditorialKpi]:
    del use_pp
    kpis: list[EditorialKpi] = []
    seen_values: list[float] = []
    level_unit = unit if unit.strip() == "%" else ""

    if prior is not None:
        prior_value = _require_value(prior)
        kpis.append(
            EditorialKpi(
                label="Período anterior",
                formatted_value=_fmt_value(prior_value, unit=level_unit),
                detail=prior.obs_date.isoformat(),
            )
        )
        seen_values.append(prior_value)

    ytd = _ytd_kpi(valid, anchor=anchor, is_monthly_pct_change=is_monthly_pct_change)
    yoy = _yoy_kpi(valid, anchor=anchor, is_monthly_pct_change=is_monthly_pct_change)

    # Anti-redundancia diciembre: YTD e interanual 12m no se duplican.
    if ytd is not None and yoy is not None and isclose(ytd[0], yoy[0], abs_tol=_FLAT_EPS):
        yoy = None

    if ytd is not None:
        value, detail = ytd
        if not _value_already_shown(value, seen_values):
            kpis.append(
                EditorialKpi(
                    label="Acum. año (YTD)",
                    formatted_value=_fmt_pct(value),
                    detail=detail,
                )
            )
            seen_values.append(value)

    if yoy is not None and len(kpis) < _MAX_KPIS:
        value, detail = yoy
        if not _value_already_shown(value, seen_values):
            kpis.append(
                EditorialKpi(
                    label="Interanual (12m)",
                    formatted_value=_fmt_pct(value),
                    detail=detail,
                )
            )
            seen_values.append(value)

    _fill_period_kpis(kpis, valid, seen_values=seen_values, unit=level_unit)
    return kpis[:_MAX_KPIS]


def _ytd_kpi(
    valid: Sequence[SeriesObservation],
    *,
    anchor: SeriesObservation,
    is_monthly_pct_change: bool,
) -> tuple[float, str] | None:
    anchor_value = _require_value(anchor)
    year_points = [obs for obs in valid if obs.obs_date.year == anchor.obs_date.year]

    if is_monthly_pct_change:
        # Enero / un solo mes: no duplicar el dato mensual como YTD.
        if len(year_points) < 2:
            return None
        rates = [_require_value(obs) for obs in year_points]
        composed = _geometric_composition(rates)
        return composed, f"{year_points[0].obs_date.isoformat()}→{anchor.obs_date.isoformat()}"

    prior_year = [obs for obs in valid if obs.obs_date.year == anchor.obs_date.year - 1]
    if not prior_year:
        return None
    base = _require_value(prior_year[-1])
    if isclose(base, 0.0, abs_tol=_FLAT_EPS):
        return None
    pct = ((anchor_value - base) / abs(base)) * 100.0
    return pct, f"vs {prior_year[-1].obs_date.isoformat()}"


def _yoy_kpi(
    valid: Sequence[SeriesObservation],
    *,
    anchor: SeriesObservation,
    is_monthly_pct_change: bool,
) -> tuple[float, str] | None:
    if is_monthly_pct_change:
        if len(valid) < 12:
            return None
        window = list(valid[-12:])
        if len(window) != 12:
            return None
        rates = [_require_value(obs) for obs in window]
        composed = _geometric_composition(rates)
        return composed, f"{window[0].obs_date.isoformat()}→{anchor.obs_date.isoformat()}"

    base_obs = _find_yoy_base(valid, anchor.obs_date)
    if base_obs is None:
        return None
    base = _require_value(base_obs)
    if isclose(base, 0.0, abs_tol=_FLAT_EPS):
        return None
    anchor_value = _require_value(anchor)
    pct = ((anchor_value - base) / abs(base)) * 100.0
    return pct, f"vs {base_obs.obs_date.isoformat()}"


def _find_yoy_base(
    valid: Sequence[SeriesObservation],
    anchor_date: date,
) -> SeriesObservation | None:
    target = anchor_date - timedelta(days=365)
    candidates = [
        obs
        for obs in valid
        if obs.obs_date < anchor_date
        and _YOY_MIN_DAYS <= (anchor_date - obs.obs_date).days <= _YOY_MAX_DAYS
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda obs: abs((obs.obs_date - target).days))


def _fill_period_kpis(
    kpis: list[EditorialKpi],
    valid: Sequence[SeriesObservation],
    *,
    seen_values: list[float],
    unit: str = "",
) -> None:
    if len(kpis) >= _MAX_KPIS or not valid:
        return

    values = [_require_value(obs) for obs in valid]
    min_value = min(values)
    max_value = max(values)

    if len(kpis) < _MAX_KPIS and not _value_already_shown(max_value, seen_values):
        kpis.append(
            EditorialKpi(
                label="Máx. del período",
                formatted_value=_fmt_value(max_value, unit=unit),
                detail=None,
            )
        )
        seen_values.append(max_value)

    if len(kpis) < _MAX_KPIS:
        rango = f"{_fmt_value(min_value, unit=unit)} – {_fmt_value(max_value, unit=unit)}"
        if len(rango) <= 40:
            kpis.append(
                EditorialKpi(
                    label="Rango del período",
                    formatted_value=rango,
                    detail=None,
                )
            )


def _geometric_composition(rates_pct: Sequence[float]) -> float:
    factors = [(1.0 + rate / 100.0) for rate in rates_pct]
    return (prod(factors) - 1.0) * 100.0


def _value_already_shown(value: float, seen: Sequence[float]) -> bool:
    return any(isclose(value, other, abs_tol=_FLAT_EPS) for other in seen)


def _anchor_label(obs_date: date) -> str:
    months = (
        "ene",
        "feb",
        "mar",
        "abr",
        "may",
        "jun",
        "jul",
        "ago",
        "sep",
        "oct",
        "nov",
        "dic",
    )
    return f"{months[obs_date.month - 1]}-{obs_date.year}"


def _fmt_signed(value: float) -> str:
    body = _fmt_number(abs(value))
    if abs(value) < _FLAT_EPS:
        return f"+{body}"
    sign = "+" if value > 0 else "−"
    return f"{sign}{body}"


def _fmt_pct(value: float) -> str:
    return f"{_fmt_signed(value)} %"


def _fmt_value(value: float, *, unit: str = "") -> str:
    body = _fmt_number(value)
    if unit.strip() == "%":
        return f"{body}%"
    return body


def _fmt_number(value: float) -> str:
    """Formato argentino corto: coma decimal, sin notación científica."""
    if isclose(value, round(value), abs_tol=_FLAT_EPS):
        as_int = int(round(value))
        if abs(as_int) >= 1000:
            return f"{as_int:,}".replace(",", ".")
        return str(as_int)
    text = f"{value:.1f}"
    return text.replace(".", ",")
