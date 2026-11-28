"""Render JSON/MD/HTML 16:9 con Apache ECharts offline (cero red)."""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path

from tigani_broadcast.official_data_charts.cli import EXIT_ERROR, run_cli
from tigani_broadcast.official_data_charts.metrics import build_chart_narrative
from tigani_broadcast.official_data_charts.models import (
    ChartArtifact,
    ChartNarrative,
    ChartsPackage,
    DataPoint,
    EditorialKpi,
    RegimeBand,
    SecondarySeriesData,
    SeriesData,
    SeriesMetrics,
    SeriesObservation,
)
from tigani_broadcast.official_data_charts.render import (
    build_echarts_option,
    echarts_asset_path,
    render_artifact_html,
    render_charts_json,
    render_charts_markdown,
    rerender_charts_package,
    write_charts_package,
)


def _metrics(
    *,
    start: date,
    end: date,
    first: float,
    latest: float,
    provisional: bool = False,
    flags: list[str] | None = None,
) -> SeriesMetrics:
    return SeriesMetrics(
        observation_count=2,
        valid_count=2,
        start_date=start,
        end_date=end,
        first_value=first,
        latest_value=latest,
        min_value=min(first, latest),
        min_date=start,
        max_value=max(first, latest),
        max_date=end,
        absolute_change=latest - first,
        percent_change=((latest - first) / abs(first)) * 100 if first != 0 else None,
        has_provisional_flags=provisional,
        flags_present=flags or [],
    )


def _series(observations: list[SeriesObservation]) -> SeriesData:
    return SeriesData(
        catalog_id="ar_indec_ipc_mensual",
        provider="indec",
        source_tier="official_primary",
        series_id="145.3_INGNACNAL_DICI_M_38",
        source_url="https://api.indec.gob.ar/v1/ipc_nacional_tidy",
        source_attribution="Fuente: INDEC — IPC",
        unit="%",
        frequency="monthly",
        observations=observations,
    )


def _verified(
    *,
    observations: list[SeriesObservation] | None = None,
    provisional: bool = False,
    label: str = "índice de inflación",
    raw: str = "2.5%",
) -> ChartArtifact:
    obs = observations or [
        SeriesObservation(obs_date=date(2025, 1, 1), value=2.0),
        SeriesObservation(obs_date=date(2025, 2, 1), value=2.5),
    ]
    valid = [o for o in obs if o.value is not None]
    first = valid[0].value if valid else 0.0
    latest = valid[-1].value if valid else 0.0
    assert first is not None and latest is not None
    return ChartArtifact(
        chapter_index=0,
        cue_index=1,
        timestamp="00:00:07",
        indicator_label=label,
        raw_value_text=raw,
        time_reference="hoy",
        resolution_status="verified_series",
        rationale="IPC mensual INDEC.",
        series=_series(obs),
        metrics=_metrics(
            start=valid[0].obs_date if valid else date(2025, 1, 1),
            end=valid[-1].obs_date if valid else date(2025, 1, 1),
            first=first,
            latest=latest,
            provisional=provisional,
            flags=["*", "e"] if provisional else [],
        ),
    )


def test_verified_html_incluye_echarts_offline_y_textos_es() -> None:
    html = render_artifact_html(_verified(provisional=True), date(2025, 12, 11))
    assert '<script src="echarts.min.js">' in html
    assert 'id="chart"' in html
    assert "echarts.init" in html
    assert "animationDuration" in html
    assert "Fuente: INDEC — IPC" in html
    assert "145.3_INGNACNAL_DICI_M_38" in html
    assert "Datos provisorios" in html
    assert "min-width: 960px" in html
    assert "min-height: 540px" in html
    assert "max-width: 1920px" not in html
    assert "max-height: 1080px" not in html
    assert "min-height: 280px" not in html
    assert "requestAnimationFrame" in html
    assert "clientWidth / 1280" in html
    assert "ResizeObserver" in html
    assert "Índice de inflación" in html
    assert "Corte: 11/12/2025" in html
    assert "Mensual" in html
    assert "publish_date 2025-12-11" not in html
    assert "Ene 25" in html
    assert "Feb 25" in html
    assert not re.search(r"https?://cdn\.|jsdelivr|unpkg|cdnjs", html, flags=re.I)
    assert not re.search(r"<(link)[^>]+https?://", html, flags=re.I)
    assert 'class="side"' in html
    assert 'class="badge' not in html
    assert 'class="kpi-bar"' not in html


def test_echarts_option_labels_y_markpoint() -> None:
    short = [
        SeriesObservation(obs_date=date(2025, 1, 1), value=2.0),
        SeriesObservation(obs_date=date(2025, 2, 1), value=2.8),
    ]
    option_short = build_echarts_option(
        short,
        _metrics(start=date(2025, 1, 1), end=date(2025, 2, 1), first=2.0, latest=2.8),
        unit="%",
    )
    assert option_short["animation"] is True
    assert option_short["animationDuration"] == 750
    assert option_short["series"][0]["smooth"] == 0.2
    assert option_short["series"][0]["label"]["show"] is True
    assert option_short["grid"]["containLabel"] is True
    assert option_short["grid"]["top"] == 44
    assert option_short["yAxis"]["min"] < 2.0
    assert option_short["yAxis"]["max"] > 2.8
    assert option_short["xAxis"]["axisLabel"]["show"] is True
    assert option_short["xAxis"]["axisLabel"]["interval"] == 0
    assert "markPoint" not in option_short["series"][0]
    assert "Ene 25" in option_short["xAxis"]["data"]
    assert "Feb 25" in option_short["xAxis"]["data"]

    long_obs = [
        SeriesObservation(obs_date=date(2024, month, 1), value=1.0 + month * 0.1)
        for month in range(1, 13)
    ] + [
        SeriesObservation(obs_date=date(2025, 1, 1), value=3.7),
        SeriesObservation(obs_date=date(2025, 2, 1), value=2.8),
        SeriesObservation(obs_date=date(2025, 3, 1), value=2.2),
    ]
    values = [o.value for o in long_obs if o.value is not None]
    metrics = _metrics(
        start=date(2024, 1, 1),
        end=date(2025, 3, 1),
        first=float(values[0]),
        latest=float(values[-1]),
    ).model_copy(
        update={
            "min_value": float(min(values)),  # type: ignore[arg-type]
            "max_value": float(max(values)),  # type: ignore[arg-type]
        }
    )
    option_long = build_echarts_option(long_obs, metrics, unit="%")
    assert option_long["series"][0]["label"]["show"] is False
    assert "markPoint" in option_long["series"][0]
    assert "Ene 24" in option_long["xAxis"]["data"]
    assert "Mar 25" in option_long["xAxis"]["data"]


def _narrative_artifact() -> ChartArtifact:
    observations = [
        SeriesObservation(obs_date=date(2022, 6, 1), value=5.0),
        SeriesObservation(obs_date=date(2023, 6, 1), value=7.0),
        SeriesObservation(obs_date=date(2024, 6, 1), value=4.0),
        SeriesObservation(obs_date=date(2025, 5, 1), value=2.5),
    ]
    narrative = build_chart_narrative(
        observations,
        unit="%",
        frequency="monthly",
        mode="term_comparison",
        publish_date=date(2025, 6, 1),
        scope="argentina",
        is_monthly_pct_change=True,
    )
    base = _verified(observations=observations)
    return base.model_copy(update={"narrative": narrative})


def test_verified_html_con_narrativa_badge_markarea_y_kpis() -> None:
    artifact = _narrative_artifact()
    assert artifact.narrative is not None
    html = render_artifact_html(artifact, date(2025, 6, 1))
    assert artifact.narrative.headline_badge is not None
    assert artifact.narrative.headline_badge in html
    assert 'class="badge' in html
    assert "markArea" in html
    assert "Fernández" in html or "Milei" in html
    assert "kpi-bar" in html
    assert "kpi-card" in html
    assert any(kpi.label in html for kpi in artifact.narrative.kpis)
    assert "Índice de inflación" in html
    assert "Corte: 01/06/2025" in html
    assert "min-width: 960px" in html
    assert "min-height: 540px" in html
    assert "max-width: 1920px" not in html
    assert "max-height: 1080px" not in html
    assert '<script src="echarts.min.js">' in html
    assert not re.search(r"https?://cdn\.|jsdelivr|unpkg", html, flags=re.I)


def test_narrativa_escapa_html_en_badge_bandas_y_kpis() -> None:
    narrative = ChartNarrative(
        mode="trend_with_callout",
        headline_badge="▲ +0,3 p.p. <script>alert(1)</script>",
        delta_direction="up",
        anchor_date="2025-02-01",
        anchor_label="feb<script>x</script>",
        kpis=[
            EditorialKpi(
                label="YTD <b>mal</b>",
                formatted_value="+1,2 % & más",
                detail="2025-01-01→2025-02-01",
            )
        ],
        regime_bands=[
            RegimeBand(
                label="Fernández <img src=x>",
                start_date=date(2025, 1, 1),
                end_date=date(2025, 1, 15),
            ),
            RegimeBand(
                label="Milei (2023–act.)",
                start_date=date(2025, 1, 16),
                end_date=date(2025, 2, 1),
            ),
        ],
    )
    artifact = _verified().model_copy(update={"narrative": narrative})
    html_doc = render_artifact_html(artifact, date(2025, 12, 11))
    assert "<script>alert(1)</script>" not in html_doc
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html_doc
    assert "<b>mal</b>" not in html_doc
    assert "&lt;b&gt;mal&lt;/b&gt;" in html_doc
    assert "&amp; más" in html_doc
    assert "<img src=x>" not in html_doc
    assert "&lt;img src=x&gt;" in html_doc
    # El JSON embebido no debe romper el script con </.
    assert "<\\/" in html_doc or "</script>" in html_doc


def test_echarts_option_sin_puntos_validos() -> None:
    metrics = SeriesMetrics(
        observation_count=1,
        valid_count=1,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 1),
        first_value=1.0,
        latest_value=1.0,
        min_value=1.0,
        min_date=date(2025, 1, 1),
        max_value=1.0,
        max_date=date(2025, 1, 1),
        absolute_change=None,
        percent_change=None,
        has_provisional_flags=False,
        flags_present=[],
    )
    option = build_echarts_option(
        [SeriesObservation(obs_date=date(2025, 1, 1), value=None)],
        metrics,
    )
    assert option["title"]["text"] == "Sin datos"


def test_quoted_and_fetch_error_escape_html() -> None:
    quoted = ChartArtifact(
        chapter_index=1,
        cue_index=9,
        timestamp="00:01:13",
        indicator_label="reservas <script>netas</script>",
        raw_value_text="26,000 & más",
        time_reference="2015",
        resolution_status="quoted_only",
        rationale="Sin serie.",
    )
    html_q = render_artifact_html(quoted, date(2025, 12, 11))
    assert "Dato citado en exposición — sin serie oficial asociada" in html_q
    assert "<script>netas</script>" not in html_q
    assert "&lt;script&gt;" in html_q
    assert "&amp; más" in html_q
    assert "echarts.min.js" not in html_q

    err = ChartArtifact(
        chapter_index=0,
        cue_index=4,
        timestamp="00:00:40",
        indicator_label="BADLAR",
        raw_value_text="9.26%",
        resolution_status="fetch_error",
        rationale="Falló BCRA",
        error_message="timeout <BCRA>",
    )
    html_e = render_artifact_html(err, date(2025, 12, 11))
    assert "timeout &lt;BCRA&gt;" in html_e
    assert "No se pudo obtener la serie oficial" in html_e


def test_render_json_y_markdown() -> None:
    package = ChartsPackage(
        publish_date=date(2025, 12, 11),
        source_chapters_path="out/video.chapters.json",
        items=[
            _verified(),
            ChartArtifact(
                chapter_index=1,
                cue_index=19,
                timestamp="00:02:36",
                indicator_label="deuda",
                raw_value_text="4600 millones de dólares",
                resolution_status="quoted_only",
                rationale="Monto puntual.",
            ),
        ],
    )
    payload = json.loads(render_charts_json(package))
    assert payload["publish_date"] == "2025-12-11"
    assert len(payload["items"]) == 2

    md = render_charts_markdown(package)
    assert "publish_date" in md
    assert "verified_series" in md
    assert "quoted_only" in md
    assert "índice de inflación" in md


def test_write_charts_package_copia_echarts_min_js(tmp_path: Path) -> None:
    assert echarts_asset_path().is_file()
    package = ChartsPackage(
        publish_date=date(2025, 12, 11),
        items=[
            _verified(),
            ChartArtifact(
                chapter_index=0,
                cue_index=10,
                timestamp="00:01:22",
                indicator_label="reservas netas",
                raw_value_text="-17,000 millones",
                resolution_status="quoted_only",
                rationale="quoted",
            ),
        ],
    )
    out_json = tmp_path / "charts.json"
    charts_dir = tmp_path / "charts"
    md = tmp_path / "charts.md"
    result = write_charts_package(package, out_json, charts_dir, md)
    assert out_json.is_file()
    assert md.is_file()
    assert (charts_dir / "echarts.min.js").is_file()
    assert (charts_dir / "echarts.min.js").stat().st_size > 100_000
    assert len(list(charts_dir.glob("*.html"))) == 2
    assert all(item.html_path is not None for item in result.items)
    verified = Path(result.items[0].html_path or "").read_text(encoding="utf-8")
    assert '<script src="echarts.min.js">' in verified


def test_render_dual_base100_leyenda_marca_y_escapa_nota() -> None:
    observations = [
        SeriesObservation(obs_date=date(2025, 1, 1), value=100.0),
        SeriesObservation(obs_date=date(2025, 2, 1), value=110.0),
    ]
    artifact = _verified(observations=observations, label="Inflación vs. dólar oficial").model_copy(
        update={
            "playbook_id": "ipc_vs_dolar_base100",
            "chart_type": "dual_base100",
            "editorial_note": "Base 100 <img src=x>",
            "secondary_series": SecondarySeriesData(
                label="Dólar mayorista",
                series_key="ar_bcra_dolar_mayorista",
                provider="bcra",
                series_id="4",
                unit="base 100",
                points=[
                    DataPoint(obs_date=date(2025, 1, 1), value=100.0),
                    DataPoint(obs_date=date(2025, 2, 1), value=121.0),
                ],
            ),
        }
    )
    html = render_artifact_html(artifact, date(2025, 12, 11))
    assert "editorial-note" in html
    assert "Base 100 &lt;img src=x&gt;" in html
    assert "<img src=x>" not in html
    assert "Fuente: INDEC — IPC" in html
    assert "Fuente: BCRA" in html
    assert "min-width: 960px" in html
    assert "max-width: 1920px" not in html
    assert "ResizeObserver" in html
    assert '<script src="echarts.min.js">' in html
    option = build_echarts_option(
        observations,
        artifact.metrics,  # type: ignore[arg-type]
        chart_type="dual_base100",
        secondary_points=artifact.secondary_series.points if artifact.secondary_series else None,
    )
    assert option["legend"]["show"] is True
    assert len(option["series"]) == 2
    assert option["series"][0]["name"] == "IPC"
    assert option["series"][0]["lineStyle"]["color"] == "#3db8a8"
    assert option["series"][1]["name"] == "Dólar mayorista"
    assert option["series"][1]["lineStyle"]["color"] == "#e8b84a"
    assert option["series"][0]["markLine"]["data"][0]["yAxis"] == 100
    assert option["series"][0]["data"][0]["label"]["show"] is True
    assert option["series"][0]["data"][-1]["label"]["show"] is True


def test_render_bar_diverging_colores_y_eje_cero() -> None:
    observations = [
        SeriesObservation(obs_date=date(2025, 1, 1), value=1.5),
        SeriesObservation(obs_date=date(2025, 2, 1), value=-0.8),
    ]
    artifact = _verified(observations=observations, label="Actividad económica (EMAE)").model_copy(
        update={
            "playbook_id": "emae_activity",
            "chart_type": "bar_diverging",
            "editorial_note": "Variación mensual",
        }
    )
    html = render_artifact_html(artifact, date(2025, 12, 11))
    assert "Variación mensual" in html
    assert '"type": "bar"' in html or '"type":"bar"' in html
    option = build_echarts_option(
        observations,
        artifact.metrics,  # type: ignore[arg-type]
        chart_type="bar_diverging",
    )
    assert option["series"][0]["type"] == "bar"
    assert option["series"][0]["data"][0]["itemStyle"]["color"] == "#3db8a8"
    assert option["series"][0]["data"][0]["label"]["position"] == "top"
    assert option["series"][0]["data"][1]["itemStyle"]["color"] == "#e57373"
    assert option["series"][0]["data"][1]["label"]["position"] == "bottom"
    assert option["series"][0]["markLine"]["data"][0]["yAxis"] == 0
    assert option["yAxis"]["min"] < 0 < option["yAxis"]["max"]


def test_serie_densa_usa_indices_enteros_y_oculta_simbolos() -> None:
    start = date(2023, 6, 1)
    observations = [
        SeriesObservation(obs_date=start + timedelta(days=10 * index), value=40_000.0 + index)
        for index in range(30)
    ]
    narrative = ChartNarrative(
        mode="term_comparison",
        anchor_date=observations[-1].obs_date.isoformat(),
        anchor_label="mar-2024",
        regime_bands=[
            RegimeBand(
                label="Fernández (2019–23)",
                start_date=date(2023, 6, 1),
                end_date=date(2023, 12, 9),
            ),
            RegimeBand(
                label="Milei (2023–act.)",
                start_date=date(2023, 12, 10),
                end_date=observations[-1].obs_date,
            ),
        ],
    )
    option = build_echarts_option(
        observations,
        _metrics(
            start=observations[0].obs_date,
            end=observations[-1].obs_date,
            first=40_000.0,
            latest=40_029.0,
        ),
        narrative=narrative,
        unit="millones de USD",
    )
    series = option["series"][0]
    assert series["showSymbol"] is False
    assert all(isinstance(point["coord"][0], int) for point in series["markPoint"]["data"])
    for band in series["markArea"]["data"]:
        assert isinstance(band[0]["xAxis"], int)
        assert isinstance(band[1]["xAxis"], int)
        assert band[0]["xAxis"] <= band[1]["xAxis"]
    html = render_artifact_html(
        _verified(observations=observations).model_copy(update={"narrative": narrative}),
        date(2025, 12, 11),
    )
    assert "groupThousands" in html
    assert "\\B(?=(\\d{3})+(?!\\d))" in html or r"\B(?=(\d{3})+(?!\d))" in html


def test_playbook_pie_dice_contexto_oficial() -> None:
    artifact = _narrative_artifact().model_copy(update={"playbook_id": "reservas_bcra_regimes"})
    html = render_artifact_html(artifact, date(2025, 6, 1))
    assert "Contexto oficial · Corte: 01/06/2025" in html
    assert "Citado:" not in html


def test_rerender_charts_package_regenera_html_sin_llm_ni_red(
    tmp_path: Path,
    monkeypatch,
) -> None:
    def _prohibido(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("rerender-only no debe instanciar LLM ni providers")

    monkeypatch.setattr(
        "tigani_broadcast.official_data_charts.cli.AgnoMentionResolver",
        _prohibido,
    )
    monkeypatch.setattr(
        "tigani_broadcast.official_data_charts.cli.build_default_series_fetcher",
        _prohibido,
    )
    monkeypatch.setattr(
        "tigani_broadcast.official_data_charts.cli.build_agno_model_from_env",
        _prohibido,
    )

    charts_json = tmp_path / "charts.json"
    charts_dir = tmp_path / "charts"
    package = ChartsPackage(publish_date=date(2025, 12, 11), items=[_verified()])
    charts_json.write_text(render_charts_json(package), encoding="utf-8")

    result = rerender_charts_package(charts_json, charts_dir=charts_dir)
    html_path = charts_dir / "ch00_cue001_00.html"
    assert html_path.is_file()
    html = html_path.read_text(encoding="utf-8")
    assert "echarts.init" in html
    assert "min-width: 960px" in html
    assert (charts_dir / "echarts.min.js").is_file()
    assert (tmp_path / "charts.md").is_file()
    assert result.items[0].html_path == str(html_path)

    code = run_cli(
        ["--rerender-only", "--output", str(charts_json), "--charts-dir", str(charts_dir)]
    )
    assert code == 0


def test_cli_rerender_only_falla_si_falta_charts_json(tmp_path: Path, capsys) -> None:
    missing = tmp_path / "charts.json"
    code = run_cli(["--rerender-only", "--output", str(missing)])
    captured = capsys.readouterr()
    assert code == EXIT_ERROR
    assert "charts.json" in captured.err
    assert "sin --rerender-only" in captured.err


def test_render_dual_spread_leyenda_indice_y_contexto() -> None:
    start = date(2025, 1, 1)
    observations = [
        SeriesObservation(obs_date=start + timedelta(days=index), value=1000.0 + index)
        for index in range(30)
    ]
    secondary = [
        DataPoint(obs_date=obs.obs_date, value=float(obs.value or 0) + 200.0)
        for obs in observations
    ]
    option = build_echarts_option(
        observations,
        _metrics(
            start=observations[0].obs_date,
            end=observations[-1].obs_date,
            first=1000.0,
            latest=1029.0,
        ),
        chart_type="dual_spread",
        secondary_points=secondary,
        unit="ARS por USD",
    )
    assert [serie["type"] for serie in option["series"]] == ["line", "line"]
    assert option["series"][0]["name"] == "Dólar oficial"
    assert option["series"][0]["lineStyle"]["color"] == "#3db8a8"
    assert option["series"][0]["showSymbol"] is False
    assert option["series"][0]["markPoint"]["data"][0]["coord"][0] == 29
    assert option["series"][1]["name"] == "Dólar blue"
    assert option["series"][1]["lineStyle"]["color"] == "#e8b84a"
    assert option["series"][1]["areaStyle"]["color"] == "rgba(232,184,74,0.18)"
    assert option["series"][1]["markPoint"]["data"][0]["coord"][0] == 29
    assert option["legend"]["show"] is True
    base = _verified(observations=observations, label="Brecha cambiaria")
    assert base.series is not None
    artifact = base.model_copy(
        update={
            "playbook_id": "brecha_cambiaria",
            "chart_type": "dual_spread",
            "editorial_note": "Blue <img src=x>",
            "series": base.series.model_copy(
                update={"source_attribution": "Fuente: BCRA — Comunicación A 3500"}
            ),
            "narrative": ChartNarrative(
                mode="trend_with_callout",
                headline_badge="Brecha actual: +20,0%",
                anchor_date=observations[-1].obs_date.isoformat(),
                anchor_label="ene-2025",
            ),
            "secondary_series": SecondarySeriesData(
                label="Dólar blue",
                series_key="ar_mkt_dolar_blue",
                provider="argentinadatos",
                series_id="dolares/blue",
                unit="ARS por USD",
                points=secondary,
            ),
        }
    )
    html = render_artifact_html(artifact, date(2025, 12, 11))
    assert "Contexto oficial · Corte: 11/12/2025" in html
    assert "Citado:" not in html
    assert "Blue &lt;img src=x&gt;" in html
    assert "<img src=x>" not in html
    assert "Fuente: BCRA" in html
    assert "ArgentinaDatos" in html or "DolarApi" in html
    assert "groupThousands" in html


def test_render_trade_balance_barras_saldo_y_eje_cero() -> None:
    observations = [
        SeriesObservation(obs_date=date(2025, 1, 1), value=100.0),
        SeriesObservation(obs_date=date(2025, 2, 1), value=80.0),
    ]
    secondary = [
        DataPoint(obs_date=date(2025, 1, 1), value=40.0),
        DataPoint(obs_date=date(2025, 2, 1), value=90.0),
    ]
    option = build_echarts_option(
        observations,
        _metrics(start=date(2025, 1, 1), end=date(2025, 2, 1), first=100.0, latest=80.0),
        chart_type="trade_balance",
        secondary_points=secondary,
    )
    assert [serie["type"] for serie in option["series"]] == ["bar", "bar", "line"]
    assert option["series"][0]["name"] == "Exportaciones"
    assert option["series"][0]["itemStyle"]["color"] == "#3db8a8"
    assert option["series"][1]["name"] == "Importaciones"
    assert option["series"][1]["itemStyle"]["color"] == "#e57373"
    assert option["series"][2]["name"] == "Saldo"
    assert option["series"][2]["lineStyle"]["width"] == 3
    assert option["series"][2]["data"] == [60.0, -10.0]
    assert option["series"][2]["markLine"]["data"][0]["yAxis"] == 0
    assert option["legend"]["show"] is True
    assert option["yAxis"]["min"] < 0 < option["yAxis"]["max"]
