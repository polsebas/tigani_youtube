"""Catálogo cerrado: filtros, lookup fail-closed e invariantes de curación."""

import pytest

from tigani_broadcast.official_data_charts.catalog import (
    UnknownCatalogEntryError,
    _index_by_catalog_id,
    get_catalog_entry,
    is_valid_catalog_id,
    list_catalog_entries,
)
from tigani_broadcast.official_data_charts.models import CatalogEntry


def test_list_catalog_entries_devuelve_todos_sin_filtro() -> None:
    entries = list_catalog_entries()
    assert len(entries) == 37
    ids = [e.catalog_id for e in entries]
    assert "ar_bcra_reservas_brutas" in ids
    assert "ar_indec_ipc_mensual" in ids
    assert "ar_mkt_riesgo_pais" in ids
    assert "br_bcb_selic" in ids
    assert "us_fred_fed_funds" in ids
    assert "eu_ecb_eur_usd" in ids
    assert "global_imf_gdp_growth_arg" in ids
    assert "us_adr_ggal" in ids


def test_catalog_ids_son_unicos() -> None:
    ids = [e.catalog_id for e in list_catalog_entries()]
    assert len(ids) == len(set(ids))


def test_geografias_internacionales_curadas() -> None:
    by_geo = {
        geo: {e.catalog_id for e in list_catalog_entries(geography=geo)}
        for geo in ("AR", "BR", "US", "EU", "GLOBAL")
    }
    assert "ar_bcra_reservas_brutas" in by_geo["AR"]
    assert by_geo["BR"] == {
        "br_bcb_selic",
        "br_bcb_ipca_mensual",
        "br_bcb_dolar_ptax",
    }
    assert "us_fred_fed_funds" in by_geo["US"]
    assert "us_adr_ggal" in by_geo["US"]
    assert by_geo["EU"] == {"eu_ecb_eur_usd", "eu_ecb_hicp_yoy"}
    assert by_geo["GLOBAL"] == {
        "global_imf_gdp_growth_arg",
        "global_imf_gdp_growth_bra",
        "global_imf_gdp_growth_usa",
        "global_wb_gdp_per_capita_arg",
    }


def test_list_filtra_por_geography_y_source_tier() -> None:
    ar = list_catalog_entries(geography="AR")
    assert ar
    assert all(e.geography == "AR" for e in ar)
    assert len(ar) == 18

    primary = list_catalog_entries(source_tier="official_primary")
    assert primary
    assert all(e.source_tier == "official_primary" for e in primary)

    market = list_catalog_entries(geography="AR", source_tier="market_secondary")
    assert {e.catalog_id for e in market} == {
        "ar_mkt_riesgo_pais",
        "ar_mkt_dolar_blue",
        "ar_mkt_dolar_mep",
        "ar_mkt_dolar_ccl",
    }


def test_argentinadatos_solo_en_market_secondary() -> None:
    for entry in list_catalog_entries():
        if entry.provider == "argentinadatos":
            assert entry.source_tier == "market_secondary"
            assert "vía ArgentinaDatos" in entry.source_attribution


def test_us_adrs_solo_market_secondary() -> None:
    adrs = [e for e in list_catalog_entries() if e.provider == "us_adrs"]
    assert len(adrs) == 7
    for entry in adrs:
        assert entry.source_tier == "market_secondary"
        assert entry.geography == "US"
        assert "vía Stooq" in entry.source_attribution


def test_bcra_e_indec_son_official_primary() -> None:
    for entry in list_catalog_entries():
        if entry.provider in {"bcra", "indec", "bcb", "fred", "ecb", "imf", "worldbank"}:
            assert entry.source_tier == "official_primary"


def test_indec_tiene_fallback_a_datos_ar() -> None:
    expected = {
        "ar_indec_ipc_mensual": "148.3_INIVELNAL_DICI_M_26:percent_change",
        "ar_indec_ipc_interanual": "148.3_INIVELNAL_DICI_M_26:percent_change_a_year_ago",
        "ar_indec_emae_mensual": "143.3_NO_PR_2004_A_31:percent_change",
    }
    for catalog_id, fallback_id in expected.items():
        entry = get_catalog_entry(catalog_id)
        assert entry.fallback_provider == "datos_ar"
        assert entry.fallback_series_id == fallback_id


def test_reservas_brutas_aclara_que_no_son_netas() -> None:
    entry = get_catalog_entry("ar_bcra_reservas_brutas")
    assert "NO son reservas netas" in entry.description
    assert "brutas" in entry.description.lower()


def test_get_catalog_entry_ok_y_is_valid() -> None:
    entry = get_catalog_entry("ar_mkt_dolar_mep")
    assert entry.provider == "argentinadatos"
    assert is_valid_catalog_id("ar_mkt_dolar_mep") is True
    assert is_valid_catalog_id("no_existe") is False


def test_get_catalog_entry_desconocido_falla_cerrado() -> None:
    with pytest.raises(UnknownCatalogEntryError, match="catalog_id desconocido: fake_id"):
        get_catalog_entry("fake_id")


def test_list_devuelve_tupla_inmutable_estable() -> None:
    first = list_catalog_entries()
    second = list_catalog_entries()
    assert first == second
    assert isinstance(first, tuple)


def test_index_rechaza_catalog_id_duplicado() -> None:
    entry = get_catalog_entry("ar_bcra_cer")
    with pytest.raises(RuntimeError, match="catalog_id duplicado"):
        _index_by_catalog_id((entry, entry))


def test_catalog_entry_type_roundtrip() -> None:
    assert isinstance(get_catalog_entry("ar_bcra_uva"), CatalogEntry)


def test_build_default_providers_registra_internacionales() -> None:
    from tigani_broadcast.official_data_charts.providers import build_default_providers

    providers = build_default_providers()
    assert set(providers) >= {
        "bcra",
        "indec",
        "datos_ar",
        "argentinadatos",
        "bcb",
        "imf",
        "ecb",
        "worldbank",
        "fred",
        "us_adrs",
    }
