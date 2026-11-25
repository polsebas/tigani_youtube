"""
Conector Tier 2 ArgentinaDatos (riesgo país y dólares financieros/paralelos).

Cotizaciones de dólares: se usa el campo `venta` como valor de serie
(documentado: precio de venta publicado vía DolarApi / ArgentinaDatos).
"""

from __future__ import annotations

from datetime import date

import httpx

from tigani_broadcast.official_data_charts.models import (
    CatalogEntry,
    SeriesData,
    SeriesObservation,
)
from tigani_broadcast.official_data_charts.providers.base import (
    ProviderResponseError,
    build_http_client,
    request_json,
)

ARGENTINADATOS_BASE_URL = "https://api.argentinadatos.com/v1"

# series_id del catálogo → path relativo bajo /v1
_SERIES_PATHS: dict[str, str] = {
    "riesgo-pais": "/finanzas/indices/riesgo-pais",
    "dolares/blue": "/cotizaciones/dolares/blue",
    "dolares/bolsa": "/cotizaciones/dolares/bolsa",
    "dolares/contadoconliqui": "/cotizaciones/dolares/contadoconliqui",
}


class ArgentinaDatosProvider:
    """Solo acepta entradas `market_secondary` / `argentinadatos`."""

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: httpx.Timeout | float = 30.0,
        base_url: str = ARGENTINADATOS_BASE_URL,
    ) -> None:
        self._client, self._owns_client = build_http_client(
            client=client,
            transport=transport,
            timeout=timeout,
        )
        self._base_url = base_url.rstrip("/")

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def fetch_series(
        self,
        entry: CatalogEntry,
        start_date: date,
        end_date: date,
    ) -> SeriesData:
        if entry.provider != "argentinadatos" or entry.source_tier != "market_secondary":
            raise ProviderResponseError(
                "argentinadatos: solo acepta source_tier=market_secondary y provider=argentinadatos"
            )
        if start_date > end_date:
            raise ProviderResponseError(
                "argentinadatos: start_date no puede ser mayor que end_date"
            )

        path = _SERIES_PATHS.get(entry.series_id)
        if path is None:
            raise ProviderResponseError(
                f"argentinadatos: series_id no soportado: {entry.series_id}"
            )

        url = f"{self._base_url}{path}"
        payload = request_json(self._client, "GET", url, provider="argentinadatos")
        if entry.series_id == "riesgo-pais":
            observations = _parse_riesgo_pais(payload, start_date, end_date)
        else:
            observations = _parse_dolares(payload, start_date, end_date)

        if not observations:
            raise ProviderResponseError(
                f"argentinadatos: sin observaciones en el rango "
                f"{start_date.isoformat()}..{end_date.isoformat()}"
            )

        return SeriesData(
            catalog_id=entry.catalog_id,
            provider="argentinadatos",
            source_tier="market_secondary",
            series_id=entry.series_id,
            source_url=url,
            source_attribution=entry.source_attribution,
            unit=entry.unit,
            frequency=entry.frequency,
            observations=observations,
        )


def _parse_riesgo_pais(
    payload: object,
    start_date: date,
    end_date: date,
) -> list[SeriesObservation]:
    rows = _as_list(payload, provider="argentinadatos")
    observations: list[SeriesObservation] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ProviderResponseError("argentinadatos: fila de riesgo-pais inválida")
        obs_date = _parse_fecha(row.get("fecha"))
        if obs_date < start_date or obs_date > end_date:
            continue
        valor = row.get("valor")
        if valor is None:
            observations.append(SeriesObservation(obs_date=obs_date, value=None))
            continue
        try:
            value = float(valor)
        except (TypeError, ValueError) as exc:
            raise ProviderResponseError(f"argentinadatos: valor no numérico: {valor!r}") from exc
        observations.append(SeriesObservation(obs_date=obs_date, value=value))
    observations.sort(key=lambda obs: obs.obs_date)
    return observations


def _parse_dolares(
    payload: object,
    start_date: date,
    end_date: date,
) -> list[SeriesObservation]:
    """Usa `venta` como valor de serie (precio de venta)."""
    rows = _as_list(payload, provider="argentinadatos")
    observations: list[SeriesObservation] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ProviderResponseError("argentinadatos: fila de dólar inválida")
        obs_date = _parse_fecha(row.get("fecha"))
        if obs_date < start_date or obs_date > end_date:
            continue
        venta = row.get("venta")
        if venta is None:
            observations.append(SeriesObservation(obs_date=obs_date, value=None))
            continue
        try:
            value = float(venta)
        except (TypeError, ValueError) as exc:
            raise ProviderResponseError(f"argentinadatos: venta no numérica: {venta!r}") from exc
        observations.append(SeriesObservation(obs_date=obs_date, value=value))
    observations.sort(key=lambda obs: obs.obs_date)
    return observations


def _as_list(payload: object, *, provider: str) -> list[object]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        # Algunos endpoints de "último" devuelven un objeto único.
        return [payload]
    raise ProviderResponseError(f"{provider}: payload no es lista ni objeto")


def _parse_fecha(raw: object) -> date:
    if not isinstance(raw, str):
        raise ProviderResponseError("argentinadatos: fecha ausente o inválida")
    try:
        return date.fromisoformat(raw[:10])
    except ValueError as exc:
        raise ProviderResponseError(f"argentinadatos: fecha no ISO: {raw}") from exc
