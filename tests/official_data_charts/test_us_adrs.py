"""USAdrsProvider (Stooq CSV) — offline con MockTransport."""

from __future__ import annotations

from datetime import date

import httpx
import pytest

from tigani_broadcast.official_data_charts.catalog import get_catalog_entry
from tigani_broadcast.official_data_charts.models import CatalogEntry
from tigani_broadcast.official_data_charts.providers.base import (
    ProviderAuthError,
    ProviderRateLimitError,
    ProviderResponseError,
)
from tigani_broadcast.official_data_charts.providers.us_adrs import USAdrsProvider


def _csv_response(request: httpx.Request, text: str, status: int = 200) -> httpx.Response:
    return httpx.Response(
        status,
        request=request,
        headers={"Content-Type": "text/csv"},
        text=text,
    )


_GGAL_CSV = "\n".join(
    (
        "Date,Open,High,Low,Close,Volume",
        "2025-01-03,35.10,36.00,34.90,35.50,1000000",
        "2025-01-02,34.00,35.00,33.80,34.50,900000",
        "2025-01-06,36.00,36.50,35.80,36.20,1100000",
    )
)

_YPF_CSV = "\n".join(
    (
        "Date,Open,High,Low,Close,Volume",
        "2025-02-01,20.0,21.0,19.5,20.5,500000",
        "2025-02-03,21.0,22.0,20.8,21.5,600000",
    )
)

_ARGT_CSV = "\n".join(
    (
        "Date,Open,High,Low,Close,Volume",
        "2025-03-01,50.0,51.0,49.5,50.5,200000",
        "2025-03-02,50.5,52.0,50.0,51.2,210000",
    )
)


@pytest.mark.parametrize(
    ("catalog_id", "ticker", "csv_body", "attr_fragment"),
    [
        ("us_adr_ggal", "ggal", _GGAL_CSV, "NASDAQ vía Stooq"),
        ("us_adr_ypf", "ypf", _YPF_CSV, "NYSE vía Stooq"),
        ("us_adr_argt", "argt", _ARGT_CSV, "NYSE Arca vía Stooq"),
    ],
)
def test_us_adrs_parsea_stooq_ordenado(
    catalog_id: str,
    ticker: str,
    csv_body: str,
    attr_fragment: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["s"] == f"{ticker}.us"
        assert request.url.params["i"] == "d"
        return _csv_response(request, csv_body)

    entry = get_catalog_entry(catalog_id)
    provider = USAdrsProvider(transport=httpx.MockTransport(handler))
    series = provider.fetch_series(entry, date(2025, 1, 1), date(2025, 3, 31))
    assert series.provider == "us_adrs"
    assert series.source_tier == "market_secondary"
    assert attr_fragment in series.source_attribution
    assert series.observations == sorted(series.observations, key=lambda o: o.obs_date)
    assert all(o.value is not None for o in series.observations)
    provider.close()


def test_us_adrs_rechaza_source_tier_o_provider_invalidos() -> None:
    transport = httpx.MockTransport(lambda r: _csv_response(r, _GGAL_CSV))
    provider = USAdrsProvider(transport=transport)

    bad_tier = CatalogEntry(
        catalog_id="fake",
        label="fake",
        provider="us_adrs",
        source_tier="official_primary",
        geography="US",
        series_id="ggal",
        frequency="daily",
        unit="USD",
        description="x",
        source_attribution="x",
    )
    with pytest.raises(ProviderResponseError, match="market_secondary"):
        provider.fetch_series(bad_tier, date(2025, 1, 1), date(2025, 1, 2))

    with pytest.raises(ProviderResponseError, match="market_secondary"):
        provider.fetch_series(
            get_catalog_entry("ar_bcra_cer"),
            date(2025, 1, 1),
            date(2025, 1, 2),
        )
    provider.close()


def test_us_adrs_vacio_incluye_rango() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _csv_response(request, "Date,Open,High,Low,Close,Volume\n")

    provider = USAdrsProvider(transport=httpx.MockTransport(handler))
    with pytest.raises(
        ProviderResponseError,
        match=r"us_adrs:.*2025-01-01\.\.2025-01-31",
    ):
        provider.fetch_series(
            get_catalog_entry("us_adr_ggal"),
            date(2025, 1, 1),
            date(2025, 1, 31),
        )
    provider.close()


@pytest.mark.parametrize(
    ("status", "exc_type"),
    [
        (401, ProviderAuthError),
        (429, ProviderRateLimitError),
        (500, ProviderResponseError),
    ],
)
def test_us_adrs_mapea_errores_http(status: int, exc_type: type[Exception]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, request=request, text="err")

    provider = USAdrsProvider(transport=httpx.MockTransport(handler))
    with pytest.raises(exc_type):
        provider.fetch_series(
            get_catalog_entry("us_adr_ypf"),
            date(2025, 1, 1),
            date(2025, 1, 2),
        )
    provider.close()
