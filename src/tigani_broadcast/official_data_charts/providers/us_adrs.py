"""ADRs argentinos y ARGT vía Stooq CSV (Tier 2, sin API key)."""

from __future__ import annotations

import csv
import io
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
    request_text,
)

STOOQ_DAILY_URL = "https://stooq.com/q/d/l/"
USER_AGENT = "tigani-broadcast/0.0.0 (+official-data-charts; contact=local)"


class USAdrsProvider:
    """Cotizaciones diarias de ADRs/ETF argentinos. Solo market_secondary / us_adrs."""

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: httpx.Timeout | float = 30.0,
        base_url: str = STOOQ_DAILY_URL,
    ) -> None:
        self._client, self._owns_client = build_http_client(
            client=client,
            transport=transport,
            timeout=timeout,
            headers={"User-Agent": USER_AGENT},
        )
        self._base_url = base_url

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def fetch_series(
        self,
        entry: CatalogEntry,
        start_date: date,
        end_date: date,
    ) -> SeriesData:
        if entry.provider != "us_adrs" or entry.source_tier != "market_secondary":
            raise ProviderResponseError(
                "us_adrs: solo acepta source_tier=market_secondary y provider=us_adrs"
            )
        if start_date > end_date:
            raise ProviderResponseError("us_adrs: start_date no puede ser mayor que end_date")

        ticker = entry.series_id.strip().lower()
        if not ticker:
            raise ProviderResponseError("us_adrs: series_id (ticker) vacío")

        params = {
            "s": f"{ticker}.us",
            "d1": start_date.strftime("%Y%m%d"),
            "d2": end_date.strftime("%Y%m%d"),
            "i": "d",
        }
        text = request_text(
            self._client,
            "GET",
            self._base_url,
            provider="us_adrs",
            params=params,
        )
        observations = _parse_stooq_csv(text, start_date=start_date, end_date=end_date)
        if not observations:
            raise ProviderResponseError(
                f"us_adrs: respuesta sin observaciones para el rango "
                f"{start_date.isoformat()}..{end_date.isoformat()}"
            )

        query = f"s={params['s']}&d1={params['d1']}&d2={params['d2']}&i=d"
        return SeriesData(
            catalog_id=entry.catalog_id,
            provider="us_adrs",
            source_tier="market_secondary",
            series_id=entry.series_id,
            source_url=f"{self._base_url}?{query}",
            source_attribution=entry.source_attribution,
            unit=entry.unit,
            frequency=entry.frequency,
            observations=observations,
        )


def _parse_stooq_csv(
    text: str,
    *,
    start_date: date,
    end_date: date,
) -> list[SeriesObservation]:
    cleaned = text.strip()
    if not cleaned:
        return []
    # Stooq a veces responde HTML/errores cortos en texto plano.
    if cleaned.lstrip().lower().startswith("<!DOCTYPE") or "No data" in cleaned:
        return []

    reader = csv.DictReader(io.StringIO(cleaned))
    if reader.fieldnames is None:
        raise ProviderResponseError("us_adrs: CSV sin encabezado")
    field_map = {name.lower(): name for name in reader.fieldnames if name}
    date_key = field_map.get("date")
    close_key = field_map.get("close")
    if date_key is None or close_key is None:
        raise ProviderResponseError("us_adrs: CSV sin columnas Date/Close")

    observations: list[SeriesObservation] = []
    for row in reader:
        fecha_raw = row.get(date_key)
        if not isinstance(fecha_raw, str) or not fecha_raw.strip():
            raise ProviderResponseError("us_adrs: Date ausente")
        try:
            obs_date = date.fromisoformat(fecha_raw.strip()[:10])
        except ValueError as exc:
            raise ProviderResponseError(f"us_adrs: Date no ISO: {fecha_raw}") from exc
        if obs_date < start_date or obs_date > end_date:
            continue
        close_raw = row.get(close_key)
        if close_raw is None or str(close_raw).strip() == "":
            observations.append(SeriesObservation(obs_date=obs_date, value=None))
            continue
        try:
            value = float(str(close_raw).strip().replace(",", "."))
        except ValueError as exc:
            raise ProviderResponseError(f"us_adrs: Close no numérico: {close_raw!r}") from exc
        observations.append(SeriesObservation(obs_date=obs_date, value=value))

    observations.sort(key=lambda obs: obs.obs_date)
    return observations
