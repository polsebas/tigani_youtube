"""Render determinista de assets.json, assets.md y placas HTML 16:9 para OBS."""

from __future__ import annotations

import html
import json
import os
from pathlib import Path

from tigani_broadcast.visual_assets_fetcher.models import (
    VisualAssetArtifact,
    VisualAssetsPackage,
)


def render_assets_json(package: VisualAssetsPackage) -> str:
    """JSON UTF-8 indentado, con acentos intactos."""
    return json.dumps(package.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n"


def render_assets_markdown(package: VisualAssetsPackage) -> str:
    """Tabla resumen para el operador de producción."""
    lines = [
        "# Paquete de activos visuales",
        "",
        f"- **portrait_layout:** {package.portrait_layout}",
    ]
    if package.source_chapters_path:
        lines.append(f"- **source_chapters_path:** `{package.source_chapters_path}`")
    lines.extend(["", f"- **items:** {len(package.items)}", "", "## Artefactos", ""])
    lines.append("| Cap | Cue | Timestamp | Estado | Sujeto | Occ | Crédito | Imagen | HTML |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for item in package.items:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(item.chapter_index),
                    str(item.cue_index),
                    item.timestamp,
                    item.status,
                    _cell(item.subject_label),
                    str(item.occurrences_count),
                    _cell(_markdown_credit(item)),
                    _cell(item.local_image_path or "—"),
                    _cell(item.html_path or "—"),
                ]
            )
            + " |"
        )
    lines.append("")
    return "\n".join(lines)


def render_visual_artifact_html(
    artifact: VisualAssetArtifact,
    *,
    relative_image_src: str | None = None,
) -> str:
    """Placa HTML5 16:9 autocontenida para OBS Browser Source (cero CDN/JS externo)."""
    if artifact.status == "verified_asset":
        body = _verified_body(artifact, relative_image_src=relative_image_src)
        status_class = "verified"
        status_label = "Imagen verificada"
    elif artifact.status == "fallback_card":
        body = _fallback_body(artifact)
        status_class = "fallback"
        status_label = "Placa de respaldo"
    else:
        body = _fetch_error_body(artifact)
        status_class = "error"
        status_label = "Error de fetch"

    title = html.escape(artifact.subject_label)
    status = html.escape(artifact.status)
    clock = html.escape(artifact.timestamp)
    label = html.escape(status_label)
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


def rerender_visuals_package(assets_json_path: Path) -> VisualAssetsPackage:
    """Regenera placas HTML y `assets.md` desde un `assets.json` local, sin bajar imágenes."""
    path = Path(assets_json_path)
    if not path.is_file():
        raise FileNotFoundError(
            f"no existe assets.json: {path}. Corré primero la etapa visuals sin --rerender-only."
        )
    package = VisualAssetsPackage.model_validate_json(path.read_text(encoding="utf-8"))
    return write_visual_assets_package(
        package,
        output_json=path,
        assets_dir=path.parent / "assets",
        markdown_path=path.with_suffix(".md"),
    )


def write_visual_assets_package(
    package: VisualAssetsPackage,
    output_json: Path,
    assets_dir: Path,
    markdown_path: Path | None = None,
) -> VisualAssetsPackage:
    """Escribe HTML por artefacto, actualiza html_path y persiste JSON/Markdown."""
    assets_dir.mkdir(parents=True, exist_ok=True)
    updated: list[VisualAssetArtifact] = []
    for index, artifact in enumerate(package.items):
        filename = f"ch{artifact.chapter_index:02d}_cue{artifact.cue_index:03d}_{index:02d}.html"
        path = assets_dir / filename
        relative_image_src = _relative_image_src(artifact, html_path=path)
        path.write_text(
            render_visual_artifact_html(artifact, relative_image_src=relative_image_src),
            encoding="utf-8",
        )
        updated.append(artifact.model_copy(update={"html_path": str(path)}))

    result = package.model_copy(update={"items": updated})
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(render_assets_json(result), encoding="utf-8")
    if markdown_path is not None:
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(render_assets_markdown(result), encoding="utf-8")
    return result


def _relative_image_src(artifact: VisualAssetArtifact, *, html_path: Path) -> str | None:
    if artifact.local_image_path is None:
        return None
    image_path = Path(artifact.local_image_path)
    return Path(os.path.relpath(image_path, html_path.parent)).as_posix()


def _markdown_credit(item: VisualAssetArtifact) -> str:
    if item.status == "verified_asset" and item.attribution is not None:
        attr = item.attribution
        return f"{attr.author} · {attr.license_name} · {attr.provider}"
    if item.status == "fetch_error":
        return item.error_message or "error"
    return "sin imagen licenciada"


def _cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _credit_footer(artifact: VisualAssetArtifact) -> str:
    assert artifact.attribution is not None
    attr = artifact.attribution
    author = html.escape(attr.author)
    license_name = html.escape(attr.license_name)
    provider = html.escape(attr.provider)
    return (
        '  <footer class="footer credit">\n'
        f"    <strong>Crédito:</strong> {author} · "
        f"<strong>Licencia:</strong> {license_name} · "
        f"<strong>Fuente:</strong> {provider}\n"
        "  </footer>"
    )


def _verified_body(
    artifact: VisualAssetArtifact,
    *,
    relative_image_src: str | None,
) -> str:
    assert artifact.attribution is not None
    attr = artifact.attribution
    src = relative_image_src
    if src is None or src.strip() == "":
        src = Path(artifact.local_image_path or "").name
    src_esc = html.escape(src, quote=True)
    subject = html.escape(artifact.subject_label)
    context = html.escape(artifact.context_text)
    clock = html.escape(artifact.timestamp)
    author = html.escape(attr.author)
    license_name = html.escape(attr.license_name)
    provider = html.escape(attr.provider)

    is_portrait = attr.width is not None and attr.height is not None and attr.height > attr.width
    if not is_portrait:
        return (
            '  <section class="content single landscape-layout">\n'
            '    <header class="headline-row">\n'
            f'      <h1 class="headline">{subject}</h1>\n'
            f'      <p class="meta">{clock}</p>\n'
            "    </header>\n"
            '    <figure class="media landscape">\n'
            f'      <img src="{src_esc}" alt="{subject}"/>\n'
            "    </figure>\n"
            f"{_credit_footer(artifact)}\n"
            "  </section>"
        )

    if artifact.portrait_layout == "contain":
        return (
            '  <section class="content single contain-layout">\n'
            '    <header class="headline-row">\n'
            f'      <h1 class="headline">{subject}</h1>\n'
            f'      <p class="meta">{clock}</p>\n'
            "    </header>\n"
            '    <figure class="media contain">\n'
            f'      <img src="{src_esc}" alt="{subject}"/>\n'
            "    </figure>\n"
            f"{_credit_footer(artifact)}\n"
            "  </section>"
        )

    # sidebar (default para retrato)
    return (
        '  <section class="content sidebar-layout">\n'
        '    <figure class="media sidebar">\n'
        f'      <img src="{src_esc}" alt="{subject}"/>\n'
        "    </figure>\n"
        '    <aside class="side">\n'
        f'      <h1 class="headline">{subject}</h1>\n'
        f'      <p class="meta">{clock}</p>\n'
        f'      <p class="meta">{context}</p>\n'
        '      <p class="credit">\n'
        f"        <strong>Crédito:</strong> {author}<br/>\n"
        f"        <strong>Licencia:</strong> {license_name}<br/>\n"
        f"        <strong>Fuente:</strong> {provider}\n"
        "      </p>\n"
        "    </aside>\n"
        "  </section>"
    )


def _fallback_body(artifact: VisualAssetArtifact) -> str:
    subject = html.escape(artifact.subject_label)
    context = html.escape(artifact.context_text)
    clock = html.escape(artifact.timestamp)
    return (
        '  <section class="content single">\n'
        '    <div class="side">\n'
        f'      <h1 class="headline">{subject}</h1>\n'
        f'      <p class="meta">{clock}</p>\n'
        f'      <p class="meta">{context}</p>\n'
        '      <p class="value">Placa contextual — sin imagen con licencia verificada</p>\n'
        "    </div>\n"
        "  </section>"
    )


def _fetch_error_body(artifact: VisualAssetArtifact) -> str:
    subject = html.escape(artifact.subject_label)
    message = html.escape(artifact.error_message or "error desconocido")
    return (
        '  <section class="content single">\n'
        '    <div class="side">\n'
        f'      <h1 class="headline">{subject}</h1>\n'
        f'      <p class="value">Error de fetch</p>\n'
        f'      <p class="meta">{message}</p>\n'
        "    </div>\n"
        "  </section>"
    )


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
  background:
    radial-gradient(1200px 500px at 10% -10%, #1d3348 0%, transparent 55%),
    linear-gradient(160deg, #101820 0%, #0c1219 100%);
  display: grid;
  grid-template-rows: auto 1fr;
  padding: 2.2% 2.8%;
  gap: 1.2%;
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
.fallback .status { color: var(--warn); }
.error .status { color: var(--danger); }
.clock { color: var(--muted); font-variant-numeric: tabular-nums; }
.content {
  display: grid;
  gap: 2%;
  min-height: 0;
}
.content.single {
  grid-template-rows: auto 1fr auto;
}
.content.sidebar-layout {
  grid-template-columns: 1fr 1.05fr;
  align-items: stretch;
}
.headline-row { margin-bottom: 0.4%; }
.headline {
  font-size: clamp(24px, 2.8vw, 96px);
  font-weight: 700;
  line-height: 1.08;
  margin: 0 0 0.25em;
}
.value {
  font-size: clamp(22px, 2.4vw, 80px);
  font-weight: 700;
  color: var(--accent);
  margin: 0.6em 0 0;
}
.fallback .value { color: var(--warn); }
.error .value { color: var(--danger); }
.meta, .credit, .footer {
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
  overflow: auto;
}
.side strong, .footer strong { color: var(--ink); }
.credit { margin-top: 1em; }
.footer {
  border-top: 1px solid var(--line);
  padding-top: 0.7%;
  font-size: clamp(12px, 1.1vw, 36px);
}
.media {
  margin: 0;
  min-height: 0;
  border: 1px solid var(--line);
  border-radius: 12px;
  overflow: hidden;
  background: #0a1017;
  display: flex;
  align-items: center;
  justify-content: center;
}
.media img {
  display: block;
  max-width: 100%;
  max-height: 100%;
}
.media.landscape img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.media.contain img,
.media.sidebar img {
  width: 100%;
  height: 100%;
  object-fit: contain;
  background: #0a1017;
}
"""
