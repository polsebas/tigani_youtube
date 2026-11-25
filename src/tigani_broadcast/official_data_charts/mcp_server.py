"""
Servidor MCP propio (stdio) para catálogo y series oficiales.

En mcp >= 2.x, `FastMCP` fue renombrado a `MCPServer`. Acá se aliasa como
`FastMCP` para conservar el contrato de la SPEC.
"""

from __future__ import annotations

from datetime import date
from typing import Any, cast

from mcp.server.mcpserver import MCPServer as FastMCP

from tigani_broadcast.official_data_charts.catalog import (
    UnknownCatalogEntryError,
    get_catalog_entry,
    is_valid_catalog_id,
    list_catalog_entries,
)
from tigani_broadcast.official_data_charts.metrics import (
    MetricsCalculationError,
    compute_series_metrics,
)
from tigani_broadcast.official_data_charts.models import Geography, SourceTier
from tigani_broadcast.official_data_charts.providers.base import ProviderError
from tigani_broadcast.official_data_charts.providers.factory import build_default_providers
from tigani_broadcast.official_data_charts.providers.fetcher import SeriesFetcher

_GEOGRAPHIES: frozenset[str] = frozenset({"AR", "BR", "US", "EU", "GLOBAL"})
_SOURCE_TIERS: frozenset[str] = frozenset({"official_primary", "market_secondary"})


def build_default_fetcher() -> SeriesFetcher:
    """Fetcher de producción con AR + internacional + ADRs (Corte 5)."""
    return SeriesFetcher(providers=build_default_providers())


def create_mcp_server(fetcher: SeriesFetcher | None = None) -> FastMCP:
    """Fábrica inyectable: tests pasan un SeriesFetcher mockeado (cero red)."""
    resolved = fetcher if fetcher is not None else build_default_fetcher()
    server = FastMCP(
        name="tigani-official-data-charts",
        instructions=(
            "Catálogo cerrado y series oficiales/verificadas de tigani-broadcast. "
            "Las métricas se calculan en Python determinista; el cliente no debe inventar cifras."
        ),
    )

    @server.tool()
    def list_official_indicators(
        geography: str | None = None,
        source_tier: str | None = None,
    ) -> list[dict[str, Any]] | dict[str, str]:
        """Lista entradas del catálogo cerrado, opcionalmente filtradas."""
        if geography is not None and geography not in _GEOGRAPHIES:
            return {"error": f"geography inválida: {geography}"}
        if source_tier is not None and source_tier not in _SOURCE_TIERS:
            return {"error": f"source_tier inválido: {source_tier}"}
        entries = list_catalog_entries(
            geography=cast(Geography | None, geography),
            source_tier=cast(SourceTier | None, source_tier),
        )
        return [
            {
                "catalog_id": e.catalog_id,
                "label": e.label,
                "provider": e.provider,
                "source_tier": e.source_tier,
                "geography": e.geography,
                "frequency": e.frequency,
                "unit": e.unit,
                "description": e.description,
                "source_attribution": e.source_attribution,
            }
            for e in entries
        ]

    @server.tool()
    def get_indicator_metadata(catalog_id: str) -> dict[str, Any]:
        """Detalle de una entrada del catálogo o error claro si no existe."""
        try:
            entry = get_catalog_entry(catalog_id)
        except UnknownCatalogEntryError as exc:
            return {"error": str(exc), "catalog_id": catalog_id}
        return {
            "catalog_id": entry.catalog_id,
            "label": entry.label,
            "provider": entry.provider,
            "source_tier": entry.source_tier,
            "geography": entry.geography,
            "series_id": entry.series_id,
            "frequency": entry.frequency,
            "unit": entry.unit,
            "description": entry.description,
            "source_attribution": entry.source_attribution,
            "fallback_provider": entry.fallback_provider,
            "fallback_series_id": entry.fallback_series_id,
            "aliases": list(entry.aliases),
        }

    @server.tool()
    def fetch_official_series(
        catalog_id: str,
        start_date: str,
        end_date: str,
    ) -> dict[str, Any]:
        """
        Baja la serie del catálogo y calcula métricas en Python.
        Fechas en YYYY-MM-DD. No inventa observaciones.
        """
        if not is_valid_catalog_id(catalog_id):
            return {"error": f"catalog_id desconocido: {catalog_id}", "catalog_id": catalog_id}
        try:
            start = date.fromisoformat(start_date)
            end = date.fromisoformat(end_date)
        except ValueError:
            return {
                "error": "start_date y end_date tienen que usar YYYY-MM-DD",
                "start_date": start_date,
                "end_date": end_date,
            }
        if start > end:
            return {
                "error": "start_date no puede ser mayor que end_date",
                "start_date": start_date,
                "end_date": end_date,
            }
        entry = get_catalog_entry(catalog_id)
        try:
            series = resolved.fetch(entry, start, end)
            metrics = compute_series_metrics(series.observations)
        except (ProviderError, MetricsCalculationError) as exc:
            return {
                "error": str(exc),
                "catalog_id": catalog_id,
                "start_date": start_date,
                "end_date": end_date,
            }
        return {
            "series": series.model_dump(mode="json"),
            "metrics": metrics.model_dump(mode="json"),
        }

    return server


def main() -> None:
    """Entrypoint stdio: `python -m tigani_broadcast.official_data_charts.mcp_server`."""
    server = create_mcp_server()
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
