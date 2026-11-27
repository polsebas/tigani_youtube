"""Catálogo determinista de gestiones presidenciales argentinas (sin juicios de valor)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from tigani_broadcast.official_data_charts.models import RegimeBand

_ARGENTINA_SCOPE = frozenset({"argentina", "ar"})


@dataclass(frozen=True, slots=True)
class _RegimeDefinition:
    label: str
    start_date: date
    end_date: date | None  # None = mandato abierto (en curso)


# Apellido corto + período; techos inclusivos. Milei queda abierto.
ARGENTINE_PRESIDENTIAL_REGIMES: tuple[_RegimeDefinition, ...] = (
    _RegimeDefinition(
        label="Macri (2015–19)",
        start_date=date(2015, 12, 10),
        end_date=date(2019, 12, 9),
    ),
    _RegimeDefinition(
        label="Fernández (2019–23)",
        start_date=date(2019, 12, 10),
        end_date=date(2023, 12, 9),
    ),
    _RegimeDefinition(
        label="Milei (2023–act.)",
        start_date=date(2023, 12, 10),
        end_date=None,
    ),
)


def resolve_regime_bands(
    window_start: date,
    window_end: date,
    *,
    publish_date: date,
    scope: str,
    include_single: bool = False,
) -> list[RegimeBand]:
    """
    Interseca gestiones argentinas con `[window_start, min(window_end, publish_date)]`.

    - `scope` distinto de argentina → lista vacía.
    - Por defecto solo emite bandas si la ventana cruza ≥ 2 gestiones.
    - Con `include_single=True` también emite una sola banda intersectada.
    - Nunca devuelve fechas posteriores a `publish_date`.
    """
    if scope.strip().casefold() not in _ARGENTINA_SCOPE:
        return []
    if window_start > window_end:
        return []

    effective_end = min(window_end, publish_date)
    if window_start > effective_end:
        return []

    bands: list[RegimeBand] = []
    for regime in ARGENTINE_PRESIDENTIAL_REGIMES:
        regime_end = regime.end_date if regime.end_date is not None else publish_date
        regime_end = min(regime_end, publish_date)
        if regime.start_date > publish_date:
            continue

        overlap_start = max(window_start, regime.start_date)
        overlap_end = min(effective_end, regime_end)
        if overlap_start > overlap_end:
            continue
        bands.append(
            RegimeBand(
                label=regime.label,
                start_date=overlap_start,
                end_date=overlap_end,
            )
        )

    if not include_single and len(bands) < 2:
        return []
    return bands
