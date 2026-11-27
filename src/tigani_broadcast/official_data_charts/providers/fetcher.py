"""Orquestador de consulta: caché local, proveedores y fallback INDEC → datos_ar."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date

from tigani_broadcast.official_data_charts.cache import DiskSeriesCache
from tigani_broadcast.official_data_charts.models import CatalogEntry, ProviderId, SeriesData
from tigani_broadcast.official_data_charts.providers.base import (
    DataProvider,
    ProviderError,
    ProviderResponseError,
)


class SeriesFetcher:
    """
    Resuelve una entrada de catálogo contra el proveedor efectivo.

    - Valida `start_date <= end_date`.
    - Usa `DiskSeriesCache` si está configurada (clave del proveedor resuelto).
    - Ante cualquier `ProviderError` de INDEC (token, 404 de tabla, 5xx, timeout)
      con `fallback_provider=datos_ar`, reintenta de forma trazable contra Datos Argentina.
    """

    def __init__(
        self,
        providers: Mapping[ProviderId, DataProvider],
        cache: DiskSeriesCache | None = None,
    ) -> None:
        self._providers = dict(providers)
        self._cache = cache

    def fetch(
        self,
        entry: CatalogEntry,
        start_date: date,
        end_date: date,
    ) -> SeriesData:
        if start_date > end_date:
            raise ProviderResponseError("fetcher: start_date no puede ser mayor que end_date")

        provider_id: ProviderId = entry.provider
        series_id = entry.series_id

        cached = self._cache_get(provider_id, series_id, start_date, end_date)
        if cached is not None:
            return cached

        try:
            series = self._call_provider(provider_id, entry, start_date, end_date)
        except ProviderError:
            if self._can_fallback_indec_to_datos_ar(provider_id, entry):
                series = self._fetch_datos_ar_fallback(entry, start_date, end_date)
            else:
                raise

        self._cache_put(
            series.provider,
            series.series_id,
            start_date,
            end_date,
            series,
        )
        return series

    @staticmethod
    def _can_fallback_indec_to_datos_ar(
        provider_id: ProviderId,
        entry: CatalogEntry,
    ) -> bool:
        return (
            provider_id == "indec"
            and entry.fallback_provider == "datos_ar"
            and entry.fallback_series_id is not None
        )

    def _fetch_datos_ar_fallback(
        self,
        entry: CatalogEntry,
        start_date: date,
        end_date: date,
    ) -> SeriesData:
        assert entry.fallback_series_id is not None
        fallback_id: ProviderId = "datos_ar"
        fallback_series_id = entry.fallback_series_id

        cached = self._cache_get(fallback_id, fallback_series_id, start_date, end_date)
        if cached is not None:
            return cached

        fallback_entry = entry.model_copy(
            update={
                "provider": "datos_ar",
                "series_id": fallback_series_id,
                "fallback_provider": None,
                "fallback_series_id": None,
            }
        )
        series = self._call_provider(fallback_id, fallback_entry, start_date, end_date)
        if series.provider != "datos_ar" or series.series_id != fallback_series_id:
            raise ProviderError(
                "fetcher: el fallback datos_ar no respetó provider/series_id esperados"
            )
        return series

    def _call_provider(
        self,
        provider_id: ProviderId,
        entry: CatalogEntry,
        start_date: date,
        end_date: date,
    ) -> SeriesData:
        try:
            provider = self._providers[provider_id]
        except KeyError as exc:
            raise ProviderError(f"fetcher: proveedor no registrado: {provider_id}") from exc
        return provider.fetch_series(entry, start_date, end_date)

    def _cache_get(
        self,
        provider: ProviderId,
        series_id: str,
        start_date: date,
        end_date: date,
    ) -> SeriesData | None:
        if self._cache is None:
            return None
        return self._cache.get(provider, series_id, start_date, end_date)

    def _cache_put(
        self,
        provider: ProviderId,
        series_id: str,
        start_date: date,
        end_date: date,
        series: SeriesData,
    ) -> None:
        if self._cache is None:
            return
        self._cache.put(provider, series_id, start_date, end_date, series)
