"""Conector BCRA Estadísticas Monetarias v4.0 (sin auth)."""

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

BCRA_BASE_URL = "https://api.bcra.gob.ar/estadisticas/v4.0/Monetarias"


class BCRAProvider:
    """Consulta series monetarias diarias del BCRA v4.0."""

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: httpx.Timeout | float = 30.0,
        base_url: str = BCRA_BASE_URL,
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
        if entry.provider != "bcra":
            raise ProviderResponseError(
                f"bcra: catalog_id {entry.catalog_id} no corresponde a provider bcra"
            )
        if start_date > end_date:
            raise ProviderResponseError("bcra: start_date no puede ser mayor que end_date")

        url = f"{self._base_url}/{entry.series_id}"
        params = {
            "desde": start_date.isoformat(),
            "hasta": end_date.isoformat(),
        }
        payload = request_json(
            self._client,
            "GET",
            url,
            provider="bcra",
            params=params,
        )
        observations = _parse_bcra_payload(payload, start_date=start_date, end_date=end_date)
        if not observations:
            raise ProviderResponseError(
                f"bcra: respuesta sin observaciones válidas para el rango "
                f"{start_date.isoformat()}..{end_date.isoformat()}"
            )

        source_url = f"{url}?desde={params['desde']}&hasta={params['hasta']}"
        return SeriesData(
            catalog_id=entry.catalog_id,
            provider="bcra",
            source_tier=entry.source_tier,
            series_id=entry.series_id,
            source_url=source_url,
            source_attribution=entry.source_attribution,
            unit=entry.unit,
            frequency=entry.frequency,
            observations=observations,
        )


def _parse_bcra_payload(
    payload: object,
    *,
    start_date: date,
    end_date: date,
) -> list[SeriesObservation]:
    if not isinstance(payload, dict):
        raise ProviderResponseError("bcra: payload raíz no es un objeto JSON")
    results = payload.get("results")
    if not isinstance(results, list) or not results:
        raise ProviderResponseError("bcra: falta results[] con detalle")

    first = results[0]
    if not isinstance(first, dict):
        raise ProviderResponseError("bcra: results[0] inválido")
    detalle = first.get("detalle")
    if not isinstance(detalle, list):
        raise ProviderResponseError("bcra: falta results[].detalle")

    observations: list[SeriesObservation] = []
    for item in detalle:
        if not isinstance(item, dict):
            raise ProviderResponseError("bcra: elemento de detalle inválido")
        fecha_raw = item.get("fecha")
        valor_raw = item.get("valor")
        if not isinstance(fecha_raw, str):
            raise ProviderResponseError("bcra: fecha ausente o inválida en detalle")
        try:
            obs_date = date.fromisoformat(fecha_raw[:10])
        except ValueError as exc:
            raise ProviderResponseError(f"bcra: fecha no ISO: {fecha_raw}") from exc
        if obs_date < start_date or obs_date > end_date:
            continue
        if valor_raw is None:
            observations.append(SeriesObservation(obs_date=obs_date, value=None))
            continue
        try:
            value = float(valor_raw)
        except (TypeError, ValueError) as exc:
            raise ProviderResponseError(f"bcra: valor no numérico: {valor_raw!r}") from exc
        observations.append(SeriesObservation(obs_date=obs_date, value=value))

    observations.sort(key=lambda obs: obs.obs_date)
    if not any(obs.value is not None for obs in observations):
        return []
    return observations
