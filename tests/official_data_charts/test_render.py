"""Render JSON/MD/HTML 16:9 con SVG puro (cero red)."""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from tigani_broadcast.official_data_charts.models import (
    ChartArtifact,
    ChartsPackage,
    SeriesData,
    SeriesMetrics,
    SeriesObservation,
)
from tigani_broadcast.official_data_charts.render import (
    render_artifact_html,
    render_charts_json,
    render_charts_markdown,
    render_series_svg,
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


def test_verified_html_incluye_svg_fuente_y_sin_cdn() -> None:
    html = render_artifact_html(_verified(provisional=True), date(2025, 12, 11))
    assert "<svg" in html
    assert "Fuente: INDEC — IPC" in html
    assert "145.3_INGNACNAL_DICI_M_38" in html
    assert "2025-01-01" in html and "2025-02-01" in html
    assert "Datos provisorios" in html
    assert "*" in html
    assert "aspect-ratio: 16 / 9" in html or "aspect-ratio: 16 / 9" in html
    assert not re.search(r"<(script|link)[^>]+https?://", html, flags=re.I)
    assert "<script" not in html.lower()


def test_svg_sin_puntos_validos() -> None:
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
    svg = render_series_svg(
        [SeriesObservation(obs_date=date(2025, 1, 1), value=None)],
        metrics,
    )
    assert "sin datos" in svg


def test_svg_un_solo_punto_y_serie_constante() -> None:
    one = [
        SeriesObservation(obs_date=date(2025, 3, 1), value=10.0),
    ]
    metrics_one = SeriesMetrics(
        observation_count=1,
        valid_count=1,
        start_date=date(2025, 3, 1),
        end_date=date(2025, 3, 1),
        first_value=10.0,
        latest_value=10.0,
        min_value=10.0,
        min_date=date(2025, 3, 1),
        max_value=10.0,
        max_date=date(2025, 3, 1),
        absolute_change=None,
        percent_change=None,
        has_provisional_flags=False,
        flags_present=[],
    )
    svg_one = render_series_svg(one, metrics_one)
    assert "<circle" in svg_one
    assert "NaN" not in svg_one

    constant = [
        SeriesObservation(obs_date=date(2025, 1, 1), value=5.0),
        SeriesObservation(obs_date=date(2025, 2, 1), value=5.0),
        SeriesObservation(obs_date=date(2025, 3, 1), value=None),
        SeriesObservation(obs_date=date(2025, 4, 1), value=5.0),
    ]
    metrics_c = _metrics(
        start=date(2025, 1, 1),
        end=date(2025, 4, 1),
        first=5.0,
        latest=5.0,
    )
    svg_c = render_series_svg(constant, metrics_c)
    assert "NaN" not in svg_c
    assert "<polyline" in svg_c


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


def test_write_charts_package_pobla_html_path(tmp_path: Path) -> None:
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
    assert len(list(charts_dir.glob("*.html"))) == 2
    assert all(item.html_path is not None for item in result.items)
    assert "ch00_cue001_00.html" in (result.items[0].html_path or "")
