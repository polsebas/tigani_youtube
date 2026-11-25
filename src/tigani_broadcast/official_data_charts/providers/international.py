"""Proveedores internacionales official_primary: BCB, IMF, ECB, World Bank, FRED."""

from __future__ import annotations

import csv
import io
import os
from datetime import date

import httpx

from tigani_broadcast.official_data_charts.models import (
    CatalogEntry,
    SeriesData,
    SeriesObservation,
)
from tigani_broadcast.official_data_charts.providers.base import (
    ProviderAuthError,
    ProviderResponseError,
    build_http_client,
    request_json,
    request_text,
)

BCB_BASE_URL = "https://api.bcb.gov.br/dados/serie"
IMF_BASE_URL = "https://www.imf.org/external/datamapper/api/v1"
ECB_BASE_URL = "https://data-api.ecb.europa.eu/service/data"
WORLDBANK_BASE_URL = "https://api.worldbank.org/v2"
FRED_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"
USER_AGENT = "tigani-broadcast/0.0.0 (+official-data-charts; contact=local)"


def _parse_float(raw: object, *, provider: str) -> float:
    if isinstance(raw, bool):
        raise ProviderResponseError(f"{provider}: valor booleano inesperado")
    if isinstance(raw, (int, float)):
        return float(raw)
    if not isinstance(raw, str):
        raise ProviderResponseError(f"{provider}: valor no numérico: {raw!r}")
    cleaned = raw.strip().replace(",", ".")
    try:
        return float(cleaned)
    except ValueError as exc:
        raise ProviderResponseError(f"{provider}: valor no numérico: {raw!r}") from exc


def _empty_range_error(provider: str, start_date: date, end_date: date) -> ProviderResponseError:
    return ProviderResponseError(
        f"{provider}: respuesta sin observaciones para el rango "
        f"{start_date.isoformat()}..{end_date.isoformat()}"
    )


class BCBProvider:
    """Banco Central do Brasil — SGS (sin auth)."""

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: httpx.Timeout | float = 30.0,
        base_url: str = BCB_BASE_URL,
    ) -> None:
        self._client, self._owns_client = build_http_client(
            client=client,
            transport=transport,
            timeout=timeout,
            headers={"User-Agent": USER_AGENT},
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
        if entry.provider != "bcb":
            raise ProviderResponseError(
                f"bcb: catalog_id {entry.catalog_id} no corresponde a provider bcb"
            )
        if start_date > end_date:
            raise ProviderResponseError("bcb: start_date no puede ser mayor que end_date")

        url = f"{self._base_url}/bcdata.sgs.{entry.series_id}/dados"
        params = {
            "formato": "json",
            "dataInicial": start_date.strftime("%d/%m/%Y"),
            "dataFinal": end_date.strftime("%d/%m/%Y"),
        }
        payload = request_json(self._client, "GET", url, provider="bcb", params=params)
        observations = _parse_bcb_payload(payload, start_date=start_date, end_date=end_date)
        if not observations:
            raise _empty_range_error("bcb", start_date, end_date)

        query = f"formato=json&dataInicial={params['dataInicial']}&dataFinal={params['dataFinal']}"
        return SeriesData(
            catalog_id=entry.catalog_id,
            provider="bcb",
            source_tier=entry.source_tier,
            series_id=entry.series_id,
            source_url=f"{url}?{query}",
            source_attribution=entry.source_attribution,
            unit=entry.unit,
            frequency=entry.frequency,
            observations=observations,
        )


def _parse_bcb_payload(
    payload: object,
    *,
    start_date: date,
    end_date: date,
) -> list[SeriesObservation]:
    if not isinstance(payload, list):
        raise ProviderResponseError("bcb: payload raíz no es una lista JSON")
    observations: list[SeriesObservation] = []
    for row in payload:
        if not isinstance(row, dict):
            raise ProviderResponseError("bcb: fila inválida")
        fecha_raw = row.get("data")
        if not isinstance(fecha_raw, str):
            raise ProviderResponseError("bcb: fecha ausente o inválida")
        try:
            day_s, month_s, year_s = fecha_raw.split("/")
            obs_date = date(int(year_s), int(month_s), int(day_s))
        except ValueError as exc:
            raise ProviderResponseError(f"bcb: fecha no dd/MM/yyyy: {fecha_raw}") from exc
        if obs_date < start_date or obs_date > end_date:
            continue
        valor_raw = row.get("valor")
        if valor_raw is None or (isinstance(valor_raw, str) and valor_raw.strip() == ""):
            observations.append(SeriesObservation(obs_date=obs_date, value=None))
            continue
        value = _parse_float(valor_raw, provider="bcb")
        observations.append(SeriesObservation(obs_date=obs_date, value=value))
    observations.sort(key=lambda obs: obs.obs_date)
    return observations


class IMFProvider:
    """FMI DataMapper API (sin auth). series_id = '{indicator}/{country}'."""

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: httpx.Timeout | float = 30.0,
        base_url: str = IMF_BASE_URL,
    ) -> None:
        self._client, self._owns_client = build_http_client(
            client=client,
            transport=transport,
            timeout=timeout,
            headers={"User-Agent": USER_AGENT},
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
        if entry.provider != "imf":
            raise ProviderResponseError(
                f"imf: catalog_id {entry.catalog_id} no corresponde a provider imf"
            )
        if start_date > end_date:
            raise ProviderResponseError("imf: start_date no puede ser mayor que end_date")

        indicator, country = _split_imf_series_id(entry.series_id)
        url = f"{self._base_url}/{indicator}/{country}"
        payload = request_json(self._client, "GET", url, provider="imf")
        observations = _parse_imf_payload(
            payload,
            indicator=indicator,
            country=country,
            start_date=start_date,
            end_date=end_date,
        )
        if not observations:
            raise _empty_range_error("imf", start_date, end_date)

        return SeriesData(
            catalog_id=entry.catalog_id,
            provider="imf",
            source_tier=entry.source_tier,
            series_id=entry.series_id,
            source_url=url,
            source_attribution=entry.source_attribution,
            unit=entry.unit,
            frequency=entry.frequency,
            observations=observations,
        )


def _split_imf_series_id(series_id: str) -> tuple[str, str]:
    parts = series_id.split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ProviderResponseError(
            f"imf: series_id inválido (esperado INDICATOR/COUNTRY): {series_id}"
        )
    return parts[0], parts[1]


def _parse_imf_payload(
    payload: object,
    *,
    indicator: str,
    country: str,
    start_date: date,
    end_date: date,
) -> list[SeriesObservation]:
    if not isinstance(payload, dict):
        raise ProviderResponseError("imf: payload raíz no es un objeto JSON")
    values = payload.get("values")
    if not isinstance(values, dict):
        raise ProviderResponseError("imf: falta values")
    by_indicator = values.get(indicator)
    if not isinstance(by_indicator, dict):
        raise ProviderResponseError(f"imf: falta values.{indicator}")
    by_country = by_indicator.get(country)
    if not isinstance(by_country, dict):
        raise ProviderResponseError(f"imf: falta values.{indicator}.{country}")

    observations: list[SeriesObservation] = []
    for year_raw, valor_raw in by_country.items():
        try:
            year = int(str(year_raw))
        except ValueError as exc:
            raise ProviderResponseError(f"imf: año inválido: {year_raw!r}") from exc
        if year < start_date.year or year > end_date.year:
            continue
        obs_date = date(year, 1, 1)
        if valor_raw is None:
            observations.append(SeriesObservation(obs_date=obs_date, value=None))
            continue
        value = _parse_float(valor_raw, provider="imf")
        observations.append(SeriesObservation(obs_date=obs_date, value=value))
    observations.sort(key=lambda obs: obs.obs_date)
    return observations


class ECBProvider:
    """BCE Data API — CSV SDMX (`format=csvdata`)."""

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: httpx.Timeout | float = 30.0,
        base_url: str = ECB_BASE_URL,
    ) -> None:
        self._client, self._owns_client = build_http_client(
            client=client,
            transport=transport,
            timeout=timeout,
            headers={"User-Agent": USER_AGENT, "Accept": "text/csv"},
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
        if entry.provider != "ecb":
            raise ProviderResponseError(
                f"ecb: catalog_id {entry.catalog_id} no corresponde a provider ecb"
            )
        if start_date > end_date:
            raise ProviderResponseError("ecb: start_date no puede ser mayor que end_date")

        url = f"{self._base_url}/{entry.series_id}"
        params = {
            "startPeriod": start_date.isoformat(),
            "endPeriod": end_date.isoformat(),
            "format": "csvdata",
        }
        text = request_text(self._client, "GET", url, provider="ecb", params=params)
        observations = _parse_ecb_csv(text, start_date=start_date, end_date=end_date)
        if not observations:
            raise _empty_range_error("ecb", start_date, end_date)

        query = (
            f"startPeriod={params['startPeriod']}&endPeriod={params['endPeriod']}&format=csvdata"
        )
        return SeriesData(
            catalog_id=entry.catalog_id,
            provider="ecb",
            source_tier=entry.source_tier,
            series_id=entry.series_id,
            source_url=f"{url}?{query}",
            source_attribution=entry.source_attribution,
            unit=entry.unit,
            frequency=entry.frequency,
            observations=observations,
        )


def _parse_ecb_time_period(raw: str) -> date:
    text = raw.strip()
    if len(text) == 10:
        return date.fromisoformat(text)
    if len(text) == 7 and text[4] == "-":
        year_s, month_s = text.split("-")
        return date(int(year_s), int(month_s), 1)
    raise ValueError(f"TIME_PERIOD no soportado: {raw}")


def _parse_ecb_csv(
    text: str,
    *,
    start_date: date,
    end_date: date,
) -> list[SeriesObservation]:
    if not text.strip():
        return []
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise ProviderResponseError("ecb: CSV sin encabezado")
    if "TIME_PERIOD" not in reader.fieldnames or "OBS_VALUE" not in reader.fieldnames:
        raise ProviderResponseError("ecb: CSV sin columnas TIME_PERIOD/OBS_VALUE")

    observations: list[SeriesObservation] = []
    for row in reader:
        period_raw = row.get("TIME_PERIOD")
        if not isinstance(period_raw, str) or not period_raw.strip():
            raise ProviderResponseError("ecb: TIME_PERIOD ausente")
        try:
            obs_date = _parse_ecb_time_period(period_raw)
        except ValueError as exc:
            raise ProviderResponseError(f"ecb: {exc}") from exc
        if obs_date < start_date or obs_date > end_date:
            continue
        valor_raw = row.get("OBS_VALUE")
        if valor_raw is None or str(valor_raw).strip() == "":
            observations.append(SeriesObservation(obs_date=obs_date, value=None))
            continue
        value = _parse_float(valor_raw, provider="ecb")
        observations.append(SeriesObservation(obs_date=obs_date, value=value))
    observations.sort(key=lambda obs: obs.obs_date)
    return observations


class WorldBankProvider:
    """World Bank Indicators API. series_id = '{country}:{indicator}'."""

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: httpx.Timeout | float = 30.0,
        base_url: str = WORLDBANK_BASE_URL,
    ) -> None:
        self._client, self._owns_client = build_http_client(
            client=client,
            transport=transport,
            timeout=timeout,
            headers={"User-Agent": USER_AGENT},
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
        if entry.provider != "worldbank":
            raise ProviderResponseError(
                f"worldbank: catalog_id {entry.catalog_id} no corresponde a provider worldbank"
            )
        if start_date > end_date:
            raise ProviderResponseError("worldbank: start_date no puede ser mayor que end_date")

        country, indicator = _split_worldbank_series_id(entry.series_id)
        url = f"{self._base_url}/country/{country}/indicator/{indicator}"
        params = {
            "date": f"{start_date.year}:{end_date.year}",
            "format": "json",
            "per_page": "500",
        }
        payload = request_json(self._client, "GET", url, provider="worldbank", params=params)
        observations = _parse_worldbank_payload(payload, start_date=start_date, end_date=end_date)
        if not observations:
            raise _empty_range_error("worldbank", start_date, end_date)

        query = f"date={params['date']}&format=json&per_page=500"
        return SeriesData(
            catalog_id=entry.catalog_id,
            provider="worldbank",
            source_tier=entry.source_tier,
            series_id=entry.series_id,
            source_url=f"{url}?{query}",
            source_attribution=entry.source_attribution,
            unit=entry.unit,
            frequency=entry.frequency,
            observations=observations,
        )


def _split_worldbank_series_id(series_id: str) -> tuple[str, str]:
    parts = series_id.split(":", maxsplit=1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ProviderResponseError(
            f"worldbank: series_id inválido (esperado COUNTRY:INDICATOR): {series_id}"
        )
    return parts[0], parts[1]


def _parse_worldbank_payload(
    payload: object,
    *,
    start_date: date,
    end_date: date,
) -> list[SeriesObservation]:
    if not isinstance(payload, list) or len(payload) < 2:
        raise ProviderResponseError("worldbank: se esperaba array JSON [meta, data]")
    rows = payload[1]
    if rows is None:
        return []
    if not isinstance(rows, list):
        raise ProviderResponseError("worldbank: data[] inválida")

    observations: list[SeriesObservation] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ProviderResponseError("worldbank: fila inválida")
        year_raw = row.get("date")
        try:
            year = int(str(year_raw))
        except (TypeError, ValueError) as exc:
            raise ProviderResponseError(f"worldbank: año inválido: {year_raw!r}") from exc
        if year < start_date.year or year > end_date.year:
            continue
        obs_date = date(year, 1, 1)
        valor_raw = row.get("value")
        if valor_raw is None:
            observations.append(SeriesObservation(obs_date=obs_date, value=None))
            continue
        value = _parse_float(valor_raw, provider="worldbank")
        observations.append(SeriesObservation(obs_date=obs_date, value=value))
    observations.sort(key=lambda obs: obs.obs_date)
    return observations


class FREDProvider:
    """FRED (St. Louis Fed). Exige FRED_API_KEY (env o inyección)."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        client: httpx.Client | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: httpx.Timeout | float = 30.0,
        base_url: str = FRED_BASE_URL,
    ) -> None:
        env_key = os.environ.get("FRED_API_KEY")
        resolved = api_key if api_key is not None else env_key
        self._api_key = resolved.strip() if isinstance(resolved, str) else None
        if self._api_key == "":
            self._api_key = None
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
        if entry.provider != "fred":
            raise ProviderResponseError(
                f"fred: catalog_id {entry.catalog_id} no corresponde a provider fred"
            )
        if start_date > end_date:
            raise ProviderResponseError("fred: start_date no puede ser mayor que end_date")
        if self._api_key is None:
            raise ProviderAuthError("fred: falta FRED_API_KEY")

        params = {
            "series_id": entry.series_id,
            "observation_start": start_date.isoformat(),
            "observation_end": end_date.isoformat(),
            "file_type": "json",
            "api_key": self._api_key,
        }
        payload = request_json(
            self._client,
            "GET",
            self._base_url,
            provider="fred",
            params=params,
        )
        observations = _parse_fred_payload(payload, start_date=start_date, end_date=end_date)
        if not observations:
            raise _empty_range_error("fred", start_date, end_date)

        # No incluir api_key en source_url.
        query = (
            f"series_id={entry.series_id}"
            f"&observation_start={params['observation_start']}"
            f"&observation_end={params['observation_end']}"
            f"&file_type=json"
        )
        return SeriesData(
            catalog_id=entry.catalog_id,
            provider="fred",
            source_tier=entry.source_tier,
            series_id=entry.series_id,
            source_url=f"{self._base_url}?{query}",
            source_attribution=entry.source_attribution,
            unit=entry.unit,
            frequency=entry.frequency,
            observations=observations,
        )


def _parse_fred_payload(
    payload: object,
    *,
    start_date: date,
    end_date: date,
) -> list[SeriesObservation]:
    if not isinstance(payload, dict):
        raise ProviderResponseError("fred: payload raíz no es un objeto JSON")
    rows = payload.get("observations")
    if not isinstance(rows, list):
        raise ProviderResponseError("fred: falta observations[]")

    observations: list[SeriesObservation] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ProviderResponseError("fred: fila inválida")
        fecha_raw = row.get("date")
        if not isinstance(fecha_raw, str):
            raise ProviderResponseError("fred: fecha ausente o inválida")
        try:
            obs_date = date.fromisoformat(fecha_raw[:10])
        except ValueError as exc:
            raise ProviderResponseError(f"fred: fecha no ISO: {fecha_raw}") from exc
        if obs_date < start_date or obs_date > end_date:
            continue
        valor_raw = row.get("value")
        if valor_raw is None or (isinstance(valor_raw, str) and valor_raw.strip() in {"", "."}):
            observations.append(SeriesObservation(obs_date=obs_date, value=None))
            continue
        value = _parse_float(valor_raw, provider="fred")
        observations.append(SeriesObservation(obs_date=obs_date, value=value))
    observations.sort(key=lambda obs: obs.obs_date)
    return observations
