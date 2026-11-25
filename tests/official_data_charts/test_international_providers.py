"""Proveedores internacionales: payloads representativos y errores HTTP (offline)."""

from __future__ import annotations

import json
from datetime import date

import httpx
import pytest

from tigani_broadcast.official_data_charts.catalog import get_catalog_entry
from tigani_broadcast.official_data_charts.providers.base import (
    ProviderAuthError,
    ProviderRateLimitError,
    ProviderResponseError,
)
from tigani_broadcast.official_data_charts.providers.international import (
    BCBProvider,
    ECBProvider,
    FREDProvider,
    IMFProvider,
    WorldBankProvider,
)


def _json_response(request: httpx.Request, payload: object, status: int = 200) -> httpx.Response:
    return httpx.Response(
        status,
        request=request,
        headers={"Content-Type": "application/json"},
        content=json.dumps(payload).encode("utf-8"),
    )


def _text_response(request: httpx.Request, text: str, status: int = 200) -> httpx.Response:
    return httpx.Response(
        status,
        request=request,
        headers={"Content-Type": "text/csv"},
        text=text,
    )


def test_bcb_parsea_dd_mm_yyyy_y_coma_decimal() -> None:
    payload = [
        {"data": "03/01/2025", "valor": "12,25"},
        {"data": "01/01/2025", "valor": "12,15"},
        {"data": "02/01/2025", "valor": "12,20"},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert "bcdata.sgs.432" in str(request.url)
        assert request.url.params["dataInicial"] == "01/01/2025"
        assert request.url.params["dataFinal"] == "03/01/2025"
        return _json_response(request, payload)

    provider = BCBProvider(transport=httpx.MockTransport(handler))
    series = provider.fetch_series(
        get_catalog_entry("br_bcb_selic"),
        date(2025, 1, 1),
        date(2025, 1, 3),
    )
    assert [o.obs_date for o in series.observations] == [
        date(2025, 1, 1),
        date(2025, 1, 2),
        date(2025, 1, 3),
    ]
    assert [o.value for o in series.observations] == [12.15, 12.20, 12.25]
    assert series.provider == "bcb"
    provider.close()


def test_imf_filtra_anios_y_estampa_1_enero() -> None:
    payload = {
        "values": {
            "NGDP_RPCH": {
                "ARG": {
                    "2022": -1.6,
                    "2023": -1.6,
                    "2024": 3.5,
                    "2025": 5.0,
                }
            }
        }
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/NGDP_RPCH/ARG")
        return _json_response(request, payload)

    provider = IMFProvider(transport=httpx.MockTransport(handler))
    series = provider.fetch_series(
        get_catalog_entry("global_imf_gdp_growth_arg"),
        date(2023, 1, 1),
        date(2024, 12, 31),
    )
    assert [o.obs_date for o in series.observations] == [
        date(2023, 1, 1),
        date(2024, 1, 1),
    ]
    assert [o.value for o in series.observations] == [-1.6, 3.5]
    provider.close()


def test_ecb_parsea_csv_diario_y_mensual() -> None:
    csv_body = "\n".join(
        (
            "KEY,TIME_PERIOD,OBS_VALUE",
            "EXR,2025-01-02,1.0401",
            "EXR,2025-01-03,1.0410",
            "ICP,2025-02,2.3",
        )
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert "EXR/D.USD.EUR.SP00.A" in str(request.url)
        assert request.url.params["format"] == "csvdata"
        return _text_response(request, csv_body)

    provider = ECBProvider(transport=httpx.MockTransport(handler))
    series = provider.fetch_series(
        get_catalog_entry("eu_ecb_eur_usd"),
        date(2025, 1, 1),
        date(2025, 2, 28),
    )
    assert series.observations[0].obs_date == date(2025, 1, 2)
    assert series.observations[0].value == pytest.approx(1.0401)
    assert series.observations[2].obs_date == date(2025, 2, 1)
    assert series.observations[2].value == pytest.approx(2.3)
    provider.close()


def test_worldbank_parsea_segundo_elemento_del_array() -> None:
    payload = [
        {"page": 1, "pages": 1, "total": 2},
        [
            {"date": "2023", "value": 13712.5},
            {"date": "2024", "value": None},
            {"date": "2022", "value": 13650.0},
        ],
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert "/country/ARG/indicator/NY.GDP.PCAP.CD" in str(request.url)
        assert request.url.params["date"] == "2022:2024"
        return _json_response(request, payload)

    provider = WorldBankProvider(transport=httpx.MockTransport(handler))
    series = provider.fetch_series(
        get_catalog_entry("global_wb_gdp_per_capita_arg"),
        date(2022, 1, 1),
        date(2024, 12, 31),
    )
    assert [o.obs_date for o in series.observations] == [
        date(2022, 1, 1),
        date(2023, 1, 1),
        date(2024, 1, 1),
    ]
    assert series.observations[0].value == pytest.approx(13650.0)
    assert series.observations[2].value is None
    provider.close()


def test_fred_mapea_punto_a_none_y_exige_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    called = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        called["n"] += 1
        return _json_response(request, {"observations": []})

    provider = FREDProvider(api_key="", transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderAuthError, match="FRED_API_KEY"):
        provider.fetch_series(
            get_catalog_entry("us_fred_fed_funds"),
            date(2025, 1, 1),
            date(2025, 3, 1),
        )
    assert called["n"] == 0
    provider.close()

    payload = {
        "observations": [
            {"date": "2025-01-01", "value": "4.33"},
            {"date": "2025-02-01", "value": "."},
            {"date": "2025-03-01", "value": "4.28"},
        ]
    }

    def ok_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["api_key"] == "test-key"
        assert request.url.params["series_id"] == "FEDFUNDS"
        return _json_response(request, payload)

    provider = FREDProvider(api_key="test-key", transport=httpx.MockTransport(ok_handler))
    series = provider.fetch_series(
        get_catalog_entry("us_fred_fed_funds"),
        date(2025, 1, 1),
        date(2025, 3, 1),
    )
    assert [o.value for o in series.observations] == [4.33, None, 4.28]
    assert "api_key=" not in series.source_url
    provider.close()


@pytest.mark.parametrize(
    ("status", "exc_type"),
    [
        (401, ProviderAuthError),
        (429, ProviderRateLimitError),
        (500, ProviderResponseError),
    ],
)
def test_bcb_mapea_errores_http(status: int, exc_type: type[Exception]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, request=request, text="boom")

    provider = BCBProvider(transport=httpx.MockTransport(handler))
    with pytest.raises(exc_type):
        provider.fetch_series(
            get_catalog_entry("br_bcb_dolar_ptax"),
            date(2025, 1, 1),
            date(2025, 1, 2),
        )
    provider.close()


def test_imf_y_ecb_vacios_incluyen_rango() -> None:
    def imf_handler(request: httpx.Request) -> httpx.Response:
        return _json_response(request, {"values": {"NGDP_RPCH": {"BRA": {}}}})

    imf = IMFProvider(transport=httpx.MockTransport(imf_handler))
    with pytest.raises(
        ProviderResponseError,
        match=r"imf:.*2020-01-01\.\.2021-12-31",
    ):
        imf.fetch_series(
            get_catalog_entry("global_imf_gdp_growth_bra"),
            date(2020, 1, 1),
            date(2021, 12, 31),
        )
    imf.close()

    def ecb_handler(request: httpx.Request) -> httpx.Response:
        return _text_response(request, "KEY,TIME_PERIOD,OBS_VALUE\n")

    ecb = ECBProvider(transport=httpx.MockTransport(ecb_handler))
    with pytest.raises(
        ProviderResponseError,
        match=r"ecb:.*2025-01-01\.\.2025-01-31",
    ):
        ecb.fetch_series(
            get_catalog_entry("eu_ecb_hicp_yoy"),
            date(2025, 1, 1),
            date(2025, 1, 31),
        )
    ecb.close()


def test_providers_rechazan_rango_invertido_y_provider_ajeno() -> None:
    bcb = BCBProvider(transport=httpx.MockTransport(lambda r: _json_response(r, [])))
    with pytest.raises(ProviderResponseError, match="start_date"):
        bcb.fetch_series(
            get_catalog_entry("br_bcb_selic"),
            date(2025, 2, 1),
            date(2025, 1, 1),
        )
    with pytest.raises(ProviderResponseError, match="no corresponde"):
        bcb.fetch_series(
            get_catalog_entry("ar_bcra_cer"),
            date(2025, 1, 1),
            date(2025, 1, 2),
        )
    bcb.close()
