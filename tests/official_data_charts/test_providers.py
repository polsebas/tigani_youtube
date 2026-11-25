"""Proveedores AR: payloads representativos, signos INDEC y errores HTTP."""

from __future__ import annotations

import json
from datetime import date

import httpx
import pytest

from tigani_broadcast.official_data_charts.catalog import get_catalog_entry
from tigani_broadcast.official_data_charts.models import CatalogEntry
from tigani_broadcast.official_data_charts.providers.argentinadatos import ArgentinaDatosProvider
from tigani_broadcast.official_data_charts.providers.base import (
    ProviderAuthError,
    ProviderRateLimitError,
    ProviderResponseError,
    build_http_client,
)
from tigani_broadcast.official_data_charts.providers.bcra import BCRAProvider
from tigani_broadcast.official_data_charts.providers.datos_ar import DatosArgentinaProvider
from tigani_broadcast.official_data_charts.providers.indec import INDECProvider


def _json_response(request: httpx.Request, payload: object, status: int = 200) -> httpx.Response:
    return httpx.Response(
        status,
        request=request,
        headers={"Content-Type": "application/json"},
        content=json.dumps(payload).encode("utf-8"),
    )


def test_build_http_client_rechaza_client_y_transport() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, request=request))
    with pytest.raises(ValueError, match="client o transport"):
        build_http_client(client=httpx.Client(), transport=transport)


def test_bcra_parsea_results_detalle_ordenado() -> None:
    payload = {
        "status": 200,
        "results": [
            {
                "idVariable": 1,
                "detalle": [
                    {"fecha": "2025-01-03", "valor": 21000},
                    {"fecha": "2025-01-01", "valor": 20000},
                    {"fecha": "2025-01-02", "valor": 20500},
                    {"fecha": "2024-12-31", "valor": 19999},
                ],
            }
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert "/Monetarias/1" in str(request.url)
        assert request.url.params["desde"] == "2025-01-01"
        assert request.url.params["hasta"] == "2025-01-03"
        return _json_response(request, payload)

    provider = BCRAProvider(transport=httpx.MockTransport(handler))
    series = provider.fetch_series(
        get_catalog_entry("ar_bcra_reservas_brutas"),
        date(2025, 1, 1),
        date(2025, 1, 3),
    )
    assert [o.obs_date for o in series.observations] == [
        date(2025, 1, 1),
        date(2025, 1, 2),
        date(2025, 1, 3),
    ]
    assert series.provider == "bcra"
    assert "desde=2025-01-01" in series.source_url
    provider.close()


@pytest.mark.parametrize(
    ("status", "exc_type"),
    [
        (401, ProviderAuthError),
        (429, ProviderRateLimitError),
        (500, ProviderResponseError),
    ],
)
def test_bcra_mapea_errores_http(status: int, exc_type: type[Exception]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, request=request, text="error")

    provider = BCRAProvider(transport=httpx.MockTransport(handler))
    with pytest.raises(exc_type):
        provider.fetch_series(
            get_catalog_entry("ar_bcra_reservas_brutas"),
            date(2025, 1, 1),
            date(2025, 1, 2),
        )
    provider.close()


def test_bcra_timeout_y_json_mal_formado() -> None:
    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    provider = BCRAProvider(transport=httpx.MockTransport(timeout_handler))
    with pytest.raises(ProviderResponseError, match="timeout"):
        provider.fetch_series(
            get_catalog_entry("ar_bcra_reservas_brutas"),
            date(2025, 1, 1),
            date(2025, 1, 2),
        )
    provider.close()

    def bad_json(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, request=request, text="{bad")

    provider = BCRAProvider(transport=httpx.MockTransport(bad_json))
    with pytest.raises(ProviderResponseError, match="JSON inválido"):
        provider.fetch_series(
            get_catalog_entry("ar_bcra_reservas_brutas"),
            date(2025, 1, 1),
            date(2025, 1, 2),
        )
    provider.close()


def test_bcra_fail_closed_sin_observaciones_validas() -> None:
    payload = {"status": 200, "results": [{"idVariable": 1, "detalle": []}]}

    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response(request, payload)

    provider = BCRAProvider(transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderResponseError, match="sin observaciones"):
        provider.fetch_series(
            get_catalog_entry("ar_bcra_reservas_brutas"),
            date(2025, 1, 1),
            date(2025, 1, 2),
        )
    provider.close()


def test_indec_exige_token_sin_llamar_http(monkeypatch) -> None:
    monkeypatch.delenv("INDEC_API_TOKEN", raising=False)
    called = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        called["n"] += 1
        return _json_response(request, [])

    provider = INDECProvider(token="", transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderAuthError, match="INDEC_API_TOKEN"):
        provider.fetch_series(
            get_catalog_entry("ar_indec_ipc_mensual"),
            date(2025, 1, 1),
            date(2025, 3, 1),
        )
    assert called["n"] == 0
    provider.close()


def test_indec_filtra_tidy_y_preserva_signos(monkeypatch) -> None:
    monkeypatch.setenv("INDEC_API_TOKEN", "test-token")
    payload = [
        {
            "periodo": "2025-01",
            "tipo_de_indicador": "Variación porcentual respecto del mes anterior",
            "alcance_nombre": "Nacional",
            "valor": "2.5",
            "signo": "*",
        },
        {
            "periodo": "2025-01",
            "tipo_de_indicador": "Índice de precios",
            "alcance_nombre": "Nacional",
            "valor": "999.0",
            "signo": None,
        },
        {
            "periodo": "2025-02",
            "tipo_de_indicador": "Variación porcentual respecto del mes anterior",
            "alcance_nombre": "GBA",
            "valor": "3.0",
        },
        {
            "periodo": "2025-02",
            "tipo_de_indicador": "Variación porcentual respecto del mes anterior",
            "alcance_nombre": "Nacional",
            "valor": "...",
            "signo": None,
        },
        {
            "periodo": "2025-03",
            "tipo_de_indicador": "Variación porcentual respecto del mes anterior",
            "alcance_nombre": "Nacional",
            "valor": "2,2**",
        },
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-token"
        assert "ipc_nacional_tidy" in request.url.path
        assert request.url.params["tipo_de_indicador"].startswith("eq.Variaci")
        return _json_response(request, payload)

    provider = INDECProvider(token="test-token", transport=httpx.MockTransport(handler))
    series = provider.fetch_series(
        get_catalog_entry("ar_indec_ipc_mensual"),
        date(2025, 1, 1),
        date(2025, 3, 31),
    )
    assert len(series.observations) == 3
    assert series.observations[0].value == 2.5
    assert series.observations[0].flag == "*"
    assert series.observations[1].value is None
    assert series.observations[1].flag == "..."
    assert series.observations[2].value == 2.2
    assert series.observations[2].flag == "**"
    provider.close()


def test_indec_http_401() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, request=request, text="no")

    provider = INDECProvider(token="bad", transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderAuthError):
        provider.fetch_series(
            get_catalog_entry("ar_indec_ipc_mensual"),
            date(2025, 1, 1),
            date(2025, 1, 31),
        )
    provider.close()


def test_datos_ar_parsea_data_con_none_y_escala_percent_change() -> None:
    payload = {
        "data": [
            ["2025-01-01", 0.025],
            ["2025-02-01", None],
            ["2025-03-01", 0.031],
        ]
    }
    series_id = "148.3_INIVELNAL_DICI_M_26:percent_change"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["User-Agent"].startswith("tigani-broadcast/")
        assert request.url.params["ids"] == series_id
        assert request.url.params["format"] == "json"
        assert request.url.params["limit"] == "5000"
        assert request.url.params["start_date"] == "2025-01-01"
        assert request.url.params["end_date"] == "2025-03-31"
        return _json_response(request, payload)

    entry = get_catalog_entry("ar_indec_ipc_mensual").model_copy(
        update={
            "provider": "datos_ar",
            "series_id": series_id,
            "fallback_provider": None,
            "fallback_series_id": None,
        }
    )
    provider = DatosArgentinaProvider(transport=httpx.MockTransport(handler))
    series = provider.fetch_series(entry, date(2025, 1, 1), date(2025, 3, 31))
    assert series.provider == "datos_ar"
    assert series.observations[0].value == pytest.approx(2.5)
    assert series.observations[1].value is None
    assert series.observations[2].value == pytest.approx(3.1)
    provider.close()


def test_datos_ar_escala_percent_change_a_year_ago() -> None:
    payload = {"data": [["2025-01-01", 0.845], ["2025-02-01", 0.669]]}
    series_id = "148.3_INIVELNAL_DICI_M_26:percent_change_a_year_ago"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["ids"] == series_id
        return _json_response(request, payload)

    entry = get_catalog_entry("ar_indec_ipc_interanual").model_copy(
        update={
            "provider": "datos_ar",
            "series_id": series_id,
            "fallback_provider": None,
            "fallback_series_id": None,
        }
    )
    provider = DatosArgentinaProvider(transport=httpx.MockTransport(handler))
    series = provider.fetch_series(entry, date(2025, 1, 1), date(2025, 2, 28))
    assert [o.value for o in series.observations] == [
        pytest.approx(84.5),
        pytest.approx(66.9),
    ]
    provider.close()


def test_datos_ar_http_400_incluye_detalle_sanitizado() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response(
            request,
            {
                "errors": [
                    {
                        "error": "Serie inexistente: fake_id",
                        "hint": "Authorization: Bearer super-secret-token",
                    }
                ]
            },
            status=400,
        )

    entry = get_catalog_entry("ar_indec_ipc_mensual").model_copy(
        update={
            "provider": "datos_ar",
            "series_id": get_catalog_entry("ar_indec_ipc_mensual").fallback_series_id,
            "fallback_provider": None,
            "fallback_series_id": None,
        }
    )
    provider = DatosArgentinaProvider(transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderResponseError, match=r"HTTP 400 — .*Serie inexistente") as exc_info:
        provider.fetch_series(entry, date(2025, 1, 1), date(2025, 2, 28))
    message = str(exc_info.value)
    assert "super-secret-token" not in message
    assert "***" in message
    provider.close()


def test_argentinadatos_riesgo_pais_y_dolares() -> None:
    riesgo = [
        {"fecha": "2025-01-01", "valor": 800},
        {"fecha": "2025-01-03", "valor": 820},
        {"fecha": "2024-12-31", "valor": 790},
    ]
    dolares = [
        {"casa": "blue", "fecha": "2025-01-01", "compra": 1000, "venta": 1020},
        {"casa": "blue", "fecha": "2025-01-02", "compra": 1010, "venta": 1030},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/finanzas/indices/riesgo-pais"):
            return _json_response(request, riesgo)
        if url.endswith("/cotizaciones/dolares/blue"):
            return _json_response(request, dolares)
        if url.endswith("/cotizaciones/dolares/bolsa"):
            return _json_response(request, dolares)
        if url.endswith("/cotizaciones/dolares/contadoconliqui"):
            return _json_response(request, dolares)
        return httpx.Response(404, request=request, text="no")

    transport = httpx.MockTransport(handler)
    provider = ArgentinaDatosProvider(transport=transport)

    riesgo_series = provider.fetch_series(
        get_catalog_entry("ar_mkt_riesgo_pais"),
        date(2025, 1, 1),
        date(2025, 1, 31),
    )
    assert [o.value for o in riesgo_series.observations] == [800.0, 820.0]
    assert "Ámbito vía ArgentinaDatos" in riesgo_series.source_attribution

    blue = provider.fetch_series(
        get_catalog_entry("ar_mkt_dolar_blue"),
        date(2025, 1, 1),
        date(2025, 1, 31),
    )
    assert [o.value for o in blue.observations] == [1020.0, 1030.0]

    mep = provider.fetch_series(
        get_catalog_entry("ar_mkt_dolar_mep"),
        date(2025, 1, 1),
        date(2025, 1, 31),
    )
    assert mep.series_id == "dolares/bolsa"

    ccl = provider.fetch_series(
        get_catalog_entry("ar_mkt_dolar_ccl"),
        date(2025, 1, 1),
        date(2025, 1, 31),
    )
    assert ccl.series_id == "dolares/contadoconliqui"
    provider.close()


def test_bcra_y_datos_ar_rechazan_provider_o_rango_invalido() -> None:
    bcra = BCRAProvider(transport=httpx.MockTransport(lambda r: _json_response(r, {})))
    with pytest.raises(ProviderResponseError, match="no corresponde"):
        bcra.fetch_series(
            get_catalog_entry("ar_indec_ipc_mensual"),
            date(2025, 1, 1),
            date(2025, 1, 2),
        )
    with pytest.raises(ProviderResponseError, match="start_date"):
        bcra.fetch_series(
            get_catalog_entry("ar_bcra_cer"),
            date(2025, 2, 1),
            date(2025, 1, 1),
        )
    bcra.close()

    datos = DatosArgentinaProvider(transport=httpx.MockTransport(lambda r: _json_response(r, {})))
    with pytest.raises(ProviderResponseError, match="start_date"):
        datos.fetch_series(
            get_catalog_entry("ar_indec_ipc_mensual").model_copy(
                update={
                    "provider": "datos_ar",
                    "fallback_provider": None,
                    "fallback_series_id": None,
                }
            ),
            date(2025, 2, 1),
            date(2025, 1, 1),
        )
    datos.close()


def test_bcra_payload_mal_formado() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response(request, {"results": [{"detalle": "no-lista"}]})

    provider = BCRAProvider(transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderResponseError, match="detalle"):
        provider.fetch_series(
            get_catalog_entry("ar_bcra_cer"),
            date(2025, 1, 1),
            date(2025, 1, 2),
        )
    provider.close()


def test_argentinadatos_rechaza_official_primary() -> None:
    entry = CatalogEntry(
        catalog_id="fake",
        label="fake",
        provider="argentinadatos",
        source_tier="official_primary",
        geography="AR",
        series_id="riesgo-pais",
        frequency="daily",
        unit="pb",
        description="x",
        source_attribution="x",
    )
    transport = httpx.MockTransport(lambda r: _json_response(r, []))
    provider = ArgentinaDatosProvider(transport=transport)
    with pytest.raises(ProviderResponseError, match="market_secondary"):
        provider.fetch_series(entry, date(2025, 1, 1), date(2025, 1, 2))
    provider.close()
