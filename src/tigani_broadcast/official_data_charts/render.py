"""Render determinista de charts.json, charts.md y placas HTML 16:9 (ECharts offline)."""

from __future__ import annotations

import html
import json
import shutil
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

from tigani_broadcast.official_data_charts.catalog import get_catalog_entry, is_valid_catalog_id
from tigani_broadcast.official_data_charts.models import (
    ChartArtifact,
    ChartNarrative,
    ChartsPackage,
    DataPoint,
    PlaybookChartType,
    SeriesData,
    SeriesMetrics,
    SeriesObservation,
)

_DENSE_LABEL_MAX = 14
_DENSE_SYMBOL_MAX = 24
_ASSETS_DIR = Path(__file__).resolve().parent / "assets"
_ECHARTS_ASSET = _ASSETS_DIR / "echarts.min.js"
_ECHARTS_FILENAME = "echarts.min.js"

_MONTHS_SHORT_ES = (
    "Ene",
    "Feb",
    "Mar",
    "Abr",
    "May",
    "Jun",
    "Jul",
    "Ago",
    "Sep",
    "Oct",
    "Nov",
    "Dic",
)
_FREQUENCY_ES = {
    "daily": "Diaria",
    "monthly": "Mensual",
    "quarterly": "Trimestral",
    "annual": "Anual",
}
_BAND_FILLS = (
    "rgba(61,184,168,0.12)",
    "rgba(232,184,74,0.12)",
    "rgba(157,176,195,0.14)",
)


def render_charts_json(package: ChartsPackage) -> str:
    """JSON UTF-8 indentado, con acentos intactos."""
    return json.dumps(package.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n"


def render_charts_markdown(package: ChartsPackage) -> str:
    """Resumen legible para el operador de producción."""
    lines = [
        "# Paquete de charts",
        "",
        f"- **publish_date:** {package.publish_date.isoformat()}",
    ]
    if package.source_chapters_path:
        lines.append(f"- **source_chapters_path:** `{package.source_chapters_path}`")
    lines.extend(["", f"- **items:** {len(package.items)}", "", "## Artefactos", ""])
    lines.append("| Cap | Cue | Timestamp | Estado | Indicador | Valor citado | Detalle | HTML |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for item in package.items:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(item.chapter_index),
                    str(item.cue_index),
                    item.timestamp,
                    item.resolution_status,
                    _cell(item.indicator_label),
                    _cell(item.raw_value_text),
                    _cell(_markdown_detail(item)),
                    _cell(item.html_path or "—"),
                ]
            )
            + " |"
        )
    lines.append("")
    return "\n".join(lines)


def render_artifact_html(artifact: ChartArtifact, publish_date: date) -> str:
    """Placa HTML5 16:9 autocontenida para OBS Browser Source (cero CDN)."""
    if artifact.resolution_status == "verified_series":
        body = _verified_body(artifact, publish_date)
        status_class = "verified"
        status_label = "Serie oficial verificada"
        head_extra = f'<script src="{_ECHARTS_FILENAME}"></script>\n'
    elif artifact.resolution_status == "quoted_only":
        body = _quoted_body(artifact)
        status_class = "quoted"
        status_label = "Dato citado"
        head_extra = ""
    else:
        body = _fetch_error_body(artifact)
        status_class = "error"
        status_label = "Error de fetch"
        head_extra = ""

    title = html.escape(_capitalize_headline(artifact.indicator_label))
    status = html.escape(artifact.resolution_status)
    clock = html.escape(artifact.timestamp)
    label = html.escape(status_label)
    return (
        "<!DOCTYPE html>\n"
        '<html lang="es">\n'
        "<head>\n"
        '<meta charset="utf-8"/>\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1"/>\n'
        f"<title>{title}</title>\n"
        f"{head_extra}"
        "<style>\n"
        f"{_PLATE_CSS}\n"
        "</style>\n"
        "</head>\n"
        "<body>\n"
        f'<main class="plate {status_class}" data-status="{status}">\n'
        '  <header class="banner">\n'
        f'    <span class="status">{label}</span>\n'
        f'    <span class="clock">{clock}</span>\n'
        "  </header>\n"
        f"{body}\n"
        "</main>\n"
        "</body>\n"
        "</html>\n"
    )


def write_charts_package(
    package: ChartsPackage,
    output_json: Path,
    charts_dir: Path,
    markdown_path: Path | None = None,
) -> ChartsPackage:
    """Escribe HTML por artefacto, copia ECharts offline y persiste JSON/Markdown."""
    charts_dir = Path(charts_dir)
    charts_dir.mkdir(parents=True, exist_ok=True)
    copy_echarts_runtime(charts_dir)

    updated: list[ChartArtifact] = []
    for index, artifact in enumerate(package.items):
        filename = f"ch{artifact.chapter_index:02d}_cue{artifact.cue_index:03d}_{index:02d}.html"
        path = charts_dir / filename
        path.write_text(
            render_artifact_html(artifact, package.publish_date),
            encoding="utf-8",
        )
        updated.append(artifact.model_copy(update={"html_path": str(path)}))

    result = package.model_copy(update={"items": updated})
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(render_charts_json(result), encoding="utf-8")
    if markdown_path is not None:
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(render_charts_markdown(result), encoding="utf-8")
    return result


def copy_echarts_runtime(destination_dir: Path) -> Path:
    """Copia `echarts.min.js` vendoreado a un directorio de placas (offline OBS)."""
    destination_dir = Path(destination_dir)
    destination_dir.mkdir(parents=True, exist_ok=True)
    if not _ECHARTS_ASSET.is_file():
        raise FileNotFoundError(f"falta el runtime ECharts vendoreado: {_ECHARTS_ASSET}")
    dest = destination_dir / _ECHARTS_FILENAME
    shutil.copy2(_ECHARTS_ASSET, dest)
    return dest


def echarts_asset_path() -> Path:
    """Ruta al `echarts.min.js` embebido en el paquete."""
    return _ECHARTS_ASSET


_PLATE_CSS = """
:root {
  --bg: #0f1720;
  --panel: #182230;
  --ink: #f4f7fb;
  --muted: #9db0c3;
  --accent: #3db8a8;
  --warn: #e8b84a;
  --danger: #e57373;
  --line: #2b3b4d;
}
* { box-sizing: border-box; }
html, body {
  margin: 0;
  padding: 0;
  width: 100%;
  height: 100%;
  min-width: 960px;
  min-height: 540px;
  overflow: auto;
  background: #000;
  color: var(--ink);
  font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
}
.plate {
  width: 100%;
  height: 100%;
  min-width: 960px;
  min-height: 540px;
  margin: 0 auto;
  overflow: hidden;
  background:
    radial-gradient(1200px 500px at 10% -10%, #1d3348 0%, transparent 55%),
    linear-gradient(160deg, #101820 0%, #0c1219 100%);
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  padding: 1.6% 2.4% 1.2%;
  gap: 0.8%;
}
.banner {
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid var(--line);
  padding-bottom: 0.6%;
  font-size: clamp(14px, 1.4vw, 44px);
  letter-spacing: 0.04em;
  text-transform: uppercase;
}
.status { color: var(--accent); font-weight: 700; }
.quoted .status { color: var(--warn); }
.error .status { color: var(--danger); }
.clock { color: var(--muted); font-variant-numeric: tabular-nums; }
.content {
  display: grid;
  grid-template-columns: 1.55fr 1fr;
  gap: 2%;
  min-height: 0;
}
.content.single { grid-template-columns: 1fr; }
.content.narrative {
  grid-template-columns: 1fr;
  grid-template-rows: auto minmax(0, 1fr);
  min-height: 0;
  overflow: hidden;
}
.content > .stack {
  display: grid;
  grid-template-rows: auto auto auto minmax(0, 1fr);
  min-height: 0;
  gap: 0.6%;
}
.headline-row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 1.5%;
  flex-wrap: wrap;
  flex-shrink: 0;
}
.headline {
  font-size: clamp(26px, 3.1vw, 104px);
  font-weight: 700;
  line-height: 1.05;
  margin: 0 0 0.25em;
}
.badge {
  display: inline-flex;
  align-items: center;
  gap: 0.35em;
  padding: 0.28em 0.7em;
  border-radius: 999px;
  border: 1px solid var(--line);
  background: color-mix(in srgb, var(--panel) 80%, black);
  font-size: clamp(14px, 1.5vw, 48px);
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.badge.up {
  color: var(--danger);
  border-color: color-mix(in srgb, var(--danger) 45%, var(--line));
}
.badge.down {
  color: var(--accent);
  border-color: color-mix(in srgb, var(--accent) 45%, var(--line));
}
.badge.flat {
  color: var(--warn);
  border-color: color-mix(in srgb, var(--warn) 45%, var(--line));
}
.value {
  font-size: clamp(36px, 5vw, 168px);
  font-weight: 700;
  color: var(--accent);
  margin: 0 0 0.25em;
  font-variant-numeric: tabular-nums;
}
.meta, .side, .legend, .footer {
  color: var(--muted);
  font-size: clamp(14px, 1.35vw, 44px);
  line-height: 1.35;
}
.side {
  background: color-mix(in srgb, var(--panel) 88%, black);
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 4% 5%;
  align-self: stretch;
}
.side strong { color: var(--ink); display: block; margin-bottom: 0.35em; }
.chart-wrap {
  background: color-mix(in srgb, var(--panel) 70%, transparent);
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 0.6% 0.8%;
  min-height: 0;
  overflow: hidden;
  height: 100%;
}
#chart {
  width: 100%;
  height: 100%;
}
.legend {
  margin-top: 0.8em;
  padding: 0.7em 0.9em;
  border-left: 3px solid var(--warn);
  background: rgba(232, 184, 74, 0.08);
}
.kpi-bar {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 1%;
  margin: 0 0 0.45%;
  flex-shrink: 0;
}
.kpi-card {
  background: color-mix(in srgb, var(--panel) 88%, black);
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 0.45% 0.9%;
  min-width: 0;
}
.kpi-card .kpi-label {
  color: var(--muted);
  font-size: clamp(10px, 0.95vw, 32px);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  margin: 0 0 0.15em;
}
.kpi-card .kpi-value {
  color: var(--ink);
  font-size: clamp(14px, 1.55vw, 48px);
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  margin: 0;
}
.kpi-card .kpi-detail {
  color: var(--muted);
  font-size: clamp(10px, 0.95vw, 28px);
  margin: 0.15em 0 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.footer {
  border-top: 1px solid var(--line);
  padding-top: 0.45%;
  font-size: clamp(11px, 1.0vw, 36px);
  flex-shrink: 0;
  min-height: 0;
}
.footer .prov {
  color: var(--warn);
  margin-top: 0.35em;
}
"""


def _verified_body(artifact: ChartArtifact, publish_date: date) -> str:
    assert artifact.series is not None and artifact.metrics is not None
    series = artifact.series
    metrics = artifact.metrics
    narrative = artifact.narrative
    chart_unit = "base 100" if artifact.chart_type == "dual_base100" else series.unit
    chart_block = _echarts_chart_html(
        series.observations,
        metrics,
        narrative=narrative,
        unit=chart_unit,
        chart_type=artifact.chart_type,
        secondary_points=(
            artifact.secondary_series.points if artifact.secondary_series is not None else None
        ),
    )
    change = _format_percent(metrics.percent_change)
    period = f"{metrics.start_date.isoformat()} → {metrics.end_date.isoformat()}"
    provisional = ""
    if metrics.has_provisional_flags:
        flags = ", ".join(html.escape(flag) for flag in metrics.flags_present)
        provisional = f'<div class="prov">Datos provisorios / estimados (signos: {flags})</div>'
    latest = html.escape(_format_display_value(metrics.latest_value, series.unit))
    corte = html.escape(_format_corte(publish_date))
    title = html.escape(_capitalize_headline(artifact.indicator_label))
    frequency_es = html.escape(_frequency_label(series.frequency))
    footer = (
        f"{_source_line(artifact, series)} · "
        f"series_id={html.escape(series.series_id)} · "
        f"período {html.escape(period)}"
    )
    note_html = _editorial_note_html(artifact)

    if narrative is not None:
        badge_html = _headline_badge_html(narrative)
        kpi_html = _kpi_bar_html(narrative)
        return f"""
  <section class="content narrative">
    <div class="headline-row">
      <h1 class="headline">{title}</h1>
      {badge_html}
    </div>
    <div class="chart-wrap">{chart_block}</div>
  </section>
  <footer class="footer">
    {kpi_html}
    <div>{footer}</div>
    {note_html}
    <p class="meta">{_cited_line(artifact, corte)}</p>
    {provisional}
  </footer>
"""

    return f"""
  <section class="content">
    <div class="stack">
      <h1 class="headline">{title}</h1>
      <p class="value">{html.escape(artifact.raw_value_text)}</p>
      <p class="meta">Citado en exposición · {corte}</p>
      <div class="chart-wrap">{chart_block}</div>
    </div>
    <aside class="side">
      <strong>Último dato oficial</strong>
      <div class="value" style="font-size:clamp(28px,3.2vw,96px)">{latest}</div>
      <p class="meta">Variación en el tramo: {html.escape(change)}</p>
      <p class="meta">Unidad: {html.escape(series.unit)}</p>
      <p class="meta">Frecuencia: {frequency_es}</p>
    </aside>
  </section>
  <footer class="footer">
    <div>{footer}</div>
    {note_html}
    {provisional}
  </footer>
"""


def _cited_line(artifact: ChartArtifact, corte: str) -> str:
    """`corte` ya viene escapado. El playbook no repite el texto citado del locutor."""
    if artifact.playbook_id is not None:
        return f"Contexto oficial · {corte}"
    return f"Citado: {html.escape(artifact.raw_value_text)} · {corte}"


def _editorial_note_html(artifact: ChartArtifact) -> str:
    if artifact.editorial_note is None or not artifact.editorial_note.strip():
        return ""
    return f'<p class="meta editorial-note">{html.escape(artifact.editorial_note)}</p>'


def _source_line(artifact: ChartArtifact, series: SeriesData) -> str:
    primary = html.escape(series.source_attribution)
    secondary = artifact.secondary_series
    if secondary is None:
        return primary
    extra = secondary.label
    if is_valid_catalog_id(secondary.series_key):
        extra = get_catalog_entry(secondary.series_key).source_attribution
    return f"{primary} · {html.escape(extra)}"


def build_echarts_option(
    observations: list[SeriesObservation],
    metrics: SeriesMetrics,
    *,
    narrative: ChartNarrative | None = None,
    unit: str = "",
    chart_type: PlaybookChartType = "single_line",
    secondary_points: Sequence[DataPoint] | None = None,
) -> dict[str, Any]:
    """Option ECharts determinista (serializable a JSON) para placas verified_series."""
    points = [(obs.obs_date, obs.value) for obs in observations if obs.value is not None]
    # El eje se deriva de los puntos; metrics queda en la firma por contrato del caller.
    del metrics
    if chart_type == "dual_base100" and secondary_points:
        return _dual_base100_option(observations, secondary_points)
    if chart_type == "bar_diverging":
        return _bar_diverging_option(observations)
    if not points:
        return {
            "animation": False,
            "title": {
                "text": "Sin datos",
                "left": "center",
                "top": "middle",
                "textStyle": {"color": "#9db0c3", "fontSize": 18},
            },
        }

    categories = _category_labels([item[0] for item in points])
    values = [float(item[1]) for item in points]
    n = len(values)
    show_all_labels = n <= _DENSE_LABEL_MAX
    y_min, y_max = _y_axis_bounds(values)

    series_payload: dict[str, Any] = {
        "type": "line",
        "smooth": 0.2,
        "showSymbol": n <= _DENSE_SYMBOL_MAX,
        "symbol": "circle",
        "symbolSize": 9,
        "data": values,
        "lineStyle": {"width": 3, "color": "#3db8a8"},
        "itemStyle": {"color": "#3db8a8"},
        "areaStyle": {
            "color": {
                "type": "linear",
                "x": 0,
                "y": 0,
                "x2": 0,
                "y2": 1,
                "colorStops": [
                    {"offset": 0, "color": "rgba(61,184,168,0.45)"},
                    {"offset": 1, "color": "rgba(61,184,168,0.03)"},
                ],
            }
        },
        "label": {
            "show": show_all_labels,
            "position": "top",
            "fontSize": 15,
            "fontWeight": 600,
            "color": "#f4f7fb",
            "formatter": "__LABEL_FORMATTER__",
        },
    }

    if not show_all_labels:
        series_payload["markPoint"] = _mark_point_payload(values, unit=unit)

    if narrative is not None and narrative.regime_bands:
        series_payload["markArea"] = _mark_area_payload(
            narrative,
            dates=[item[0] for item in points],
        )

    return {
        "animation": True,
        "animationDuration": 750,
        "animationEasing": "cubicOut",
        "grid": {"left": 16, "right": 28, "top": 44, "bottom": 34, "containLabel": True},
        "tooltip": {"trigger": "axis", "show": False},
        "xAxis": {
            "type": "category",
            "boundaryGap": False,
            "data": categories,
            "axisLine": {"lineStyle": {"color": "#2b3b4d"}},
            "axisTick": {"show": False},
            "axisLabel": {
                "show": True,
                "color": "#c8d6e5",
                "fontSize": 15,
                "interval": 0 if show_all_labels else "auto",
            },
        },
        "yAxis": {
            "type": "value",
            "scale": True,
            "min": y_min,
            "max": y_max,
            "axisLine": {"show": False},
            "axisTick": {"show": False},
            "axisLabel": {
                "color": "#c8d6e5",
                "fontSize": 14,
                "formatter": "__Y_FORMATTER__",
            },
            "splitLine": {
                "show": True,
                "lineStyle": {"type": "dashed", "color": "#243242", "width": 1},
            },
        },
        "series": [series_payload],
        "_tiganiUnit": unit,
    }


def _dual_base100_option(
    observations: list[SeriesObservation],
    secondary_points: Sequence[DataPoint],
) -> dict[str, Any]:
    secondary_by_date = {point.obs_date: float(point.value) for point in secondary_points}
    aligned = [
        (obs.obs_date, float(obs.value), secondary_by_date[obs.obs_date])
        for obs in observations
        if obs.value is not None and obs.obs_date in secondary_by_date
    ]
    if len(aligned) < 2:
        return {
            "animation": False,
            "title": {
                "text": "Sin datos",
                "left": "center",
                "top": "middle",
                "textStyle": {"color": "#9db0c3", "fontSize": 18},
            },
        }
    categories = _category_labels([row[0] for row in aligned])
    primary_values = [row[1] for row in aligned]
    secondary_values = [row[2] for row in aligned]
    show_all = len(aligned) <= _DENSE_LABEL_MAX
    y_min, y_max = _y_axis_bounds([*primary_values, *secondary_values, 100.0])
    return {
        "animation": True,
        "animationDuration": 750,
        "animationEasing": "cubicOut",
        "legend": {
            "show": True,
            "top": 0,
            "textStyle": {"color": "#f4f7fb", "fontSize": 14},
        },
        "grid": {"left": 16, "right": 28, "top": 72, "bottom": 34, "containLabel": True},
        "tooltip": {"trigger": "axis", "show": False},
        "xAxis": {
            "type": "category",
            "boundaryGap": False,
            "data": categories,
            "axisLine": {"lineStyle": {"color": "#2b3b4d"}},
            "axisTick": {"show": False},
            "axisLabel": {
                "show": True,
                "color": "#c8d6e5",
                "fontSize": 15,
                "interval": 0 if show_all else "auto",
            },
        },
        "yAxis": {
            "type": "value",
            "scale": True,
            "min": y_min,
            "max": y_max,
            "axisLine": {"show": False},
            "axisTick": {"show": False},
            "axisLabel": {
                "color": "#c8d6e5",
                "fontSize": 14,
                "formatter": "__Y_FORMATTER__",
            },
            "splitLine": {
                "show": True,
                "lineStyle": {"type": "dashed", "color": "#243242", "width": 1},
            },
        },
        "series": [
            _indexed_line_series(
                "IPC",
                primary_values,
                color="#3db8a8",
                show_all=show_all,
                with_base_line=True,
            ),
            _indexed_line_series(
                "Dólar mayorista",
                secondary_values,
                color="#e8b84a",
                show_all=show_all,
                with_base_line=False,
            ),
        ],
        "_tiganiUnit": "base 100",
    }


def _indexed_line_series(
    name: str,
    values: list[float],
    *,
    color: str,
    show_all: bool,
    with_base_line: bool,
) -> dict[str, Any]:
    last = len(values) - 1
    data = [
        {
            "value": value,
            "label": {"show": show_all or index == last, "position": "top"},
        }
        for index, value in enumerate(values)
    ]
    payload: dict[str, Any] = {
        "name": name,
        "type": "line",
        "smooth": 0.2,
        "symbol": "circle",
        "symbolSize": 9,
        "data": data,
        "lineStyle": {"width": 3, "color": color},
        "itemStyle": {"color": color},
        "label": {
            "show": True,
            "position": "top",
            "fontSize": 15,
            "fontWeight": 600,
            "color": "#f4f7fb",
            "formatter": "__LABEL_FORMATTER__",
        },
    }
    if with_base_line:
        payload["markLine"] = {
            "silent": True,
            "symbol": "none",
            "lineStyle": {"type": "dashed", "color": "#9db0c3", "width": 1},
            "data": [
                {
                    "yAxis": 100,
                    "label": {"formatter": "Base 100", "color": "#c8d6e5", "fontSize": 12},
                }
            ],
        }
    return payload


def _bar_diverging_option(observations: list[SeriesObservation]) -> dict[str, Any]:
    points = [(obs.obs_date, float(obs.value)) for obs in observations if obs.value is not None]
    if not points:
        return {
            "animation": False,
            "title": {
                "text": "Sin datos",
                "left": "center",
                "top": "middle",
                "textStyle": {"color": "#9db0c3", "fontSize": 18},
            },
        }
    categories = _category_labels([item[0] for item in points])
    values = [item[1] for item in points]
    show_all = len(values) <= _DENSE_LABEL_MAX
    y_min, y_max = _diverging_y_bounds(values)
    data = []
    for value in values:
        positive = value >= 0
        data.append(
            {
                "value": value,
                "itemStyle": {"color": "#3db8a8" if positive else "#e57373"},
                "label": {
                    "show": True,
                    "position": "top" if positive else "bottom",
                    "color": "#f4f7fb",
                    "fontSize": 15,
                    "fontWeight": 600,
                },
            }
        )
    return {
        "animation": True,
        "animationDuration": 750,
        "animationEasing": "cubicOut",
        "grid": {"left": 16, "right": 28, "top": 44, "bottom": 34, "containLabel": True},
        "tooltip": {"trigger": "axis", "show": False},
        "xAxis": {
            "type": "category",
            "data": categories,
            "axisLine": {"lineStyle": {"color": "#2b3b4d"}},
            "axisTick": {"show": False},
            "axisLabel": {
                "show": True,
                "color": "#c8d6e5",
                "fontSize": 15,
                "interval": 0 if show_all else "auto",
            },
        },
        "yAxis": {
            "type": "value",
            "min": y_min,
            "max": y_max,
            "axisLine": {"show": False},
            "axisTick": {"show": False},
            "axisLabel": {
                "color": "#c8d6e5",
                "fontSize": 14,
                "formatter": "__Y_FORMATTER__",
            },
            "splitLine": {
                "show": True,
                "lineStyle": {"type": "dashed", "color": "#243242", "width": 1},
            },
        },
        "series": [
            {
                "type": "bar",
                "data": data,
                "label": {
                    "show": True,
                    "fontSize": 15,
                    "fontWeight": 600,
                    "color": "#f4f7fb",
                    "formatter": "__LABEL_FORMATTER__",
                },
                "markLine": {
                    "silent": True,
                    "symbol": "none",
                    "lineStyle": {"color": "#c8d6e5", "width": 1.5},
                    "data": [{"yAxis": 0, "label": {"show": False}}],
                },
            }
        ],
        "_tiganiUnit": "%",
    }


def _diverging_y_bounds(values: list[float]) -> tuple[float, float]:
    """Incluye el cero y deja aire por encima del máximo y por debajo del mínimo."""
    span = max(max(values) - min(values), 0.5)
    pad = span * 0.18
    y_min = round(min(values) - pad, 1)
    y_max = round(max(values) + pad, 1)
    if y_min >= 0:
        y_min = round(-max(pad, 0.5), 1)
    if y_max <= 0:
        y_max = round(max(pad, 0.5), 1)
    return float(y_min), float(y_max)


def _echarts_chart_html(
    observations: list[SeriesObservation],
    metrics: SeriesMetrics,
    *,
    narrative: ChartNarrative | None,
    unit: str,
    chart_type: PlaybookChartType = "single_line",
    secondary_points: Sequence[DataPoint] | None = None,
) -> str:
    option = build_echarts_option(
        observations,
        metrics,
        narrative=narrative,
        unit=unit,
        chart_type=chart_type,
        secondary_points=secondary_points,
    )
    option_json = json.dumps(option, ensure_ascii=False)
    option_json = option_json.replace("</", "<\\/")
    # Reemplazar placeholders de formatters por funciones JS reales.
    option_json = option_json.replace('"__LABEL_FORMATTER__"', "null")
    option_json = option_json.replace('"__Y_FORMATTER__"', "null")
    unit_json = json.dumps(unit, ensure_ascii=False)
    return f"""
<div id="chart" role="img" aria-label="serie oficial"></div>
<script>
(function () {{
  const unit = {unit_json};
  function groupThousands(digits) {{
    return digits.replace(/\\B(?=(\\d{{3}})+(?!\\d))/g, ".");
  }}
  function formatValue(value) {{
    const n = Number(value);
    if (!Number.isFinite(n)) return "";
    const abs = Math.abs(n);
    const whole = Math.abs(abs - Math.round(abs)) < 1e-9;
    let body = whole ? String(Math.round(abs)) : abs.toFixed(1).replace(".", ",");
    if (abs >= 1000) {{
      const parts = body.split(",");
      parts[0] = groupThousands(parts[0]);
      body = parts.join(",");
    }}
    if (n < 0) body = "-" + body;
    const u = String(unit || "").trim().toLowerCase();
    if (u === "%" || u === "p.p." || u === "pp" || u.includes("%") || u.includes("porcent")) {{
      return body + "%";
    }}
    return body;
  }}
  const option = {option_json};
  if (option.yAxis && option.yAxis.axisLabel) {{
    option.yAxis.axisLabel.formatter = function (value) {{ return formatValue(value); }};
  }}
  (option.series || []).forEach(function (serie) {{
    if (serie && serie.label) {{
      serie.label.formatter = function (params) {{ return formatValue(params.value); }};
    }}
  }});
  const el = document.getElementById("chart");
  const chart = echarts.init(el, null, {{ renderer: "canvas" }});
  chart.setOption(option);
  const wrap = (el && el.closest) ? el.closest(".chart-wrap") : el;
  const axisX = option.xAxis && option.xAxis.axisLabel;
  const axisY = option.yAxis && option.yAxis.axisLabel;
  const seriesLabels = (option.series || []).map(function (serie) {{
    const label = serie && serie.label;
    return (label && label.fontSize) || 15;
  }});
  const baseX = (axisX && axisX.fontSize) || 15;
  const baseY = (axisY && axisY.fontSize) || 14;
  let scaleFrame = 0;
  function fitChart() {{
    const container = wrap || el;
    if (!container) return;
    chart.resize();
    if (scaleFrame) cancelAnimationFrame(scaleFrame);
    scaleFrame = requestAnimationFrame(function () {{
      scaleFrame = 0;
      const scale = Math.max(0.85, Math.min(2.0, container.clientWidth / 1280));
      const patch = {{
        xAxis: {{ axisLabel: {{ fontSize: Math.round(baseX * scale) }} }},
        yAxis: {{ axisLabel: {{ fontSize: Math.round(baseY * scale) }} }}
      }};
      if (seriesLabels.length) {{
        patch.series = seriesLabels.map(function (baseLabel) {{
          return {{ label: {{ fontSize: Math.round(baseLabel * scale) }} }};
        }});
      }}
      chart.setOption(patch);
    }});
  }}
  window.addEventListener("resize", fitChart);
  if (wrap && typeof ResizeObserver !== "undefined") {{
    const observer = new ResizeObserver(fitChart);
    observer.observe(wrap);
  }}
  fitChart();
}})();
</script>
"""


def _y_axis_bounds(values: list[float]) -> tuple[float, float]:
    """Margen cómodo para que etiquetas y el piso de la curva no se recorten."""
    v_min = min(values)
    v_max = max(values)
    span = max(v_max - v_min, 0.5)
    pad = span * 0.18
    y_min = round(v_min - pad, 1)
    y_max = round(v_max + pad, 1)
    if all(value >= 0 for value in values) and y_min < 0:
        y_min = 0.0
    if y_max <= y_min:
        y_max = round(y_min + span, 1)
    return float(y_min), float(y_max)


def _category_labels(dates: list[date]) -> list[str]:
    labels: list[str] = []
    for index, obs_date in enumerate(dates):
        show_year = index == 0 or index == len(dates) - 1
        if not show_year and index > 0 and obs_date.year != dates[index - 1].year:
            show_year = True
        labels.append(_format_month_tick(obs_date, show_year=show_year))
    return labels


def _format_month_tick(obs_date: date, *, show_year: bool) -> str:
    month = _MONTHS_SHORT_ES[obs_date.month - 1]
    if show_year:
        return f"{month} {obs_date.year % 100:02d}"
    return month


def _mark_point_payload(
    values: list[float],
    *,
    unit: str,
) -> dict[str, Any]:
    min_i = min(range(len(values)), key=lambda i: values[i])
    max_i = max(range(len(values)), key=lambda i: values[i])
    last_i = len(values) - 1
    points = []
    for index, name in ((max_i, "Máx"), (min_i, "Mín"), (last_i, "Último")):
        points.append(
            {
                "name": name,
                "coord": [index, values[index]],
                "value": values[index],
                "label": {
                    "show": True,
                    "formatter": _format_display_value(values[index], unit),
                    "color": "#f4f7fb",
                    "fontSize": 14,
                    "fontWeight": 700,
                },
                "itemStyle": {"color": "#e8b84a"},
            }
        )
    return {
        "symbol": "pin",
        "symbolSize": 48,
        "data": points,
    }


def _mark_area_payload(
    narrative: ChartNarrative,
    *,
    dates: list[date],
) -> dict[str, Any]:
    data: list[list[dict[str, Any]]] = []
    for index, band in enumerate(narrative.regime_bands):
        start_i = _nearest_index(dates, band.start_date)
        end_i = _nearest_index(dates, band.end_date)
        if start_i > end_i:
            start_i, end_i = end_i, start_i
        fill = _BAND_FILLS[index % len(_BAND_FILLS)]
        safe_label = html.escape(band.label)
        data.append(
            [
                {
                    "name": safe_label,
                    "xAxis": start_i,
                    "itemStyle": {"color": fill},
                    "label": {
                        "show": True,
                        "position": "insideTop",
                        "color": "#9db0c3",
                        "fontSize": 12,
                        "formatter": safe_label,
                    },
                },
                {"xAxis": end_i},
            ]
        )
    return {"silent": True, "data": data}


def _nearest_index(dates: list[date], target: date) -> int:
    return min(range(len(dates)), key=lambda i: abs((dates[i] - target).days))


def _headline_badge_html(narrative: ChartNarrative) -> str:
    if narrative.headline_badge is None:
        return ""
    direction = narrative.delta_direction or "flat"
    return (
        f'<span class="badge {html.escape(direction)}">'
        f"{html.escape(narrative.headline_badge)}</span>"
    )


def _kpi_bar_html(narrative: ChartNarrative) -> str:
    if not narrative.kpis:
        return ""
    cards: list[str] = []
    for kpi in narrative.kpis[:3]:
        detail = ""
        if kpi.detail:
            detail = f'<p class="kpi-detail">{html.escape(kpi.detail)}</p>'
        cards.append(
            '<div class="kpi-card">'
            f'<p class="kpi-label">{html.escape(kpi.label)}</p>'
            f'<p class="kpi-value">{html.escape(kpi.formatted_value)}</p>'
            f"{detail}"
            "</div>"
        )
    return f'<div class="kpi-bar">{"".join(cards)}</div>'


def _quoted_body(artifact: ChartArtifact) -> str:
    time_ref = artifact.time_reference or "sin referencia temporal explícita"
    title = html.escape(_capitalize_headline(artifact.indicator_label))
    return f"""
  <section class="content single">
    <div>
      <h1 class="headline">{title}</h1>
      <p class="value">{html.escape(artifact.raw_value_text)}</p>
      <p class="meta">Referencia temporal: {html.escape(time_ref)}</p>
      <p class="meta">Timestamp: {html.escape(artifact.timestamp)}</p>
      <div class="legend">Dato citado en exposición — sin serie oficial asociada</div>
    </div>
  </section>
  <footer class="footer">
    <div>Placa textual · no sustituye series oficiales</div>
  </footer>
"""


def _fetch_error_body(artifact: ChartArtifact) -> str:
    assert artifact.error_message is not None
    title = html.escape(_capitalize_headline(artifact.indicator_label))
    return f"""
  <section class="content single">
    <div>
      <h1 class="headline">{title}</h1>
      <p class="value">{html.escape(artifact.raw_value_text)}</p>
      <div class="legend">No se pudo obtener la serie oficial. No se inventaron datos.</div>
      <p class="meta">Error: {html.escape(artifact.error_message)}</p>
    </div>
  </section>
  <footer class="footer">
    <div>fetch_error · revisar fuente / token / red y reintentar</div>
  </footer>
"""


def _markdown_detail(item: ChartArtifact) -> str:
    if item.resolution_status == "verified_series":
        assert item.series is not None and item.metrics is not None
        change = _format_percent(item.metrics.percent_change)
        return (
            f"{item.series.source_attribution}; "
            f"{item.metrics.start_date.isoformat()}→{item.metrics.end_date.isoformat()}; "
            f"último={_format_display_value(item.metrics.latest_value, item.series.unit)}; "
            f"var={change}"
        )
    if item.resolution_status == "quoted_only":
        ref = item.time_reference or "—"
        return f"citado ({ref})"
    return item.error_message or "error"


def _format_percent(value: float | None) -> str:
    if value is None:
        return "n/d"
    sign = "+" if value >= 0 else "−"
    return f"{sign}{_fmt_es_decimal(abs(value), 1)}%"


def _format_number(value: float) -> str:
    if abs(value - round(value)) < 1e-9:
        as_int = int(round(value))
        if abs(as_int) >= 1000:
            return f"{as_int:,}".replace(",", ".")
        return str(as_int)
    return _fmt_es_decimal(value, 1)


def _format_display_value(value: float, unit: str = "") -> str:
    normalized = unit.strip().casefold()
    if normalized in {"%", "p.p.", "pp"} or normalized.endswith("%") or "porcent" in normalized:
        return f"{_fmt_es_decimal(value, 1)}%"
    return _format_number(value)


def _fmt_es_decimal(value: float, decimals: int) -> str:
    return f"{value:.{decimals}f}".replace(".", ",")


def _capitalize_headline(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return stripped
    return stripped[0].upper() + stripped[1:]


def _format_corte(publish_date: date) -> str:
    return f"Corte: {publish_date.day:02d}/{publish_date.month:02d}/{publish_date.year}"


def _frequency_label(frequency: str) -> str:
    return _FREQUENCY_ES.get(frequency, frequency)


def _cell(value: str) -> str:
    return " ".join(value.split()).replace("|", "\\|")
