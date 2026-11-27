"""Bandas de gestión: intersección, recorte a publish_date y scope Argentina."""

from datetime import date

from tigani_broadcast.official_data_charts.regimes import (
    ARGENTINE_PRESIDENTIAL_REGIMES,
    resolve_regime_bands,
)


def test_catalogo_tiene_apellidos_y_fechas_cerradas() -> None:
    labels = [r.label for r in ARGENTINE_PRESIDENTIAL_REGIMES]
    assert labels == [
        "Macri (2015–19)",
        "Fernández (2019–23)",
        "Milei (2023–act.)",
    ]
    assert ARGENTINE_PRESIDENTIAL_REGIMES[0].start_date == date(2015, 12, 10)
    assert ARGENTINE_PRESIDENTIAL_REGIMES[0].end_date == date(2019, 12, 9)
    assert ARGENTINE_PRESIDENTIAL_REGIMES[1].start_date == date(2019, 12, 10)
    assert ARGENTINE_PRESIDENTIAL_REGIMES[1].end_date == date(2023, 12, 9)
    assert ARGENTINE_PRESIDENTIAL_REGIMES[2].start_date == date(2023, 12, 10)
    assert ARGENTINE_PRESIDENTIAL_REGIMES[2].end_date is None


def test_scope_no_argentina_devuelve_vacio() -> None:
    bands = resolve_regime_bands(
        date(2018, 1, 1),
        date(2024, 1, 1),
        publish_date=date(2025, 12, 11),
        scope="US",
    )
    assert bands == []


def test_ventana_corta_una_sola_gestion_sin_include_single() -> None:
    bands = resolve_regime_bands(
        date(2024, 1, 1),
        date(2025, 6, 1),
        publish_date=date(2025, 12, 11),
        scope="argentina",
    )
    assert bands == []


def test_include_single_emite_una_banda() -> None:
    bands = resolve_regime_bands(
        date(2024, 1, 1),
        date(2025, 6, 1),
        publish_date=date(2025, 12, 11),
        scope="argentina",
        include_single=True,
    )
    assert len(bands) == 1
    assert bands[0].label == "Milei (2023–act.)"
    assert bands[0].start_date == date(2024, 1, 1)
    assert bands[0].end_date == date(2025, 6, 1)


def test_ventana_larga_cruza_dos_gestiones() -> None:
    bands = resolve_regime_bands(
        date(2022, 1, 1),
        date(2024, 6, 1),
        publish_date=date(2025, 12, 11),
        scope="AR",
    )
    assert [b.label for b in bands] == [
        "Fernández (2019–23)",
        "Milei (2023–act.)",
    ]
    assert bands[0].start_date == date(2022, 1, 1)
    assert bands[0].end_date == date(2023, 12, 9)
    assert bands[1].start_date == date(2023, 12, 10)
    assert bands[1].end_date == date(2024, 6, 1)


def test_recorte_estricto_a_publish_date_sin_fechas_futuras() -> None:
    bands = resolve_regime_bands(
        date(2018, 1, 1),
        date(2030, 1, 1),
        publish_date=date(2024, 6, 15),
        scope="argentina",
    )
    assert len(bands) >= 2
    for band in bands:
        assert band.end_date <= date(2024, 6, 15)
        assert band.start_date <= date(2024, 6, 15)
    assert bands[-1].label == "Milei (2023–act.)"
    assert bands[-1].end_date == date(2024, 6, 15)


def test_publish_date_antes_de_milei_no_incluye_gestion_futura() -> None:
    bands = resolve_regime_bands(
        date(2018, 1, 1),
        date(2025, 1, 1),
        publish_date=date(2023, 6, 1),
        scope="argentina",
    )
    labels = [b.label for b in bands]
    assert "Milei (2023–act.)" not in labels
    assert "Macri (2015–19)" in labels
    assert "Fernández (2019–23)" in labels
    assert all(b.end_date <= date(2023, 6, 1) for b in bands)


def test_ventana_invertida_devuelve_vacio() -> None:
    bands = resolve_regime_bands(
        date(2025, 1, 1),
        date(2024, 1, 1),
        publish_date=date(2025, 12, 11),
        scope="argentina",
    )
    assert bands == []
