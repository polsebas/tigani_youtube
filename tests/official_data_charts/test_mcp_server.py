"""Servidor MCP: herramientas tipadas con SeriesFetcher fake (cero red)."""

from __future__ import annotations

import asyncio
import json
from datetime import date

import pytest

from tigani_broadcast.official_data_charts.catalog import get_catalog_entry
from tigani_broadcast.official_data_charts.mcp_server import create_mcp_server
from tigani_broadcast.official_data_charts.models import (
    SeriesData,
    SeriesObservation,
)
from tigani_broadcast.official_data_charts.providers.base import ProviderError


class _FakeFetcher:
    def __init__(self, series: SeriesData | None = None, error: Exception | None = None) -> None:
        self.series = series
        self.error = error
        self.calls: list[tuple[str, date, date]] = []

    def fetch(self, entry, start_date: date, end_date: date) -> SeriesData:  # noqa: ANN001
        self.calls.append((entry.catalog_id, start_date, end_date))
        if self.error is not None:
            raise self.error
        assert self.series is not None
        return self.series


def _tool_payload(result: object) -> object:
    """mcp 2.x: dicts en structured_content; listas en structured_content.result."""
    structured = getattr(result, "structured_content", None)
    if isinstance(structured, dict):
        if "result" in structured and len(structured) == 1:
            return structured["result"]
        return structured
    content = getattr(result, "content", None)
    assert content, "CallToolResult sin content"
    if len(content) == 1:
        return json.loads(content[0].text)
    return [json.loads(item.text) for item in content]


def _call(server: object, name: str, arguments: dict) -> object:
    return _tool_payload(asyncio.run(server.call_tool(name, arguments)))  # type: ignore[attr-defined]


def test_list_official_indicators_y_filtro() -> None:
    server = create_mcp_server(fetcher=_FakeFetcher())  # type: ignore[arg-type]
    all_items = _call(server, "list_official_indicators", {})
    assert isinstance(all_items, list)
    assert len(all_items) == 33
    assert {row["catalog_id"] for row in all_items} >= {
        "ar_bcra_reservas_brutas",
        "ar_mkt_riesgo_pais",
        "br_bcb_selic",
        "us_adr_ggal",
        "global_imf_gdp_growth_arg",
    }

    market = _call(
        server,
        "list_official_indicators",
        {"geography": "AR", "source_tier": "market_secondary"},
    )
    assert isinstance(market, list)
    assert all(row["source_tier"] == "market_secondary" for row in market)

    bad = _call(server, "list_official_indicators", {"geography": "ZZ"})
    assert isinstance(bad, dict)
    assert "error" in bad
    bad_tier = _call(server, "list_official_indicators", {"source_tier": "rumor"})
    assert isinstance(bad_tier, dict)
    assert "source_tier" in bad_tier["error"]


def test_get_indicator_metadata_ok_y_error() -> None:
    server = create_mcp_server(fetcher=_FakeFetcher())  # type: ignore[arg-type]
    meta = _call(server, "get_indicator_metadata", {"catalog_id": "ar_bcra_cer"})
    assert isinstance(meta, dict)
    assert meta["catalog_id"] == "ar_bcra_cer"
    assert meta["provider"] == "bcra"
    assert "aliases" in meta

    missing = _call(server, "get_indicator_metadata", {"catalog_id": "no_existe"})
    assert isinstance(missing, dict)
    assert "error" in missing
    assert missing["catalog_id"] == "no_existe"


def test_fetch_official_series_devuelve_series_y_metrics() -> None:
    series = SeriesData(
        catalog_id="ar_indec_ipc_mensual",
        provider="indec",
        source_tier="official_primary",
        series_id="145.3_INGNACNAL_DICI_M_38",
        source_url="https://api.indec.gob.ar/v1/ipc_nacional_tidy",
        source_attribution="Fuente: INDEC — IPC",
        unit="%",
        frequency="monthly",
        observations=[
            SeriesObservation(obs_date=date(2025, 1, 1), value=2.5),
            SeriesObservation(obs_date=date(2025, 2, 1), value=2.7),
        ],
    )
    fetcher = _FakeFetcher(series=series)
    server = create_mcp_server(fetcher=fetcher)  # type: ignore[arg-type]
    payload = _call(
        server,
        "fetch_official_series",
        {
            "catalog_id": "ar_indec_ipc_mensual",
            "start_date": "2025-01-01",
            "end_date": "2025-02-28",
        },
    )
    assert isinstance(payload, dict)
    assert "series" in payload and "metrics" in payload
    assert payload["metrics"]["latest_value"] == 2.7
    assert payload["metrics"]["absolute_change"] == pytest.approx(0.2)
    assert fetcher.calls[0][0] == "ar_indec_ipc_mensual"


def test_fetch_official_series_catalog_inexistente_y_fechas_invalidas() -> None:
    server = create_mcp_server(fetcher=_FakeFetcher())  # type: ignore[arg-type]
    missing = _call(
        server,
        "fetch_official_series",
        {
            "catalog_id": "no_existe",
            "start_date": "2025-01-01",
            "end_date": "2025-01-31",
        },
    )
    assert isinstance(missing, dict)
    assert "error" in missing

    bad_dates = _call(
        server,
        "fetch_official_series",
        {
            "catalog_id": "ar_bcra_cer",
            "start_date": "01-01-2025",
            "end_date": "2025-01-31",
        },
    )
    assert isinstance(bad_dates, dict)
    assert "YYYY-MM-DD" in bad_dates["error"]

    inverted = _call(
        server,
        "fetch_official_series",
        {
            "catalog_id": "ar_bcra_cer",
            "start_date": "2025-02-01",
            "end_date": "2025-01-01",
        },
    )
    assert isinstance(inverted, dict)
    assert "start_date no puede ser mayor" in inverted["error"]


def test_fetch_official_series_propaga_error_de_fetcher() -> None:
    fetcher = _FakeFetcher(error=ProviderError("timeout BCRA"))
    server = create_mcp_server(fetcher=fetcher)  # type: ignore[arg-type]
    payload = _call(
        server,
        "fetch_official_series",
        {
            "catalog_id": get_catalog_entry("ar_bcra_cer").catalog_id,
            "start_date": "2025-01-01",
            "end_date": "2025-01-31",
        },
    )
    assert isinstance(payload, dict)
    assert payload["error"] == "timeout BCRA"
