"""Fábrica de proveedores por defecto para CLI / MCP / SeriesFetcher."""

from __future__ import annotations

from tigani_broadcast.official_data_charts.models import ProviderId
from tigani_broadcast.official_data_charts.providers.argentinadatos import (
    ArgentinaDatosProvider,
)
from tigani_broadcast.official_data_charts.providers.base import DataProvider
from tigani_broadcast.official_data_charts.providers.bcra import BCRAProvider
from tigani_broadcast.official_data_charts.providers.datos_ar import DatosArgentinaProvider
from tigani_broadcast.official_data_charts.providers.indec import INDECProvider
from tigani_broadcast.official_data_charts.providers.international import (
    BCBProvider,
    ECBProvider,
    FREDProvider,
    IMFProvider,
    WorldBankProvider,
)
from tigani_broadcast.official_data_charts.providers.us_adrs import USAdrsProvider


def build_default_providers() -> dict[ProviderId, DataProvider]:
    """Registra los 10 conectores curados (AR + internacional + ADRs)."""
    return {
        "bcra": BCRAProvider(),
        "indec": INDECProvider(),
        "datos_ar": DatosArgentinaProvider(),
        "argentinadatos": ArgentinaDatosProvider(),
        "bcb": BCBProvider(),
        "imf": IMFProvider(),
        "ecb": ECBProvider(),
        "worldbank": WorldBankProvider(),
        "fred": FREDProvider(),
        "us_adrs": USAdrsProvider(),
    }
