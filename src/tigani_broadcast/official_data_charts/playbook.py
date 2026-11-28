"""Playbook v1: catálogo cerrado, base 100 determinista y matcher de respaldo."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from math import isclose
from typing import Literal

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
_SeriesMode = Literal["percent_change", "level"]
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
    "brecha_cambiaria": _spec(
        "brecha_cambiaria",
        "Brecha cambiaria",
        "dual_spread",
        ("ar_bcra_dolar_mayorista", "ar_mkt_dolar_blue"),
        window_months=12,
        fetch_months=12,
        editorial_note=(
            "Brecha % entre el dólar blue (ArgentinaDatos, Tier 2) y el mayorista A 3500 (BCRA)."
        ),
    ),
    "salarios_vs_ipc_base100": _spec(
        "salarios_vs_ipc_base100",
        "Salarios vs. inflación (base 100)",
        "dual_base100",
        ("ar_indec_salarios_indice", "ar_indec_ipc_mensual"),
        window_months=12,
        fetch_months=13,
        editorial_note=(
            "Salarios (índice oct-2016=100) e IPC compuesto, ambos en base 100 del mes inicial."
        ),
    ),
    "canasta_basica_vs_ipc_base100": _spec(
        "canasta_basica_vs_ipc_base100",
        "Canasta básica vs. inflación (base 100)",
        "dual_base100",
        ("ar_indec_cbt", "ar_indec_ipc_mensual"),
        window_months=12,
        fetch_months=13,
        editorial_note=(
            "CBT en pesos corrientes e IPC compuesto, re-indexados a base 100 en el mes inicial."
        ),
    ),
    "balanza_comercial_ica": _spec(
        "balanza_comercial_ica",
        "Balanza comercial (ICA)",
        "trade_balance",
        ("ar_indec_ica_exportaciones", "ar_indec_ica_importaciones"),
        window_months=12,
        fetch_months=12,
        editorial_note=(
            "Exportaciones e importaciones ICA (INDEC), millones de USD. Saldo = expo − impo."
        ),
    ),
}

_MATCH_PRIORITY: tuple[PlaybookId, ...] = (
    "brecha_cambiaria",
    "salarios_vs_ipc_base100",
    "canasta_basica_vs_ipc_base100",
    "balanza_comercial_ica",
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
    primary_mode: _SeriesMode = "percent_change",
    secondary_mode: _SeriesMode = "level",
    primary_label: str = "IPC acumulado",
    secondary_label: str = "Dólar oficial",
    gap_label: str = "Brecha real",
    primary_subject: str = "IPC",
    secondary_subject: str = "dólar",
) -> tuple[list[DataPoint], list[DataPoint], ChartNarrative]:
    """
    Re-indexa dos series mensuales a base 100.

    Por defecto la primaria es una variación mensual % (se compone) y la secundaria
    es un nivel (se divide por su t0), que es el caso IPC vs. dólar oficial.
    Un índice ya publicado (salarios, CBT) entra con `primary_mode="level"`.
    Recorta a `<= publish_date` y exige al menos 2 meses comunes.
    """
    if max_months < 1:
        raise ValueError("max_months tiene que ser al menos 1")

    primary_by_month = _monthly_last(_clip(ipc_points, publish_date))
    secondary_by_month = _monthly_last(_clip(fx_points, publish_date))
    common = sorted(set(primary_by_month) & set(secondary_by_month))
    if len(common) < 2:
        raise ValueError(
            "hacen falta al menos 2 meses comunes entre IPC y dólar oficial "
            f"(hay {len(common)} con fecha <= {publish_date.isoformat()})"
        )
    window = common[-(max_months + 1) :]
    primary_raw = [primary_by_month[key] for key in window]
    secondary_raw = [secondary_by_month[key] for key in window]
    primary_index = _rebase_series(primary_raw, primary_mode, role="primaria")
    secondary_index = _rebase_series(
        secondary_raw,
        secondary_mode,
        role="secundaria",
        legacy_fx_errors=secondary_subject == "dólar" and secondary_mode == "level",
    )
    primary_out: list[DataPoint] = []
    secondary_out: list[DataPoint] = []
    for raw, primary_value, secondary_value in zip(
        primary_raw, primary_index, secondary_index, strict=True
    ):
        primary_out.append(DataPoint(obs_date=raw.obs_date, value=primary_value))
        secondary_out.append(DataPoint(obs_date=raw.obs_date, value=secondary_value))
    if isclose(secondary_out[-1].value, 0.0, abs_tol=_ZERO_EPS):
        if secondary_subject == "dólar":
            raise ValueError(
                "el índice de dólar oficial termina en 0; no se puede calcular la brecha"
            )
        raise ValueError(
            "el índice de la serie secundaria termina en 0; no se puede calcular la brecha"
        )
    narrative = _dual_narrative(
        primary_out,
        secondary_out,
        primary_label=primary_label,
        secondary_label=secondary_label,
        gap_label=gap_label,
        primary_subject=primary_subject,
        secondary_subject=secondary_subject,
    )
    return primary_out, secondary_out, narrative


def build_dual_spread(
    official_points: Sequence[DataPoint],
    parallel_points: Sequence[DataPoint],
    *,
    publish_date: date,
    max_months: int = 12,
) -> tuple[list[DataPoint], list[DataPoint], ChartNarrative]:
    """Brecha % entre dólar oficial y paralelo, alineados a fin de mes."""
    if max_months < 1:
        raise ValueError("max_months tiene que ser al menos 1")
    paired = _paired_months(official_points, parallel_points, publish_date, max_months)
    if len(paired) < 2:
        raise ValueError(
            "hacen falta al menos 2 meses comunes entre dólar oficial y paralelo "
            f"(hay {len(paired)} con fecha <= {publish_date.isoformat()})"
        )
    official_out: list[DataPoint] = []
    parallel_out: list[DataPoint] = []
    gaps: list[float] = []
    for official, parallel in paired:
        if isclose(official.value, 0.0, abs_tol=_ZERO_EPS):
            raise ValueError("el dólar oficial del mes es 0; no se puede calcular la brecha")
        gap = ((parallel.value / official.value) - 1.0) * 100.0
        official_out.append(DataPoint(obs_date=official.obs_date, value=official.value))
        parallel_out.append(DataPoint(obs_date=official.obs_date, value=parallel.value))
        gaps.append(gap)
    current = gaps[-1]
    previous = gaps[-2]
    direction = _direction(current - previous)
    window = f"{official_out[0].obs_date.isoformat()}→{official_out[-1].obs_date.isoformat()}"
    narrative = ChartNarrative(
        mode="trend_with_callout",
        headline_badge=f"Brecha actual: {_fmt_signed_pct(current)}",
        delta_direction=direction,
        anchor_date=official_out[-1].obs_date.isoformat(),
        anchor_label=_anchor_label(official_out[-1].obs_date),
        kpis=[
            EditorialKpi(
                label="Oficial",
                formatted_value=_fmt_level(official_out[-1].value),
                detail=window,
            ),
            EditorialKpi(
                label="Paralelo/MEP",
                formatted_value=_fmt_level(parallel_out[-1].value),
                detail=window,
            ),
            EditorialKpi(
                label="Brecha máx.",
                formatted_value=_fmt_signed_pct(max(gaps)),
                detail=window,
            ),
        ],
    )
    return official_out, parallel_out, narrative


def build_trade_balance(
    exports_points: Sequence[DataPoint],
    imports_points: Sequence[DataPoint],
    *,
    publish_date: date,
    max_months: int = 12,
) -> tuple[list[DataPoint], list[DataPoint], ChartNarrative]:
    """Saldo mensual ICA = exportaciones − importaciones, alineado por mes."""
    if max_months < 1:
        raise ValueError("max_months tiene que ser al menos 1")
    paired = _paired_months(exports_points, imports_points, publish_date, max_months)
    if not paired:
        raise ValueError(
            "no hay meses comunes entre exportaciones e importaciones "
            f"con fecha <= {publish_date.isoformat()}"
        )
    exports_out: list[DataPoint] = []
    imports_out: list[DataPoint] = []
    balances: list[float] = []
    for exports, imports in paired:
        balance = exports.value - imports.value
        exports_out.append(DataPoint(obs_date=exports.obs_date, value=exports.value))
        imports_out.append(DataPoint(obs_date=exports.obs_date, value=imports.value))
        balances.append(balance)
    last_balance = balances[-1]
    accumulated = sum(balances)
    direction = _direction(last_balance)
    window = f"{exports_out[0].obs_date.isoformat()}→{exports_out[-1].obs_date.isoformat()}"
    narrative = ChartNarrative(
        mode="trend_with_callout",
        headline_badge=_balance_badge(last_balance, direction),
        delta_direction=direction,
        anchor_date=exports_out[-1].obs_date.isoformat(),
        anchor_label=_anchor_label(exports_out[-1].obs_date),
        kpis=[
            EditorialKpi(
                label="Último saldo",
                formatted_value=_fmt_level(last_balance, signed=True),
                detail=window,
            ),
            EditorialKpi(
                label="Acum. período",
                formatted_value=_fmt_level(accumulated, signed=True),
                detail=window,
            ),
            EditorialKpi(
                label="Exportaciones últ. mes",
                formatted_value=_fmt_level(exports_out[-1].value),
                detail=window,
            ),
        ],
    )
    return exports_out, imports_out, narrative


def _paired_months(
    left_points: Sequence[DataPoint],
    right_points: Sequence[DataPoint],
    publish_date: date,
    max_months: int,
) -> list[tuple[DataPoint, DataPoint]]:
    """Último dato de cada mes en común, recortado a `<= publish_date`."""
    left = _monthly_last(_clip(left_points, publish_date))
    right = _monthly_last(_clip(right_points, publish_date))
    common = sorted(set(left) & set(right))
    window = common[-max_months:]
    return [(left[key], right[key]) for key in window]


def _rebase_series(
    points: Sequence[DataPoint],
    mode: _SeriesMode,
    *,
    role: str,
    legacy_fx_errors: bool = False,
) -> list[float]:
    if mode == "level":
        base = points[0].value
        if isclose(base, 0.0, abs_tol=_ZERO_EPS):
            if legacy_fx_errors:
                raise ValueError("el dólar oficial del mes base es 0; no se puede re-indexar")
            raise ValueError(f"el valor base de la serie {role} es 0; no se puede re-indexar")
        return [(point.value / base) * 100.0 for point in points]
    level = 100.0
    indexed: list[float] = []
    for index, point in enumerate(points):
        if index > 0:
            level = level * (1.0 + point.value / 100.0)
        indexed.append(level)
    return indexed


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
    if playbook_id == "brecha_cambiaria":
        return any(
            token in blob
            for token in ("brecha", "cepo", "dolar blue", "dolar paralelo", "dolar mep")
        ) or _has_word(blob, "ccl")
    if playbook_id == "salarios_vs_ipc_base100":
        return any(
            token in blob
            for token in (
                "salario",
                "sueldo",
                "poder adquisitivo",
                "paritarias",
                "ingresos reales",
            )
        )
    if playbook_id == "canasta_basica_vs_ipc_base100":
        return any(token in blob for token in ("canasta basica", "pobreza", "indigencia")) or any(
            _has_word(blob, token) for token in ("cbt", "cba")
        )
    if playbook_id == "balanza_comercial_ica":
        return any(
            token in blob
            for token in (
                "balanza comercial",
                "exportaciones",
                "importaciones",
                "intercambio comercial",
            )
        ) or _has_word(blob, "ica")
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


def _has_word(blob: str, token: str) -> bool:
    return token in set(blob.replace(".", " ").split())


def _dual_narrative(
    ipc_index: Sequence[DataPoint],
    fx_index: Sequence[DataPoint],
    *,
    primary_label: str = "IPC acumulado",
    secondary_label: str = "Dólar oficial",
    gap_label: str = "Brecha real",
    primary_subject: str = "IPC",
    secondary_subject: str = "dólar",
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
        headline_badge=_gap_badge(
            gap,
            direction,
            primary_subject=primary_subject,
            secondary_subject=secondary_subject,
        ),
        delta_direction=direction,
        anchor_date=ipc_index[-1].obs_date.isoformat(),
        anchor_label=_anchor_label(ipc_index[-1].obs_date),
        kpis=[
            EditorialKpi(
                label=primary_label,
                formatted_value=_fmt_signed_pct(ipc_change),
                detail=window,
            ),
            EditorialKpi(
                label=secondary_label,
                formatted_value=_fmt_signed_pct(fx_change),
                detail=window,
            ),
            EditorialKpi(
                label=gap_label,
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


def _gap_badge(
    gap: float,
    direction: DeltaDirection,
    *,
    primary_subject: str = "IPC",
    secondary_subject: str = "dólar",
) -> str:
    formatted = _fmt_signed_pct(gap)
    if direction == "up":
        return f"▲ {formatted} {primary_subject} sobre {secondary_subject}"
    if direction == "down":
        return f"▼ {formatted} {secondary_subject} sobre {primary_subject}"
    return "= 0,0%"


def _balance_badge(balance: float, direction: DeltaDirection) -> str:
    signed = direction != "flat"
    amount = _fmt_level(abs(balance) if direction == "flat" else balance, signed=signed)
    if direction == "up":
        return f"▲ {amount} mill. USD"
    if direction == "down":
        return f"▼ {amount} mill. USD"
    return "= 0,0 mill. USD"


def _fmt_level(value: float, *, signed: bool = False) -> str:
    rounded = round(value, 1)
    if abs(rounded) < 0.05:
        rounded = 0.0
    whole = abs(rounded - round(rounded)) < 0.05 and abs(rounded - int(rounded)) < 0.05
    magnitude = abs(int(round(rounded))) if whole else abs(rounded)
    if whole:
        body = f"{int(magnitude):,}".replace(",", ".")
    else:
        body = f"{magnitude:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if not signed:
        return body
    sign = "+" if rounded >= 0 else "-"
    return f"{sign}{body}"


def _fmt_signed_pct(value: float) -> str:
    rounded = round(value, 1)
    if abs(rounded) < 0.05:
        rounded = 0.0
    sign = "+" if rounded >= 0 else "-"
    body = f"{abs(rounded):.1f}".replace(".", ",")
    return f"{sign}{body}%"


def _anchor_label(obs_date: date) -> str:
    return f"{_MONTHS_ES[obs_date.month - 1]}-{obs_date.year}"
