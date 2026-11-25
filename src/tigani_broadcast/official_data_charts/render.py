"""Render determinista de charts.json, charts.md y placas HTML 16:9 (SVG puro)."""

from __future__ import annotations

import html
import json
from datetime import date
from pathlib import Path

from tigani_broadcast.official_data_charts.models import (
    ChartArtifact,
    ChartsPackage,
    SeriesMetrics,
    SeriesObservation,
)

_SVG_WIDTH = 640
_SVG_HEIGHT = 280
_SVG_PAD_L = 56
_SVG_PAD_R = 20
_SVG_PAD_T = 20
_SVG_PAD_B = 44


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
    """Placa HTML5 16:9 autocontenida para OBS Browser Source (cero CDN/JS externo)."""
    if artifact.resolution_status == "verified_series":
        body = _verified_body(artifact, publish_date)
        status_class = "verified"
        status_label = "Serie oficial verificada"
    elif artifact.resolution_status == "quoted_only":
        body = _quoted_body(artifact)
        status_class = "quoted"
        status_label = "Dato citado"
    else:
        body = _fetch_error_body(artifact)
        status_class = "error"
        status_label = "Error de fetch"

    title = html.escape(artifact.indicator_label)
    status = html.escape(artifact.resolution_status)
    clock = html.escape(artifact.timestamp)
    label = html.escape(status_label)
    # El CSS no puede ir dentro de un f-string: contiene llaves literales.
    return (
        "<!DOCTYPE html>\n"
        '<html lang="es">\n'
        "<head>\n"
        '<meta charset="utf-8"/>\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1"/>\n'
        f"<title>{title}</title>\n"
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
    """Escribe HTML por artefacto, actualiza html_path y persiste JSON/Markdown."""
    charts_dir.mkdir(parents=True, exist_ok=True)
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
  background: #000;
  color: var(--ink);
  font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
}
.plate {
  width: 100%;
  max-width: 1920px;
  margin: 0 auto;
  aspect-ratio: 16 / 9;
  background:
    radial-gradient(1200px 500px at 10% -10%, #1d3348 0%, transparent 55%),
    linear-gradient(160deg, #101820 0%, #0c1219 100%);
  display: grid;
  grid-template-rows: auto 1fr auto;
  padding: 2.2% 2.8%;
  gap: 1.2%;
}
.banner {
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid var(--line);
  padding-bottom: 0.6%;
  font-size: clamp(14px, 1.4vw, 22px);
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
.headline {
  font-size: clamp(28px, 3.4vw, 56px);
  font-weight: 700;
  line-height: 1.05;
  margin: 0 0 0.4em;
}
.value {
  font-size: clamp(36px, 5vw, 84px);
  font-weight: 700;
  color: var(--accent);
  margin: 0 0 0.25em;
  font-variant-numeric: tabular-nums;
}
.meta, .side, .legend, .footer {
  color: var(--muted);
  font-size: clamp(14px, 1.35vw, 22px);
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
  padding: 2%;
  min-height: 0;
}
.chart-wrap svg { width: 100%; height: auto; display: block; }
.legend {
  margin-top: 0.8em;
  padding: 0.7em 0.9em;
  border-left: 3px solid var(--warn);
  background: rgba(232, 184, 74, 0.08);
}
.footer {
  border-top: 1px solid var(--line);
  padding-top: 0.7%;
  font-size: clamp(12px, 1.1vw, 18px);
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
    svg = render_series_svg(series.observations, metrics)
    change = _format_percent(metrics.percent_change)
    period = f"{metrics.start_date.isoformat()} → {metrics.end_date.isoformat()}"
    provisional = ""
    if metrics.has_provisional_flags:
        flags = ", ".join(html.escape(flag) for flag in metrics.flags_present)
        provisional = f'<div class="prov">Datos provisorios / estimados (signos: {flags})</div>'
    latest = html.escape(_format_number(metrics.latest_value))
    pub = html.escape(publish_date.isoformat())
    footer = (
        f"{html.escape(series.source_attribution)} · "
        f"series_id={html.escape(series.series_id)} · "
        f"período {html.escape(period)}"
    )
    return f"""
  <section class="content">
    <div>
      <h1 class="headline">{html.escape(artifact.indicator_label)}</h1>
      <p class="value">{html.escape(artifact.raw_value_text)}</p>
      <p class="meta">Citado en exposición · publish_date {pub}</p>
      <div class="chart-wrap">{svg}</div>
    </div>
    <aside class="side">
      <strong>Último dato oficial</strong>
      <div class="value" style="font-size:clamp(28px,3.2vw,48px)">{latest}</div>
      <p class="meta">Variación en el tramo: {html.escape(change)}</p>
      <p class="meta">Unidad: {html.escape(series.unit)}</p>
      <p class="meta">Frecuencia: {html.escape(series.frequency)}</p>
    </aside>
  </section>
  <footer class="footer">
    <div>{footer}</div>
    {provisional}
  </footer>
"""


def _quoted_body(artifact: ChartArtifact) -> str:
    time_ref = artifact.time_reference or "sin referencia temporal explícita"
    return f"""
  <section class="content single">
    <div>
      <h1 class="headline">{html.escape(artifact.indicator_label)}</h1>
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
    return f"""
  <section class="content single">
    <div>
      <h1 class="headline">{html.escape(artifact.indicator_label)}</h1>
      <p class="value">{html.escape(artifact.raw_value_text)}</p>
      <div class="legend">No se pudo obtener la serie oficial. No se inventaron datos.</div>
      <p class="meta">Error: {html.escape(artifact.error_message)}</p>
    </div>
  </section>
  <footer class="footer">
    <div>fetch_error · revisar fuente / token / red y reintentar</div>
  </footer>
"""


def render_series_svg(
    observations: list[SeriesObservation],
    metrics: SeriesMetrics,
) -> str:
    """SVG puro determinista a partir de observaciones válidas."""
    points = [(obs.obs_date, obs.value) for obs in observations if obs.value is not None]
    if not points:
        return '<svg viewBox="0 0 640 280" role="img" aria-label="sin datos"></svg>'

    plot_w = _SVG_WIDTH - _SVG_PAD_L - _SVG_PAD_R
    plot_h = _SVG_HEIGHT - _SVG_PAD_T - _SVG_PAD_B
    min_v = metrics.min_value
    max_v = metrics.max_value
    if min_v == max_v:
        pad = abs(min_v) * 0.05 if min_v != 0 else 1.0
        min_v -= pad
        max_v += pad
    span = max_v - min_v

    n = len(points)
    coords: list[tuple[float, float]] = []
    for index, (_obs_date, value) in enumerate(points):
        assert value is not None
        x = _SVG_PAD_L if n == 1 else _SVG_PAD_L + (plot_w * index / (n - 1))
        y = _SVG_PAD_T + plot_h * (1.0 - ((value - min_v) / span))
        coords.append((x, y))

    polyline = " ".join(f"{x:.2f},{y:.2f}" for x, y in coords)
    area_pts = (
        f"{coords[0][0]:.2f},{_SVG_PAD_T + plot_h:.2f} "
        + polyline
        + f" {coords[-1][0]:.2f},{_SVG_PAD_T + plot_h:.2f}"
    )
    dots = "".join(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="3.5" fill="#3db8a8"/>' for x, y in coords)
    start_label = html.escape(metrics.start_date.isoformat())
    end_label = html.escape(metrics.end_date.isoformat())
    min_label = html.escape(_format_number(metrics.min_value))
    max_label = html.escape(_format_number(metrics.max_value))
    y_axis_bottom = _SVG_PAD_T + plot_h
    x_axis_right = _SVG_PAD_L + plot_w
    return "\n".join(
        [
            (
                f'<svg viewBox="0 0 {_SVG_WIDTH} {_SVG_HEIGHT}" '
                'role="img" aria-label="serie oficial">'
            ),
            (f'<rect x="0" y="0" width="{_SVG_WIDTH}" height="{_SVG_HEIGHT}" fill="transparent"/>'),
            (
                f'<line x1="{_SVG_PAD_L}" y1="{_SVG_PAD_T}" '
                f'x2="{_SVG_PAD_L}" y2="{y_axis_bottom}" '
                'stroke="#2b3b4d" stroke-width="1.5"/>'
            ),
            (
                f'<line x1="{_SVG_PAD_L}" y1="{y_axis_bottom}" '
                f'x2="{x_axis_right}" y2="{y_axis_bottom}" '
                'stroke="#2b3b4d" stroke-width="1.5"/>'
            ),
            f'<polygon points="{area_pts}" fill="rgba(61,184,168,0.18)"/>',
            (
                f'<polyline points="{polyline}" fill="none" stroke="#3db8a8" '
                'stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>'
            ),
            dots,
            (
                f'<text x="{_SVG_PAD_L}" y="{_SVG_HEIGHT - 14}" '
                f'fill="#9db0c3" font-size="12">{start_label}</text>'
            ),
            (
                f'<text x="{x_axis_right}" y="{_SVG_HEIGHT - 14}" '
                f'fill="#9db0c3" font-size="12" text-anchor="end">{end_label}</text>'
            ),
            (
                f'<text x="{_SVG_PAD_L - 8}" y="{_SVG_PAD_T + 4}" '
                f'fill="#9db0c3" font-size="12" text-anchor="end">{max_label}</text>'
            ),
            (
                f'<text x="{_SVG_PAD_L - 8}" y="{y_axis_bottom}" '
                f'fill="#9db0c3" font-size="12" text-anchor="end">{min_label}</text>'
            ),
            "</svg>",
        ]
    )


def _markdown_detail(item: ChartArtifact) -> str:
    if item.resolution_status == "verified_series":
        assert item.series is not None and item.metrics is not None
        change = _format_percent(item.metrics.percent_change)
        return (
            f"{item.series.source_attribution}; "
            f"{item.metrics.start_date.isoformat()}→{item.metrics.end_date.isoformat()}; "
            f"último={_format_number(item.metrics.latest_value)}; var={change}"
        )
    if item.resolution_status == "quoted_only":
        ref = item.time_reference or "—"
        return f"citado ({ref})"
    return item.error_message or "error"


def _format_percent(value: float | None) -> str:
    if value is None:
        return "n/d"
    return f"{value:+.2f}%"


def _format_number(value: float) -> str:
    if abs(value - round(value)) < 1e-9:
        return f"{value:.0f}"
    return f"{value:.4g}"


def _cell(value: str) -> str:
    return " ".join(value.split()).replace("|", "\\|")
