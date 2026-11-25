"""Catálogo cerrado e inmutable de indicadores curados (Argentina en Corte 1)."""

from __future__ import annotations

from tigani_broadcast.official_data_charts.models import (
    CatalogEntry,
    Geography,
    SourceTier,
)

_CATALOG: tuple[CatalogEntry, ...] = (
    CatalogEntry(
        catalog_id="ar_bcra_reservas_brutas",
        label="Reservas internacionales brutas (BCRA)",
        provider="bcra",
        source_tier="official_primary",
        geography="AR",
        series_id="1",
        frequency="daily",
        unit="millones de USD",
        description=(
            "Reservas internacionales BRUTAS del BCRA (serie monetaria v4.0). "
            "NO son reservas netas: no restan swaps, DEG ni otros pasivos. "
            "Mapear 'reservas netas' a este ID está prohibido en v0."
        ),
        source_attribution="Fuente: BCRA — Estadísticas Monetarias v4.0",
        aliases=("reservas brutas", "reservas internacionales brutas", "reservas BCRA brutas"),
    ),
    CatalogEntry(
        catalog_id="ar_bcra_dolar_mayorista",
        label="Dólar mayorista (BCRA A 3500)",
        provider="bcra",
        source_tier="official_primary",
        geography="AR",
        series_id="4",
        frequency="daily",
        unit="ARS por USD",
        description="Tipo de cambio de referencia Comunicación A 3500 (mayorista).",
        source_attribution="Fuente: BCRA — Estadísticas Monetarias v4.0",
        aliases=("dólar mayorista", "tipo de cambio A 3500", "TC mayorista"),
    ),
    CatalogEntry(
        catalog_id="ar_bcra_dolar_minorista",
        label="Dólar minorista (BCRA)",
        provider="bcra",
        source_tier="official_primary",
        geography="AR",
        series_id="5",
        frequency="daily",
        unit="ARS por USD",
        description="Tipo de cambio minorista publicado por el BCRA.",
        source_attribution="Fuente: BCRA — Estadísticas Monetarias v4.0",
        aliases=("dólar minorista", "TC minorista"),
    ),
    CatalogEntry(
        catalog_id="ar_bcra_base_monetaria",
        label="Base monetaria (BCRA)",
        provider="bcra",
        source_tier="official_primary",
        geography="AR",
        series_id="15",
        frequency="daily",
        unit="millones de ARS",
        description="Base monetaria en sentido amplio publicada por el BCRA.",
        source_attribution="Fuente: BCRA — Estadísticas Monetarias v4.0",
        aliases=("base monetaria",),
    ),
    CatalogEntry(
        catalog_id="ar_bcra_tasa_badlar",
        label="Tasa BADLAR bancos privados (BCRA)",
        provider="bcra",
        source_tier="official_primary",
        geography="AR",
        series_id="7",
        frequency="daily",
        unit="%",
        description="Tasa de interés BADLAR de bancos privados.",
        source_attribution="Fuente: BCRA — Estadísticas Monetarias v4.0",
        aliases=("BADLAR", "tasa BADLAR"),
    ),
    CatalogEntry(
        catalog_id="ar_bcra_cer",
        label="CER (BCRA)",
        provider="bcra",
        source_tier="official_primary",
        geography="AR",
        series_id="30",
        frequency="daily",
        unit="índice",
        description="Coeficiente de Estabilización de Referencia (CER).",
        source_attribution="Fuente: BCRA — Estadísticas Monetarias v4.0",
        aliases=("CER", "coeficiente CER"),
    ),
    CatalogEntry(
        catalog_id="ar_bcra_uva",
        label="UVA (BCRA)",
        provider="bcra",
        source_tier="official_primary",
        geography="AR",
        series_id="31",
        frequency="daily",
        unit="ARS",
        description="Unidad de Valor Adquisitivo (UVA) publicada por el BCRA.",
        source_attribution="Fuente: BCRA — Estadísticas Monetarias v4.0",
        aliases=("UVA",),
    ),
    CatalogEntry(
        catalog_id="ar_indec_ipc_mensual",
        label="IPC variación mensual (INDEC)",
        provider="indec",
        source_tier="official_primary",
        geography="AR",
        series_id="145.3_INGNACNAL_DICI_M_38",
        frequency="monthly",
        unit="%",
        description=(
            "Variación porcentual mensual del Índice de Precios al Consumidor "
            "nacional (INDEC). Fallback a Series de Tiempo de Datos Argentina."
        ),
        source_attribution="Fuente: INDEC — IPC",
        fallback_provider="datos_ar",
        # IPC Nacional Nivel General (índice) + representation_mode percent_change.
        fallback_series_id="148.3_INIVELNAL_DICI_M_26:percent_change",
        aliases=("IPC mensual", "inflación mensual", "variación mensual IPC"),
    ),
    CatalogEntry(
        catalog_id="ar_indec_ipc_interanual",
        label="IPC variación interanual (INDEC)",
        provider="indec",
        source_tier="official_primary",
        geography="AR",
        series_id="145.3_INGNACNAL_DICI_M_38_ia",
        frequency="monthly",
        unit="%",
        description=(
            "Variación porcentual interanual del IPC nacional (INDEC). "
            "Fallback a Series de Tiempo de Datos Argentina."
        ),
        source_attribution="Fuente: INDEC — IPC",
        fallback_provider="datos_ar",
        fallback_series_id="148.3_INIVELNAL_DICI_M_26:percent_change_a_year_ago",
        aliases=("IPC interanual", "inflación interanual", "inflación año a año"),
    ),
    CatalogEntry(
        catalog_id="ar_indec_emae_mensual",
        label="EMAE variación mensual (INDEC)",
        provider="indec",
        source_tier="official_primary",
        geography="AR",
        series_id="143.3_ING_2004_M_18",
        frequency="monthly",
        unit="%",
        description=(
            "Estimador Mensual de Actividad Económica (EMAE), variación mensual. "
            "Fallback a Series de Tiempo de Datos Argentina."
        ),
        source_attribution="Fuente: INDEC — EMAE",
        fallback_provider="datos_ar",
        # EMAE desestacionalizado (índice base 2004) + percent_change.
        fallback_series_id="143.3_NO_PR_2004_A_31:percent_change",
        aliases=("EMAE", "actividad económica mensual"),
    ),
    CatalogEntry(
        catalog_id="ar_mkt_riesgo_pais",
        label="Riesgo país (Ámbito vía ArgentinaDatos)",
        provider="argentinadatos",
        source_tier="market_secondary",
        geography="AR",
        series_id="riesgo-pais",
        frequency="daily",
        unit="puntos básicos",
        description=("Riesgo país. Sin API oficial primaria: Tier 2 con cita doble obligatoria."),
        source_attribution="Fuente: Ámbito vía ArgentinaDatos",
        aliases=("riesgo país", "country risk", "EMBI"),
    ),
    CatalogEntry(
        catalog_id="ar_mkt_dolar_blue",
        label="Dólar blue (DolarApi vía ArgentinaDatos)",
        provider="argentinadatos",
        source_tier="market_secondary",
        geography="AR",
        series_id="dolares/blue",
        frequency="daily",
        unit="ARS por USD",
        description="Cotización del dólar blue. Tier 2 con cita doble obligatoria.",
        source_attribution="Fuente: DolarApi vía ArgentinaDatos",
        aliases=("dólar blue", "blue"),
    ),
    CatalogEntry(
        catalog_id="ar_mkt_dolar_mep",
        label="Dólar MEP (DolarApi vía ArgentinaDatos)",
        provider="argentinadatos",
        source_tier="market_secondary",
        geography="AR",
        series_id="dolares/bolsa",
        frequency="daily",
        unit="ARS por USD",
        description="Cotización del dólar MEP/bolsa. Tier 2 con cita doble obligatoria.",
        source_attribution="Fuente: DolarApi vía ArgentinaDatos",
        aliases=("dólar MEP", "MEP", "dólar bolsa"),
    ),
    CatalogEntry(
        catalog_id="ar_mkt_dolar_ccl",
        label="Dólar CCL (DolarApi vía ArgentinaDatos)",
        provider="argentinadatos",
        source_tier="market_secondary",
        geography="AR",
        series_id="dolares/contadoconliqui",
        frequency="daily",
        unit="ARS por USD",
        description=(
            "Cotización del dólar contado con liquidación (CCL). Tier 2 con cita doble obligatoria."
        ),
        source_attribution="Fuente: DolarApi vía ArgentinaDatos",
        aliases=("dólar CCL", "CCL", "contado con liqui"),
    ),
    # --- Brasil (BCB SGS) ---
    CatalogEntry(
        catalog_id="br_bcb_selic",
        label="Tasa SELIC meta (BCB)",
        provider="bcb",
        source_tier="official_primary",
        geography="BR",
        series_id="432",
        frequency="daily",
        unit="%",
        description="Meta de la tasa SELIC publicada por el Banco Central do Brasil (SGS 432).",
        source_attribution="Fuente: Banco Central do Brasil — SGS",
        aliases=("SELIC", "tasa SELIC"),
    ),
    CatalogEntry(
        catalog_id="br_bcb_ipca_mensual",
        label="IPCA variación mensual (BCB/IBGE)",
        provider="bcb",
        source_tier="official_primary",
        geography="BR",
        series_id="433",
        frequency="monthly",
        unit="%",
        description="Variación mensual del IPCA (SGS 433).",
        source_attribution="Fuente: Banco Central do Brasil — SGS (IBGE)",
        aliases=("IPCA", "inflación Brasil", "IPCA mensual"),
    ),
    CatalogEntry(
        catalog_id="br_bcb_dolar_ptax",
        label="Dólar PTAX (BCB)",
        provider="bcb",
        source_tier="official_primary",
        geography="BR",
        series_id="1",
        frequency="daily",
        unit="BRL por USD",
        description="Tipo de cambio de referencia PTAX (compra) del BCB (SGS 1).",
        source_attribution="Fuente: Banco Central do Brasil — SGS",
        aliases=("PTAX", "dólar Brasil", "USD/BRL PTAX"),
    ),
    # --- Estados Unidos (FRED) ---
    CatalogEntry(
        catalog_id="us_fred_fed_funds",
        label="Federal Funds Effective Rate (FRED)",
        provider="fred",
        source_tier="official_primary",
        geography="US",
        series_id="FEDFUNDS",
        frequency="monthly",
        unit="%",
        description="Tasa efectiva de fondos federales (FEDFUNDS).",
        source_attribution="Fuente: FRED — Federal Reserve Bank of St. Louis",
        aliases=("fed funds", "tasa Fed", "FFR"),
    ),
    CatalogEntry(
        catalog_id="us_fred_cpi_yoy",
        label="CPI-U índice (FRED CPIAUCSL)",
        provider="fred",
        source_tier="official_primary",
        geography="US",
        series_id="CPIAUCSL",
        frequency="monthly",
        unit="índice 1982-84=100",
        description=(
            "Consumer Price Index for All Urban Consumers (CPIAUCSL). "
            "Serie de índice; la variación interanual se calcula en metrics si hace falta."
        ),
        source_attribution="Fuente: FRED — Federal Reserve Bank of St. Louis",
        aliases=("CPI USA", "inflación USA", "CPIAUCSL"),
    ),
    CatalogEntry(
        catalog_id="us_fred_ust_10y",
        label="Treasury 10 años (FRED DGS10)",
        provider="fred",
        source_tier="official_primary",
        geography="US",
        series_id="DGS10",
        frequency="daily",
        unit="%",
        description="Rendimiento del Treasury a 10 años (DGS10).",
        source_attribution="Fuente: FRED — Federal Reserve Bank of St. Louis",
        aliases=("UST 10Y", "Treasury 10y", "DGS10"),
    ),
    # --- Eurozona (ECB) ---
    CatalogEntry(
        catalog_id="eu_ecb_eur_usd",
        label="Tipo de cambio EUR/USD (BCE)",
        provider="ecb",
        source_tier="official_primary",
        geography="EU",
        series_id="EXR/D.USD.EUR.SP00.A",
        frequency="daily",
        unit="USD por EUR",
        description="Referencia diaria USD por EUR del Banco Central Europeo.",
        source_attribution="Fuente: Banco Central Europeo — Statistical Data Warehouse",
        aliases=("EUR/USD", "euro dólar", "FX ECB"),
    ),
    CatalogEntry(
        catalog_id="eu_ecb_hicp_yoy",
        label="HICP variación interanual (BCE)",
        provider="ecb",
        source_tier="official_primary",
        geography="EU",
        series_id="ICP/M.U2.N.000000.4.ANR",
        frequency="monthly",
        unit="%",
        description="HICP zona euro, variación porcentual anual (flash/final según publicación).",
        source_attribution="Fuente: Banco Central Europeo — Statistical Data Warehouse",
        aliases=("HICP", "inflación eurozona", "IPC Europa"),
    ),
    # --- Global / comparativas (IMF + World Bank) ---
    CatalogEntry(
        catalog_id="global_imf_gdp_growth_arg",
        label="Crecimiento real del PBI Argentina (FMI WEO)",
        provider="imf",
        source_tier="official_primary",
        geography="GLOBAL",
        series_id="NGDP_RPCH/ARG",
        frequency="annual",
        unit="%",
        description="Crecimiento porcentual real del PBI (WEO NGDP_RPCH) para Argentina.",
        source_attribution="Fuente: FMI — World Economic Outlook (DataMapper)",
        aliases=("PBI Argentina FMI", "crecimiento ARG"),
    ),
    CatalogEntry(
        catalog_id="global_imf_gdp_growth_bra",
        label="Crecimiento real del PBI Brasil (FMI WEO)",
        provider="imf",
        source_tier="official_primary",
        geography="GLOBAL",
        series_id="NGDP_RPCH/BRA",
        frequency="annual",
        unit="%",
        description="Crecimiento porcentual real del PBI (WEO NGDP_RPCH) para Brasil.",
        source_attribution="Fuente: FMI — World Economic Outlook (DataMapper)",
        aliases=("PBI Brasil FMI", "crecimiento BRA"),
    ),
    CatalogEntry(
        catalog_id="global_imf_gdp_growth_usa",
        label="Crecimiento real del PBI EE. UU. (FMI WEO)",
        provider="imf",
        source_tier="official_primary",
        geography="GLOBAL",
        series_id="NGDP_RPCH/USA",
        frequency="annual",
        unit="%",
        description="Crecimiento porcentual real del PBI (WEO NGDP_RPCH) para Estados Unidos.",
        source_attribution="Fuente: FMI — World Economic Outlook (DataMapper)",
        aliases=("PBI USA FMI", "crecimiento USA"),
    ),
    CatalogEntry(
        catalog_id="global_wb_gdp_per_capita_arg",
        label="PBI per cápita Argentina (World Bank)",
        provider="worldbank",
        source_tier="official_primary",
        geography="GLOBAL",
        series_id="ARG:NY.GDP.PCAP.CD",
        frequency="annual",
        unit="USD corrientes",
        description="GDP per capita (current US$) — indicador NY.GDP.PCAP.CD para ARG.",
        source_attribution="Fuente: World Bank — World Development Indicators",
        aliases=("PBI per cápita ARG", "GDP per capita Argentina"),
    ),
    # --- ADRs argentinos / ARGT (Stooq, Tier 2) ---
    CatalogEntry(
        catalog_id="us_adr_ggal",
        label="ADR Grupo Galicia (GGAL)",
        provider="us_adrs",
        source_tier="market_secondary",
        geography="US",
        series_id="ggal",
        frequency="daily",
        unit="USD",
        description="ADR de Grupo Financiero Galicia cotizado en NASDAQ.",
        source_attribution="Fuente: NASDAQ vía Stooq",
        aliases=("GGAL", "Galicia ADR"),
    ),
    CatalogEntry(
        catalog_id="us_adr_ypf",
        label="ADR YPF (YPF)",
        provider="us_adrs",
        source_tier="market_secondary",
        geography="US",
        series_id="ypf",
        frequency="daily",
        unit="USD",
        description="ADR de YPF cotizado en NYSE.",
        source_attribution="Fuente: NYSE vía Stooq",
        aliases=("YPF", "YPF ADR"),
    ),
    CatalogEntry(
        catalog_id="us_adr_bma",
        label="ADR Banco Macro (BMA)",
        provider="us_adrs",
        source_tier="market_secondary",
        geography="US",
        series_id="bma",
        frequency="daily",
        unit="USD",
        description="ADR de Banco Macro cotizado en NYSE.",
        source_attribution="Fuente: NYSE vía Stooq",
        aliases=("BMA", "Macro ADR"),
    ),
    CatalogEntry(
        catalog_id="us_adr_bbar",
        label="ADR BBVA Argentina (BBAR)",
        provider="us_adrs",
        source_tier="market_secondary",
        geography="US",
        series_id="bbar",
        frequency="daily",
        unit="USD",
        description="ADR de BBVA Argentina cotizado en NYSE.",
        source_attribution="Fuente: NYSE vía Stooq",
        aliases=("BBAR", "BBVA ADR"),
    ),
    CatalogEntry(
        catalog_id="us_adr_pam",
        label="ADR Pampa Energía (PAM)",
        provider="us_adrs",
        source_tier="market_secondary",
        geography="US",
        series_id="pam",
        frequency="daily",
        unit="USD",
        description="ADR de Pampa Energía cotizado en NYSE.",
        source_attribution="Fuente: NYSE vía Stooq",
        aliases=("PAM", "Pampa ADR"),
    ),
    CatalogEntry(
        catalog_id="us_adr_tgs",
        label="ADR Transportadora de Gas del Sur (TGS)",
        provider="us_adrs",
        source_tier="market_secondary",
        geography="US",
        series_id="tgs",
        frequency="daily",
        unit="USD",
        description="ADR de TGS cotizado en NYSE.",
        source_attribution="Fuente: NYSE vía Stooq",
        aliases=("TGS", "TGS ADR"),
    ),
    CatalogEntry(
        catalog_id="us_adr_argt",
        label="ETF Global X MSCI Argentina (ARGT)",
        provider="us_adrs",
        source_tier="market_secondary",
        geography="US",
        series_id="argt",
        frequency="daily",
        unit="USD",
        description="ETF MSCI Argentina (ARGT) cotizado en NYSE Arca.",
        source_attribution="Fuente: NYSE Arca vía Stooq",
        aliases=("ARGT", "ETF Argentina", "MSCI Argentina"),
    ),
)


def _index_by_catalog_id(entries: tuple[CatalogEntry, ...]) -> dict[str, CatalogEntry]:
    """Indexa por catalog_id y falla si hay duplicados (invariante del catálogo cerrado)."""
    by_id = {entry.catalog_id: entry for entry in entries}
    if len(by_id) != len(entries):
        raise RuntimeError("catalog_id duplicado en el catálogo cerrado")
    return by_id


_BY_ID: dict[str, CatalogEntry] = _index_by_catalog_id(_CATALOG)


class UnknownCatalogEntryError(ValueError):
    """Se pidió un catalog_id que no existe en el registro curado."""


def list_catalog_entries(
    geography: Geography | None = None,
    source_tier: SourceTier | None = None,
) -> tuple[CatalogEntry, ...]:
    """Devuelve entradas del catálogo, opcionalmente filtradas. No muta el registro."""
    entries = _CATALOG
    if geography is not None:
        entries = tuple(e for e in entries if e.geography == geography)
    if source_tier is not None:
        entries = tuple(e for e in entries if e.source_tier == source_tier)
    return entries


def get_catalog_entry(catalog_id: str) -> CatalogEntry:
    """Busca por ID exacto. Fail-closed si no existe."""
    try:
        return _BY_ID[catalog_id]
    except KeyError as exc:
        raise UnknownCatalogEntryError(f"catalog_id desconocido: {catalog_id}") from exc


def is_valid_catalog_id(catalog_id: str) -> bool:
    """True solo si el ID está en el catálogo cerrado."""
    return catalog_id in _BY_ID
