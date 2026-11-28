"""Playbook v1: catálogo, base 100 y matcher determinista (100 % offline)."""

from __future__ import annotations

from datetime import date

import pytest

from tigani_broadcast.official_data_charts.models import ChartArtifact, DataPoint
from tigani_broadcast.official_data_charts.playbook import (
    PLAYBOOK_CATALOG,
    build_dual_base100,
    build_dual_spread,
    build_trade_balance,
    match_playbook_fallback,
)
from tigani_broadcast.official_data_charts.resolver import SERIES_CATALOG


def _point(year: int, month: int, day: int, value: float) -> DataPoint:
    return DataPoint(obs_date=date(year, month, day), value=value)


def test_playbook_catalog_usa_claves_reales_del_catalogo() -> None:
    assert set(PLAYBOOK_CATALOG) == {
        "ipc_trend",
        "ipc_vs_dolar_base100",
        "reservas_bcra_regimes",
        "emae_activity",
        "riesgo_pais_trend",
        "brecha_cambiaria",
        "salarios_vs_ipc_base100",
        "canasta_basica_vs_ipc_base100",
        "balanza_comercial_ica",
    }
    for spec in PLAYBOOK_CATALOG.values():
        assert spec.series_keys
        for series_key in spec.series_keys:
            assert series_key in SERIES_CATALOG

    ipc = PLAYBOOK_CATALOG["ipc_trend"]
    assert ipc.chart_type == "single_line"
    assert ipc.default_window_months == 12
    assert ipc.fetch_window_months == 13
    assert ipc.series_keys == ("ar_indec_ipc_mensual",)

    dual = PLAYBOOK_CATALOG["ipc_vs_dolar_base100"]
    assert dual.chart_type == "dual_base100"
    assert dual.default_window_months == 12
    assert dual.fetch_window_months == 13
    assert dual.series_keys == ("ar_indec_ipc_mensual", "ar_bcra_dolar_mayorista")
    assert dual.editorial_note == (
        "Índices re-indexados a Base 100 en el mes inicial de la ventana"
    )

    reservas = PLAYBOOK_CATALOG["reservas_bcra_regimes"]
    assert reservas.default_window_months == 48
    assert reservas.series_keys == ("ar_bcra_reservas_brutas",)
    assert "brutas" in (reservas.editorial_note or "")
    assert PLAYBOOK_CATALOG["emae_activity"].series_keys == ("ar_indec_emae_mensual",)
    assert PLAYBOOK_CATALOG["emae_activity"].chart_type == "bar_diverging"
    assert PLAYBOOK_CATALOG["riesgo_pais_trend"].series_keys == ("ar_mkt_riesgo_pais",)


def test_chart_artifact_playbook_es_retrocompatible() -> None:
    artifact = ChartArtifact(
        chapter_index=0,
        cue_index=1,
        timestamp="00:00:07",
        indicator_label="reservas netas",
        raw_value_text="negativas",
        resolution_status="quoted_only",
        rationale="Cita textual.",
    )
    assert artifact.playbook_id is None
    assert artifact.chart_type == "single_line"
    assert artifact.secondary_series is None
    assert artifact.editorial_note is None


def test_build_dual_base100_compone_ipc_agrega_dolar_y_recorta() -> None:
    ipc = [
        _point(2025, 1, 1, 0.0),
        _point(2025, 2, 1, 10.0),
        _point(2025, 3, 1, 10.0),
        _point(2025, 4, 1, 50.0),
    ]
    fx = [
        _point(2025, 1, 10, 900.0),
        _point(2025, 1, 31, 1000.0),
        _point(2025, 2, 15, 1000.0),
        _point(2025, 3, 1, 900.0),
        _point(2025, 3, 31, 1000.0),
        _point(2025, 4, 30, 5000.0),
    ]
    ipc_idx, fx_idx, narrative = build_dual_base100(
        ipc,
        fx,
        publish_date=date(2025, 3, 31),
        max_months=12,
    )

    assert [point.obs_date for point in ipc_idx] == [
        date(2025, 1, 1),
        date(2025, 2, 1),
        date(2025, 3, 1),
    ]
    assert [point.obs_date for point in fx_idx] == [point.obs_date for point in ipc_idx]
    assert ipc_idx[0].value == pytest.approx(100.0)
    assert ipc_idx[1].value == pytest.approx(110.0)
    assert ipc_idx[2].value == pytest.approx(121.0)
    assert [point.value for point in fx_idx] == pytest.approx([100.0, 100.0, 100.0])

    assert narrative.headline_badge == "▲ +21,0% IPC sobre dólar"
    assert narrative.delta_direction == "up"
    by_label = {kpi.label: kpi.formatted_value for kpi in narrative.kpis}
    assert by_label == {
        "IPC acumulado": "+21,0%",
        "Dólar oficial": "+0,0%",
        "Brecha real": "+21,0%",
    }
    assert narrative.anchor_date == "2025-03-01"


def test_build_dual_base100_brecha_plana_cuando_ambos_suben_igual() -> None:
    ipc = [_point(2025, 1, 1, 0.0), _point(2025, 2, 1, 10.0)]
    fx = [_point(2025, 1, 31, 100.0), _point(2025, 2, 28, 110.0)]
    _ipc_idx, _fx_idx, narrative = build_dual_base100(
        ipc,
        fx,
        publish_date=date(2025, 2, 28),
    )
    assert narrative.delta_direction == "flat"
    assert narrative.headline_badge == "= 0,0%"
    by_label = {kpi.label: kpi.formatted_value for kpi in narrative.kpis}
    assert by_label["IPC acumulado"] == "+10,0%"
    assert by_label["Dólar oficial"] == "+10,0%"
    assert by_label["Brecha real"] == "+0,0%"


def test_build_dual_base100_brecha_negativa_cuando_el_dolar_sube_mas() -> None:
    ipc = [_point(2025, 1, 1, 4.0), _point(2025, 2, 1, 0.0)]
    fx = [_point(2025, 1, 31, 100.0), _point(2025, 2, 28, 200.0)]
    _ipc_idx, _fx_idx, narrative = build_dual_base100(
        ipc,
        fx,
        publish_date=date(2025, 2, 28),
    )
    assert narrative.headline_badge == "▼ -50,0% dólar sobre IPC"
    assert narrative.delta_direction == "down"
    by_label = {kpi.label: kpi.formatted_value for kpi in narrative.kpis}
    assert by_label["IPC acumulado"] == "+0,0%"
    assert by_label["Dólar oficial"] == "+100,0%"
    assert by_label["Brecha real"] == "-50,0%"


def test_build_dual_base100_toma_ultimos_meses_de_la_ventana() -> None:
    ipc = [
        _point(2025, 1, 1, 0.0),
        _point(2025, 2, 1, 10.0),
        _point(2025, 3, 1, 10.0),
    ]
    fx = [
        _point(2025, 1, 31, 100.0),
        _point(2025, 2, 28, 100.0),
        _point(2025, 3, 31, 100.0),
    ]
    ipc_idx, _fx_idx, _narrative = build_dual_base100(
        ipc,
        fx,
        publish_date=date(2025, 3, 31),
        max_months=1,
    )
    assert [point.obs_date for point in ipc_idx] == [date(2025, 2, 1), date(2025, 3, 1)]
    assert ipc_idx[0].value == pytest.approx(100.0)
    assert ipc_idx[1].value == pytest.approx(110.0)


def test_build_dual_base100_rechaza_menos_de_dos_meses_comunes() -> None:
    ipc = [_point(2025, 1, 1, 2.0), _point(2025, 2, 1, 2.0)]
    fx = [_point(2025, 3, 31, 100.0), _point(2025, 4, 30, 110.0)]
    with pytest.raises(ValueError, match="al menos 2 meses comunes"):
        build_dual_base100(ipc, fx, publish_date=date(2025, 12, 31))


def test_build_dual_base100_rechaza_dolar_base_cero() -> None:
    ipc = [_point(2025, 1, 1, 2.0), _point(2025, 2, 1, 2.0)]
    fx = [_point(2025, 1, 31, 0.0), _point(2025, 2, 28, 100.0)]
    with pytest.raises(ValueError, match="dólar oficial del mes base es 0"):
        build_dual_base100(ipc, fx, publish_date=date(2025, 2, 28))


def test_build_dual_base100_series_desfasadas_usan_solo_la_interseccion() -> None:
    ipc = [
        _point(2025, 1, 1, 8.0),
        _point(2025, 2, 1, 0.0),
        _point(2025, 3, 1, 10.0),
    ]
    fx = [
        _point(2025, 2, 28, 50.0),
        _point(2025, 3, 31, 50.0),
        _point(2025, 4, 30, 80.0),
    ]
    ipc_idx, fx_idx, narrative = build_dual_base100(
        ipc,
        fx,
        publish_date=date(2025, 4, 30),
    )
    assert [point.obs_date for point in ipc_idx] == [date(2025, 2, 1), date(2025, 3, 1)]
    assert ipc_idx[0].value == pytest.approx(100.0)
    assert ipc_idx[1].value == pytest.approx(110.0)
    assert [point.value for point in fx_idx] == pytest.approx([100.0, 100.0])
    assert narrative.headline_badge == "▲ +10,0% IPC sobre dólar"


def test_match_playbook_fallback_frases_del_piloto() -> None:
    assert match_playbook_fallback(
        "productos y servicios 55% en dólares",
        existing_series_keys=set(),
    ) == ["ipc_vs_dolar_base100"]
    assert match_playbook_fallback(
        "reservas netas",
        existing_series_keys=set(),
    ) == ["reservas_bcra_regimes"]
    assert (
        match_playbook_fallback(
            "deuda al 9.26%",
            existing_series_keys=set(),
        )
        == []
    )
    assert match_playbook_fallback(
        "tasa de interés de la deuda al 9.26%",
        existing_series_keys=set(),
    ) == ["riesgo_pais_trend"]


def test_match_playbook_fallback_no_duplica_ipc_y_respeta_tope() -> None:
    chapter = (
        "productos y servicios en dólares, reservas netas, "
        "riesgo país y deuda, recesión del EMAE e inflación"
    )
    assert match_playbook_fallback(chapter, existing_series_keys=set(), max_items=2) == [
        "ipc_vs_dolar_base100",
        "reservas_bcra_regimes",
    ]
    assert (
        match_playbook_fallback(
            "la inflación y el IPC de este mes",
            existing_series_keys={"ar_indec_ipc_mensual"},
        )
        == []
    )


def test_build_dual_base100_acepta_indice_de_nivel() -> None:
    salarios = [
        _point(2025, 1, 1, 200.0),
        _point(2025, 2, 1, 220.0),
        _point(2025, 3, 1, 242.0),
    ]
    ipc = [_point(2025, 1, 1, 0.0), _point(2025, 2, 1, 10.0), _point(2025, 3, 1, 10.0)]
    left, right, narrative = build_dual_base100(
        salarios,
        ipc,
        publish_date=date(2025, 3, 31),
        primary_mode="level",
        secondary_mode="percent_change",
        primary_label="Salarios",
        secondary_label="IPC",
        primary_subject="salarios",
        secondary_subject="IPC",
    )
    assert [point.value for point in left] == pytest.approx([100.0, 110.0, 121.0])
    assert [point.value for point in right] == pytest.approx([100.0, 110.0, 121.0])
    assert narrative.headline_badge == "= 0,0%"
    by_label = {kpi.label: kpi.formatted_value for kpi in narrative.kpis}
    assert by_label["Salarios"] == "+21,0%"
    assert by_label["IPC"] == "+21,0%"


def test_build_dual_spread_brecha_actual_y_maxima() -> None:
    official = [
        _point(2025, 1, 31, 1000.0),
        _point(2025, 2, 28, 1000.0),
        _point(2025, 3, 31, 9.0),
    ]
    parallel = [
        _point(2025, 1, 15, 1100.0),
        _point(2025, 1, 31, 1200.0),
        _point(2025, 2, 28, 1500.0),
    ]
    official_out, parallel_out, narrative = build_dual_spread(
        official,
        parallel,
        publish_date=date(2025, 2, 28),
    )
    assert [point.obs_date for point in official_out] == [date(2025, 1, 31), date(2025, 2, 28)]
    assert [point.obs_date for point in parallel_out] == [point.obs_date for point in official_out]
    assert parallel_out[0].value == pytest.approx(1200.0)
    assert narrative.headline_badge == "Brecha actual: +50,0%"
    assert narrative.delta_direction == "up"
    by_label = {kpi.label: kpi.formatted_value for kpi in narrative.kpis}
    assert by_label == {"Oficial": "1.000", "Paralelo/MEP": "1.500", "Brecha máx.": "+50,0%"}


def test_build_trade_balance_saldo_mensual_y_acumulado() -> None:
    exports = [_point(2025, 1, 1, 100.0), _point(2025, 2, 1, 80.0)]
    imports = [_point(2025, 1, 1, 40.0), _point(2025, 2, 1, 90.0), _point(2025, 3, 1, 1.0)]
    _expo, impo, narrative = build_trade_balance(
        exports,
        imports,
        publish_date=date(2025, 2, 28),
    )
    assert impo[1].value == pytest.approx(90.0)
    assert narrative.delta_direction == "down"
    assert narrative.headline_badge == "▼ -10 mill. USD"
    by_label = {kpi.label: kpi.formatted_value for kpi in narrative.kpis}
    assert by_label["Último saldo"] == "-10"
    assert by_label["Acum. período"] == "+50"
    assert by_label["Exportaciones últ. mes"] == "80"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("se amplió la brecha y el cepo", "brecha_cambiaria"),
        ("el dólar blue y el MEP", "brecha_cambiaria"),
        ("los salarios perdieron poder adquisitivo", "salarios_vs_ipc_base100"),
        ("la canasta básica y la pobreza", "canasta_basica_vs_ipc_base100"),
        ("la balanza comercial y las exportaciones", "balanza_comercial_ica"),
    ],
)
def test_match_playbook_v2_triggers(text: str, expected: str) -> None:
    matched = match_playbook_fallback(text, existing_series_keys=set(), max_items=1)
    assert matched == [expected]
