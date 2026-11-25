"""Conector Series de Tiempo de Datos Argentina (sin auth, fallback de INDEC)."""

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

DATOS_AR_BASE_URL = "https://apis.datos.gob.ar/series/api/series/"
USER_AGENT = "tigani-broadcast/0.0.0 (+official-data-charts; contact=local)"
_PERCENT_CHANGE_SUFFIXES = (
    ":percent_change_a_year_ago",
    ":percent_change",
)


def _series_uses_percent_change_mode(series_id: str) -> bool:
    return any(series_id.endswith(suffix) for suffix in _PERCENT_CHANGE_SUFFIXES)


def _unit_is_percent(unit: str) -> bool:
    normalized = unit.strip()
    return normalized == "%" or normalized.endswith("%")


class DatosArgentinaProvider:
    """Consulta `apis.datos.gob.ar/series` con User-Agent descriptivo."""

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: httpx.Timeout | float = 30.0,
        base_url: str = DATOS_AR_BASE_URL,
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
        if entry.provider not in {"datos_ar", "indec"}:
            # Permite reusar el conector como fallback de entradas INDEC.
            raise ProviderResponseError(
                f"datos_ar: provider {entry.provider} no soportado por este conector"
            )
        if start_date > end_date:
            raise ProviderResponseError("datos_ar: start_date no puede ser mayor que end_date")

        series_id = entry.series_id
        params = {
            "ids": series_id,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "format": "json",
            "limit": "5000",
        }
        payload = request_json(
            self._client,
            "GET",
            self._base_url,
            provider="datos_ar",
            params=params,
        )
        scale_to_pp = _series_uses_percent_change_mode(series_id) and _unit_is_percent(entry.unit)
        observations = _parse_datos_ar_payload(payload, scale_to_percentage_points=scale_to_pp)
        if not observations:
            raise ProviderResponseError(
                f"datos_ar: respuesta sin observaciones para el rango "
                f"{start_date.isoformat()}..{end_date.isoformat()}"
            )

        query = (
            f"ids={series_id}&start_date={params['start_date']}"
            f"&end_date={params['end_date']}&format=json"
        )
        source_url = f"{self._base_url}?{query}"
        return SeriesData(
            catalog_id=entry.catalog_id,
            provider="datos_ar",
            source_tier=entry.source_tier,
            series_id=series_id,
            source_url=source_url,
            source_attribution=entry.source_attribution,
            unit=entry.unit,
            frequency=entry.frequency,
            observations=observations,
        )


def _parse_datos_ar_payload(
    payload: object,
    *,
    scale_to_percentage_points: bool = False,
) -> list[SeriesObservation]:
    if not isinstance(payload, dict):
        raise ProviderResponseError("datos_ar: payload raíz no es un objeto JSON")
    data = payload.get("data")
    if not isinstance(data, list):
        raise ProviderResponseError("datos_ar: falta data[]")

    observations: list[SeriesObservation] = []
    for row in data:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            raise ProviderResponseError("datos_ar: fila data inválida")
        fecha_raw, valor_raw = row[0], row[1]
        if not isinstance(fecha_raw, str):
            raise ProviderResponseError("datos_ar: fecha no string")
        try:
            obs_date = date.fromisoformat(fecha_raw[:10])
        except ValueError as exc:
            raise ProviderResponseError(f"datos_ar: fecha no ISO: {fecha_raw}") from exc
        if valor_raw is None:
            observations.append(SeriesObservation(obs_date=obs_date, value=None))
            continue
        try:
            value = float(valor_raw)
        except (TypeError, ValueError) as exc:
            raise ProviderResponseError(f"datos_ar: valor no numérico: {valor_raw!r}") from exc
        if scale_to_percentage_points:
            value *= 100.0
        observations.append(SeriesObservation(obs_date=obs_date, value=value))

    observations.sort(key=lambda obs: obs.obs_date)
    return observations
