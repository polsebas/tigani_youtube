"""Playbook v1: catálogo cerrado, base 100 determinista y matcher de respaldo."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from math import isclose

from pydantic import BaseModel, ConfigDict, Field

from tigani_broadcast.official_data_charts.guardrails import normalize_label
from tigani_broadcast.official_data_charts.models import (
    ChartNarrative,
    DataPoint,
    DeltaDirection,
    EditorialKpi,
    PlaybookChartType,
    PlaybookId,
)

_ZERO_EPS = 1e-12
_MONTHS_ES = (
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


class PlaybookChartSpec(BaseModel):
    """Definición cerrada de un gráfico estándar del playbook."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    playbook_id: PlaybookId
    title: str = Field(min_length=1, max_length=80)
    chart_type: PlaybookChartType
    series_keys: tuple[str, ...] = Field(min_length=1, max_length=2)
    default_window_months: int = Field(ge=6, le=60)
    fetch_window_months: int = Field(ge=6, le=60)
    editorial_note: str | None = Field(default=None, max_length=140)


def _spec(
    playbook_id: PlaybookId,
    title: str,
    chart_type: PlaybookChartType,
    series_keys: tuple[str, ...],
    *,
    window_months: int,
    fetch_months: int,
    editorial_note: str | None = None,
) -> PlaybookChartSpec:
    return PlaybookChartSpec(
        playbook_id=playbook_id,
        title=title,
        chart_type=chart_type,
        series_keys=series_keys,
        default_window_months=window_months,
        fetch_window_months=fetch_months,
        editorial_note=editorial_note,
    )


PLAYBOOK_CATALOG: dict[PlaybookId, PlaybookChartSpec] = {
    "ipc_trend": _spec(
        "ipc_trend",
        "Inflación mensual",
        "single_line",
        ("ar_indec_ipc_mensual",),
        window_months=12,
        fetch_months=13,
    ),
    "ipc_vs_dolar_base100": _spec(
        "ipc_vs_dolar_base100",
        "Inflación vs. dólar oficial (base 100)",
        "dual_base100",
        ("ar_indec_ipc_mensual", "ar_bcra_dolar_mayorista"),
        window_months=12,
        fetch_months=13,
        editorial_note="Índices re-indexados a Base 100 en el mes inicial de la ventana",
    ),
    "reservas_bcra_regimes": _spec(
        "reservas_bcra_regimes",
        "Reservas brutas BCRA",
        "single_line",
        ("ar_bcra_reservas_brutas",),
        window_months=48,
        fetch_months=48,
        editorial_note="Reservas internacionales brutas BCRA (incluye encajes y swap)",
    ),
    "emae_activity": _spec(
        "emae_activity",
        "Actividad económica (EMAE)",
        "bar_diverging",
        ("ar_indec_emae_mensual",),
        window_months=12,
        fetch_months=12,
    ),
    "riesgo_pais_trend": _spec(
        "riesgo_pais_trend",
        "Riesgo país",
        "single_line",
        ("ar_mkt_riesgo_pais",),
        window_months=12,
        fetch_months=12,
    ),
}

_MATCH_PRIORITY: tuple[PlaybookId, ...] = (
    "ipc_vs_dolar_base100",
    "reservas_bcra_regimes",
    "riesgo_pais_trend",
    "emae_activity",
    "ipc_trend",
)


def build_dual_base100(
    ipc_points: Sequence[DataPoint],
    fx_points: Sequence[DataPoint],
    *,
    publish_date: date,
    max_months: int = 12,
) -> tuple[list[DataPoint], list[DataPoint], ChartNarrative]:
    """
    Re-indexa IPC mensual compuesto y dólar oficial a base 100.

    Recorta a `<= publish_date`, agrega el dólar al último dato de cada mes,
    alinea por `YYYY-MM` y exige al menos 2 meses comunes.
    `idx[0] = 100`; cada mes siguiente compone la tasa de ese mes.
    `fx_idx[k] = fx[k] / fx[0] * 100`.
    """
    if max_months < 1:
        raise ValueError("max_months tiene que ser al menos 1")

    ipc_by_month = _monthly_last(_clip(ipc_points, publish_date))
    fx_by_month = _monthly_last(_clip(fx_points, publish_date))
    common = sorted(set(ipc_by_month) & set(fx_by_month))
    if len(common) < 2:
        raise ValueError(
            "hacen falta al menos 2 meses comunes entre IPC y dólar oficial "
            f"(hay {len(common)} con fecha <= {publish_date.isoformat()})"
        )
    window = common[-(max_months + 1) :]

    ipc_rates = [ipc_by_month[key] for key in window]
    fx_levels = [fx_by_month[key] for key in window]
    fx_base = fx_levels[0].value
    if isclose(fx_base, 0.0, abs_tol=_ZERO_EPS):
        raise ValueError("el dólar oficial del mes base es 0; no se puede re-indexar")

    ipc_index: list[DataPoint] = []
    fx_index: list[DataPoint] = []
    level = 100.0
    for index, (ipc_point, fx_point) in enumerate(zip(ipc_rates, fx_levels, strict=True)):
        if index > 0:
            level = level * (1.0 + ipc_point.value / 100.0)
        month_date = ipc_point.obs_date
        ipc_index.append(DataPoint(obs_date=month_date, value=level))
        fx_value = (fx_point.value / fx_base) * 100.0
        fx_index.append(DataPoint(obs_date=month_date, value=fx_value))

    if isclose(fx_index[-1].value, 0.0, abs_tol=_ZERO_EPS):
        raise ValueError("el índice de dólar oficial termina en 0; no se puede calcular la brecha")

    narrative = _dual_narrative(ipc_index, fx_index)
    return ipc_index, fx_index, narrative


def match_playbook_fallback(
    chapter_text: str,
    *,
    existing_series_keys: set[str],
    max_items: int = 2,
) -> list[PlaybookId]:
    """
    Respaldo determinista por palabras clave.

    Prioriza el gráfico más específico y corta en `max_items`.

    No repite un `single_line` / `bar_diverging` cuya serie primaria ya está en
    `existing_series_keys`. `ipc_vs_dolar_base100` se conserva aunque el IPC
    mensual ya se haya graficado: es el compuesto de atraso cambiario.
    """
    if max_items < 0:
        raise ValueError("max_items no puede ser negativo")
    blob = normalize_label(chapter_text)
    if not blob or max_items == 0:
        return []

    chosen: list[PlaybookId] = []
    for playbook_id in _MATCH_PRIORITY:
        if len(chosen) >= max_items:
            break
        if not _rule_matches(playbook_id, blob):
            continue
        spec = PLAYBOOK_CATALOG[playbook_id]
        primary = spec.series_keys[0]
        blocks_primary = playbook_id != "ipc_vs_dolar_base100" and spec.chart_type in {
            "single_line",
            "bar_diverging",
        }
        if blocks_primary and primary in existing_series_keys:
            continue
        chosen.append(playbook_id)
    return chosen


def _clip(points: Sequence[DataPoint], publish_date: date) -> list[DataPoint]:
    return [point for point in points if point.obs_date <= publish_date]


def _monthly_last(points: Sequence[DataPoint]) -> dict[str, DataPoint]:
    """Último dato de cada `YYYY-MM`. Si la serie ya es mensual, queda un punto."""
    buckets: dict[str, DataPoint] = {}
    for point in sorted(points, key=lambda item: item.obs_date):
        buckets[_month_key(point.obs_date)] = point
    return buckets


def _month_key(obs_date: date) -> str:
    return f"{obs_date.year:04d}-{obs_date.month:02d}"


def _rule_matches(playbook_id: PlaybookId, blob: str) -> bool:
    if playbook_id == "ipc_vs_dolar_base100":
        has_fx = "caro en dolares" in blob or "en dolares" in blob
        has_topic = any(
            token in blob
            for token in (
                "productos",
                "servicios",
                "precios",
                "atraso cambiario",
                "competitividad",
            )
        )
        return has_fx and has_topic
    if playbook_id == "reservas_bcra_regimes":
        return any(token in blob for token in ("reservas", "swap", "banco central"))
    if playbook_id == "riesgo_pais_trend":
        has_market = any(
            token in blob for token in ("riesgo pais", "embi", "bonos", "tasa de interes")
        )
        has_debt = any(token in blob for token in ("deuda", "vencimiento", "financiamiento"))
        return has_market and has_debt
    if playbook_id == "emae_activity":
        return any(token in blob for token in ("actividad economica", "emae", "recesion", "pbi"))
    return "inflacion" in blob or "ipc" in blob


def _dual_narrative(
    ipc_index: Sequence[DataPoint],
    fx_index: Sequence[DataPoint],
) -> ChartNarrative:
    ipc_change = ipc_index[-1].value - 100.0
    fx_change = fx_index[-1].value - 100.0
    gap = ((ipc_index[-1].value / fx_index[-1].value) - 1.0) * 100.0
    direction = _direction(gap)
    start = ipc_index[0].obs_date.isoformat()
    end = ipc_index[-1].obs_date.isoformat()
    window = f"{start}→{end}"
    return ChartNarrative(
        mode="trend_with_callout",
        headline_badge=_gap_badge(gap, direction),
        delta_direction=direction,
        anchor_date=ipc_index[-1].obs_date.isoformat(),
        anchor_label=_anchor_label(ipc_index[-1].obs_date),
        kpis=[
            EditorialKpi(
                label="IPC acumulado",
                formatted_value=_fmt_signed_pct(ipc_change),
                detail=window,
            ),
            EditorialKpi(
                label="Dólar oficial",
                formatted_value=_fmt_signed_pct(fx_change),
                detail=window,
            ),
            EditorialKpi(
                label="Brecha real",
                formatted_value=_fmt_signed_pct(gap),
                detail=window,
            ),
        ],
    )


def _direction(gap: float) -> DeltaDirection:
    rounded = round(gap, 1)
    if abs(rounded) < 0.05:
        return "flat"
    return "up" if rounded > 0 else "down"


def _gap_badge(gap: float, direction: DeltaDirection) -> str:
    formatted = _fmt_signed_pct(gap)
    if direction == "up":
        return f"▲ {formatted} IPC sobre dólar"
    if direction == "down":
        return f"▼ {formatted} dólar sobre IPC"
    return "= 0,0%"


def _fmt_signed_pct(value: float) -> str:
    rounded = round(value, 1)
    if abs(rounded) < 0.05:
        rounded = 0.0
    sign = "+" if rounded >= 0 else "-"
    body = f"{abs(rounded):.1f}".replace(".", ",")
    return f"{sign}{body}%"


def _anchor_label(obs_date: date) -> str:
    return f"{_MONTHS_ES[obs_date.month - 1]}-{obs_date.year}"
