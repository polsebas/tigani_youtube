"""Métricas deterministas: orden, flags INDEC, bordes, narrativa editorial."""

from datetime import date
from math import prod

import pytest

from tigani_broadcast.official_data_charts.metrics import (
    MetricsCalculationError,
    _value_date_key,
    build_chart_narrative,
    compute_series_metrics,
)
from tigani_broadcast.official_data_charts.models import SeriesObservation


def _geometric(rates: list[float]) -> float:
    return (prod(1.0 + r / 100.0 for r in rates) - 1.0) * 100.0


def _monthly(
    pairs: list[tuple[int, int, float]],
) -> list[SeriesObservation]:
    return [
        SeriesObservation(obs_date=date(year, month, 1), value=value)
        for year, month, value in pairs
    ]


def test_compute_ordena_sin_mutar_y_calcula_cambios() -> None:
    original = [
        SeriesObservation(obs_date=date(2025, 1, 3), value=110.0),
        SeriesObservation(obs_date=date(2025, 1, 1), value=100.0),
        SeriesObservation(obs_date=date(2025, 1, 2), value=105.0),
    ]
    snapshot = list(original)

    metrics = compute_series_metrics(original)

    assert original == snapshot
    assert metrics.observation_count == 3
    assert metrics.valid_count == 3
    assert metrics.start_date == date(2025, 1, 1)
    assert metrics.end_date == date(2025, 1, 3)
    assert metrics.first_value == 100.0
    assert metrics.latest_value == 110.0
    assert metrics.min_value == 100.0
    assert metrics.min_date == date(2025, 1, 1)
    assert metrics.max_value == 110.0
    assert metrics.max_date == date(2025, 1, 3)
    assert metrics.absolute_change == 10.0
    assert metrics.percent_change == 10.0
    assert metrics.has_provisional_flags is False
    assert metrics.flags_present == []


def test_value_none_no_entra_al_calculo_pero_cuenta_en_observation_count() -> None:
    metrics = compute_series_metrics(
        [
            SeriesObservation(obs_date=date(2025, 2, 1), value=None, flag="..."),
            SeriesObservation(obs_date=date(2025, 2, 2), value=50.0),
            SeriesObservation(obs_date=date(2025, 2, 3), value=None, flag="s"),
            SeriesObservation(obs_date=date(2025, 2, 4), value=55.0, flag="*"),
        ]
    )
    assert metrics.observation_count == 4
    assert metrics.valid_count == 2
    assert metrics.first_value == 50.0
    assert metrics.latest_value == 55.0
    assert metrics.absolute_change == 5.0
    assert metrics.percent_change == 10.0
    assert metrics.flags_present == ["*", "...", "s"]
    assert metrics.has_provisional_flags is True


def test_un_solo_punto_valido_deja_cambios_en_none() -> None:
    metrics = compute_series_metrics(
        [SeriesObservation(obs_date=date(2025, 3, 1), value=2.5, flag="e")]
    )
    assert metrics.valid_count == 1
    assert metrics.absolute_change is None
    assert metrics.percent_change is None
    assert metrics.has_provisional_flags is True
    assert metrics.flags_present == ["e"]


def test_first_value_cero_deja_percent_change_none() -> None:
    metrics = compute_series_metrics(
        [
            SeriesObservation(obs_date=date(2025, 4, 1), value=0.0),
            SeriesObservation(obs_date=date(2025, 4, 2), value=10.0),
        ]
    )
    assert metrics.absolute_change == 10.0
    assert metrics.percent_change is None


def test_percent_change_con_first_negativo_usa_abs() -> None:
    metrics = compute_series_metrics(
        [
            SeriesObservation(obs_date=date(2025, 5, 1), value=-50.0),
            SeriesObservation(obs_date=date(2025, 5, 2), value=-40.0),
        ]
    )
    assert metrics.absolute_change == 10.0
    assert metrics.percent_change == 20.0


def test_signos_provisorios_indec() -> None:
    metrics = compute_series_metrics(
        [
            SeriesObservation(obs_date=date(2025, 6, 1), value=1.0, flag="**"),
            SeriesObservation(obs_date=date(2025, 6, 2), value=2.0, flag="i"),
            SeriesObservation(obs_date=date(2025, 6, 3), value=1.5, flag="*"),
        ]
    )
    assert metrics.flags_present == ["*", "**", "i"]
    assert metrics.has_provisional_flags is True
    assert metrics.min_value == 1.0
    assert metrics.max_value == 2.0


def test_sin_valores_validos_falla_cerrado() -> None:
    with pytest.raises(MetricsCalculationError, match="no hay observaciones"):
        compute_series_metrics([])
    with pytest.raises(MetricsCalculationError, match="no hay observaciones"):
        compute_series_metrics(
            [
                SeriesObservation(obs_date=date(2025, 7, 1), value=None, flag="s"),
                SeriesObservation(obs_date=date(2025, 7, 2), value=None),
            ]
        )


def test_value_date_key_rechaza_value_none() -> None:
    with pytest.raises(AssertionError, match="value numérico"):
        _value_date_key(SeriesObservation(obs_date=date(2025, 1, 1), value=None))


def test_empate_en_min_max_elige_fecha_mas_temprana() -> None:
    metrics = compute_series_metrics(
        [
            SeriesObservation(obs_date=date(2025, 8, 2), value=10.0),
            SeriesObservation(obs_date=date(2025, 8, 1), value=10.0),
            SeriesObservation(obs_date=date(2025, 8, 3), value=10.0),
        ]
    )
    assert metrics.min_date == date(2025, 8, 1)
    assert metrics.max_date == date(2025, 8, 1)
    assert metrics.absolute_change == 0.0
    assert metrics.percent_change == 0.0


def test_narrative_ipc_mensual_delta_pp_ytd_y_interanual() -> None:
    # "subió al 2,2 %" tras 1,9 %: delta +0,3 p.p.; YTD e interanual geométricos.
    rates = [
        (2024, 12, 2.7),
        (2025, 1, 2.2),
        (2025, 2, 2.4),
        (2025, 3, 3.7),
        (2025, 4, 2.8),
        (2025, 5, 1.5),
        (2025, 6, 1.6),
        (2025, 7, 1.9),
        (2025, 8, 1.9),
        (2025, 9, 1.6),
        (2025, 10, 1.9),
        (2025, 11, 2.2),
    ]
    points = _monthly(rates)
    narrative = build_chart_narrative(
        points,
        unit="%",
        frequency="monthly",
        mode="trend_with_callout",
        publish_date=date(2025, 11, 30),
        scope="argentina",
        is_monthly_pct_change=True,
    )

    assert narrative.anchor_date == "2025-11-01"
    assert narrative.delta_direction == "up"
    assert narrative.headline_badge is not None
    assert "+0,3 p.p." in narrative.headline_badge
    assert "▲" in narrative.headline_badge

    labels = [kpi.label for kpi in narrative.kpis]
    assert "Período anterior" in labels
    assert "Acum. año (YTD)" in labels
    assert "Interanual (12m)" in labels

    ytd_rates = [v for _y, _m, v in rates if _y == 2025]
    yoy_rates = [v for _y, _m, v in rates]
    expected_ytd = _geometric(ytd_rates)
    expected_yoy = _geometric(yoy_rates)

    by_label = {kpi.label: kpi for kpi in narrative.kpis}
    assert by_label["Período anterior"].formatted_value == "1,9%"
    assert by_label["Acum. año (YTD)"].formatted_value == _fmt_pct_like(expected_ytd)
    assert by_label["Interanual (12m)"].formatted_value == _fmt_pct_like(expected_yoy)


def _fmt_pct_like(value: float) -> str:
    sign = "+" if value >= 0 else "−"
    return f"{sign}{abs(value):.1f} %".replace(".", ",")


def test_narrative_diciembre_anti_redundancia_ytd_igual_interanual() -> None:
    rates = [
        (2025, 1, 2.0),
        (2025, 2, 2.0),
        (2025, 3, 2.0),
        (2025, 4, 2.0),
        (2025, 5, 2.0),
        (2025, 6, 2.0),
        (2025, 7, 2.0),
        (2025, 8, 2.0),
        (2025, 9, 2.0),
        (2025, 10, 2.0),
        (2025, 11, 2.0),
        (2025, 12, 2.0),
    ]
    narrative = build_chart_narrative(
        _monthly(rates),
        unit="%",
        frequency="monthly",
        mode="trend_with_callout",
        publish_date=date(2025, 12, 31),
        scope="argentina",
        is_monthly_pct_change=True,
    )
    labels = [kpi.label for kpi in narrative.kpis]
    assert "Acum. año (YTD)" in labels
    assert "Interanual (12m)" not in labels
    assert "Rango del período" in labels or "Máx. del período" in labels


def test_narrative_enero_no_duplica_mes_como_ytd() -> None:
    rates = [
        (2024, 10, 2.5),
        (2024, 11, 2.4),
        (2024, 12, 2.7),
        (2025, 1, 2.2),
    ]
    narrative = build_chart_narrative(
        _monthly(rates),
        unit="%",
        frequency="monthly",
        mode="trend_with_callout",
        publish_date=date(2025, 1, 31),
        scope="argentina",
        is_monthly_pct_change=True,
    )
    labels = [kpi.label for kpi in narrative.kpis]
    assert "Acum. año (YTD)" not in labels
    assert "Período anterior" in labels
    assert any(label in labels for label in ("Máx. del período", "Rango del período"))


def test_narrative_serie_nivel_delta_pct_ytd_yoy_sin_dividir_por_cero() -> None:
    points = [
        SeriesObservation(obs_date=date(2024, 11, 15), value=20_000.0),
        SeriesObservation(obs_date=date(2024, 12, 31), value=25_000.0),
        SeriesObservation(obs_date=date(2025, 6, 15), value=28_000.0),
        SeriesObservation(obs_date=date(2025, 11, 15), value=30_000.0),
    ]
    narrative = build_chart_narrative(
        points,
        unit="millones de USD",
        frequency="daily",
        mode="trend_with_callout",
        publish_date=date(2025, 11, 20),
        scope="argentina",
        is_monthly_pct_change=False,
    )
    assert narrative.delta_direction == "up"
    assert narrative.headline_badge is not None
    assert "%" in narrative.headline_badge
    assert "p.p." not in narrative.headline_badge
    assert "▲" in narrative.headline_badge

    by_label = {kpi.label: kpi for kpi in narrative.kpis}
    assert "Período anterior" in by_label
    assert "Acum. año (YTD)" in by_label
    # YTD vs cierre 2024-12-31: (30000-25000)/25000 = 20 %
    assert by_label["Acum. año (YTD)"].formatted_value == "+20 %"
    assert "Interanual (12m)" in by_label

    # Base en cero: no ZeroDivisionError; omite delta % / YTD peligrosos.
    zero_base = [
        SeriesObservation(obs_date=date(2024, 12, 31), value=0.0),
        SeriesObservation(obs_date=date(2025, 11, 15), value=100.0),
    ]
    safe = build_chart_narrative(
        zero_base,
        unit="millones de USD",
        frequency="daily",
        mode="trend_with_callout",
        publish_date=date(2025, 11, 20),
        scope="argentina",
    )
    assert safe.headline_badge is None
    assert all(kpi.label != "Acum. año (YTD)" for kpi in safe.kpis)


def test_narrative_serie_corta_degrada_a_rango_sin_inventar_yoy() -> None:
    # Ancla en enero: sin YTD (un solo mes del año) ni YoY (faltan 12 puntos).
    points = [
        SeriesObservation(obs_date=date(2024, 12, 1), value=1.5),
        SeriesObservation(obs_date=date(2025, 1, 1), value=2.2),
    ]
    narrative = build_chart_narrative(
        points,
        unit="%",
        frequency="monthly",
        mode="trend_with_callout",
        publish_date=date(2025, 1, 31),
        scope="argentina",
        is_monthly_pct_change=True,
    )
    labels = [kpi.label for kpi in narrative.kpis]
    assert "Interanual (12m)" not in labels
    assert "Acum. año (YTD)" not in labels
    assert "Período anterior" in labels
    assert any(label in labels for label in ("Máx. del período", "Rango del período"))
    by_label = {kpi.label: kpi for kpi in narrative.kpis}
    assert by_label["Período anterior"].formatted_value == "1,5%"
    if "Máx. del período" in by_label:
        assert by_label["Máx. del período"].formatted_value.endswith("%")
    if "Rango del período" in by_label:
        assert "%" in by_label["Rango del período"].formatted_value
    assert narrative.delta_direction == "up"
    assert narrative.headline_badge is not None
    assert "+0,7 p.p." in narrative.headline_badge


def test_narrative_recorta_puntos_posteriores_a_publish_date() -> None:
    points = [
        SeriesObservation(obs_date=date(2025, 10, 1), value=1.0),
        SeriesObservation(obs_date=date(2025, 11, 1), value=2.0),
        SeriesObservation(obs_date=date(2025, 12, 1), value=9.9),
    ]
    narrative = build_chart_narrative(
        points,
        unit="%",
        frequency="monthly",
        mode="trend_with_callout",
        publish_date=date(2025, 11, 15),
        scope="argentina",
        is_monthly_pct_change=True,
    )
    assert narrative.anchor_date == "2025-11-01"
    assert narrative.delta_direction == "up"


def test_narrative_sin_puntos_validos_falla_cerrado() -> None:
    with pytest.raises(MetricsCalculationError, match="narrativa"):
        build_chart_narrative(
            [SeriesObservation(obs_date=date(2025, 1, 1), value=None)],
            unit="%",
            frequency="monthly",
            mode="trend_with_callout",
            publish_date=date(2025, 11, 30),
            scope="argentina",
        )
