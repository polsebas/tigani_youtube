"""SeriesFetcher: caché, fallback INDEC→datos_ar y fail-closed sin fallback."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest

from tigani_broadcast.official_data_charts.cache import DiskSeriesCache
from tigani_broadcast.official_data_charts.catalog import get_catalog_entry
from tigani_broadcast.official_data_charts.providers.base import (
    ProviderAuthError,
    ProviderError,
    ProviderResponseError,
)
from tigani_broadcast.official_data_charts.providers.bcra import BCRAProvider
from tigani_broadcast.official_data_charts.providers.datos_ar import DatosArgentinaProvider
from tigani_broadcast.official_data_charts.providers.fetcher import SeriesFetcher
from tigani_broadcast.official_data_charts.providers.indec import INDECProvider


def _json_response(request: httpx.Request, payload: object, status: int = 200) -> httpx.Response:
    return httpx.Response(
        status,
        request=request,
        headers={"Content-Type": "application/json"},
        content=json.dumps(payload).encode("utf-8"),
    )


def test_fetcher_valida_rango_de_fechas() -> None:
    fetcher = SeriesFetcher(providers={})
    with pytest.raises(ProviderResponseError, match="start_date"):
        fetcher.fetch(
            get_catalog_entry("ar_bcra_cer"),
            date(2025, 2, 1),
            date(2025, 1, 1),
        )


def test_fetcher_usa_cache_hit(tmp_path: Path) -> None:
    calls = {"n": 0}
    payload = {
        "status": 200,
        "results": [
            {
                "idVariable": 1,
                "detalle": [{"fecha": "2025-01-02", "valor": 20000}],
            }
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return _json_response(request, payload)

    cache = DiskSeriesCache(
        tmp_path,
        now_fn=lambda: datetime(2025, 6, 1, tzinfo=UTC),
    )
    bcra = BCRAProvider(transport=httpx.MockTransport(handler))
    fetcher = SeriesFetcher(providers={"bcra": bcra}, cache=cache)
    entry = get_catalog_entry("ar_bcra_reservas_brutas")
    first = fetcher.fetch(entry, date(2025, 1, 1), date(2025, 1, 3))
    second = fetcher.fetch(entry, date(2025, 1, 1), date(2025, 1, 3))
    assert first.observations[0].value == 20_000.0
    assert second.observations[0].value == 20_000.0
    assert calls["n"] == 1
    bcra.close()


def test_fallback_indec_a_datos_ar_sin_token(tmp_path: Path) -> None:
    calls: list[str] = []
    # Datos Argentina entrega proporción decimal en :percent_change (0.025 = 2.5%).
    datos_payload = {"data": [["2025-01-01", 0.025], ["2025-02-01", 0.027]]}

    # Base URL del mock: MockTransport no mira host; usamos path.
    def route(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if "ipc_nacional_tidy" in request.url.path:
            return httpx.Response(500, request=request, text="fail")
        return _json_response(request, datos_payload)

    cache = DiskSeriesCache(tmp_path)
    indec = INDECProvider(token="", transport=httpx.MockTransport(route))
    datos = DatosArgentinaProvider(transport=httpx.MockTransport(route))
    fetcher = SeriesFetcher(
        providers={"indec": indec, "datos_ar": datos},
        cache=cache,
    )
    entry = get_catalog_entry("ar_indec_ipc_mensual")
    series = fetcher.fetch(entry, date(2025, 1, 1), date(2025, 2, 28))

    assert series.provider == "datos_ar"
    assert series.series_id == entry.fallback_series_id
    assert entry.fallback_series_id is not None
    assert f"ids={entry.fallback_series_id}" in series.source_url
    assert series.observations[0].value == pytest.approx(2.5)
    assert series.observations[1].value == pytest.approx(2.7)
    assert "ipc_nacional_tidy" not in "".join(calls)
    indec.close()
    datos.close()


def test_sin_fallback_propaga_auth_error() -> None:
    entry = get_catalog_entry("ar_bcra_reservas_brutas")

    # Entrada BCRA sin fallback: un auth error del proveedor registrado se propaga.
    class Boom:
        def fetch_series(self, *_a, **_k):
            raise ProviderAuthError("bcra: HTTP 401")

    fetcher = SeriesFetcher(providers={"bcra": Boom()})  # type: ignore[dict-item]
    with pytest.raises(ProviderAuthError):
        fetcher.fetch(entry, date(2025, 1, 1), date(2025, 1, 2))


def test_error_servidor_indec_no_hace_fallback_si_hay_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, request=request, text="boom")

    indec = INDECProvider(token="tok", transport=httpx.MockTransport(handler))
    datos = DatosArgentinaProvider(
        transport=httpx.MockTransport(lambda r: _json_response(r, {"data": [["2025-01-01", 1.0]]}))
    )
    fetcher = SeriesFetcher(providers={"indec": indec, "datos_ar": datos})
    with pytest.raises(ProviderResponseError, match="HTTP 500"):
        fetcher.fetch(
            get_catalog_entry("ar_indec_ipc_mensual"),
            date(2025, 1, 1),
            date(2025, 1, 31),
        )
    indec.close()
    datos.close()


def test_proveedor_no_registrado() -> None:
    fetcher = SeriesFetcher(providers={})
    with pytest.raises(ProviderError, match="no registrado"):
        fetcher.fetch(
            get_catalog_entry("ar_bcra_cer"),
            date(2025, 1, 1),
            date(2025, 1, 2),
        )


def test_fetcher_sin_cache_funciona() -> None:
    payload = {
        "status": 200,
        "results": [{"idVariable": 30, "detalle": [{"fecha": "2025-01-01", "valor": 1.0}]}],
    }
    bcra = BCRAProvider(
        transport=httpx.MockTransport(lambda r: _json_response(r, payload)),
    )
    fetcher = SeriesFetcher(providers={"bcra": bcra}, cache=None)
    series = fetcher.fetch(
        get_catalog_entry("ar_bcra_cer"),
        date(2025, 1, 1),
        date(2025, 1, 1),
    )
    assert series.observations[0].value == 1.0
    bcra.close()
