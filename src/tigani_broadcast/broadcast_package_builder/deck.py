"""Player OBS `deck.html` 16:9 y placas separadoras de capítulo."""

from __future__ import annotations

import html
import json
from pathlib import Path

from tigani_broadcast.broadcast_package_builder.models import BroadcastPackageManifest, PackageSlide
from tigani_broadcast.transcript_chapterizer.models import ChapterizedTranscript

_COVER_CSS = """
:root {
  --bg: #0f1720;
  --panel: #182230;
  --ink: #f4f7fb;
  --muted: #9db0c3;
  --accent: #3db8a8;
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
  grid-template-rows: auto 1fr auto;
  padding: 3% 4%;
  gap: 2%;
}
.banner {
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid var(--line);
  padding-bottom: 0.8%;
  font-size: clamp(14px, 1.4vw, 44px);
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--muted);
}
.banner .mark { color: var(--accent); font-weight: 700; }
.clock { font-variant-numeric: tabular-nums; }
.content {
  display: flex;
  flex-direction: column;
  justify-content: center;
  min-height: 0;
  max-width: 88%;
}
.kicker {
  color: var(--accent);
  font-size: clamp(16px, 1.6vw, 56px);
  letter-spacing: 0.08em;
  text-transform: uppercase;
  margin: 0 0 0.6em;
  font-weight: 700;
}
.headline {
  font-size: clamp(36px, 4.6vw, 144px);
  font-weight: 700;
  line-height: 1.05;
  margin: 0 0 0.45em;
}
.summary {
  color: var(--muted);
  font-size: clamp(18px, 2vw, 64px);
  line-height: 1.35;
  margin: 0;
  max-width: 42ch;
}
.footer {
  border-top: 1px solid var(--line);
  padding-top: 0.9%;
  color: var(--muted);
  font-size: clamp(12px, 1.1vw, 36px);
}
"""


def render_promo_outro_html(
    timestamp: str,
    *,
    video_title: str,
    relative_image: str | None = None,
) -> str:
    """Placa de cierre promocional, con imagen estándar o texto sobrio si no hay archivo."""
    clock = html.escape(timestamp)
    title = html.escape(video_title)
    if relative_image is not None:
        src = html.escape(relative_image, quote=True)
        body = f'<figure class="media"><img src="{src}" alt="Cierre del programa"/></figure>'
    else:
        body = (
            '<section class="card">'
            '<p class="kicker">Cierre</p>'
            "<h1>Sumate a la comunidad · Nivel 1 y Nivel 2</h1>"
            f'<p class="meta">{title}</p>'
            "</section>"
        )
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Cierre · {title}</title>
  <style>
    * {{ box-sizing: border-box; }}
    html, body {{
      margin: 0;
      width: 100%;
      height: 100%;
      min-width: 960px;
      min-height: 540px;
      overflow: auto;
      background: #000;
      color: #f4f7fb;
      font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
    }}
    .plate {{
      width: 100%;
      height: 100%;
      min-width: 960px;
      min-height: 540px;
      display: grid;
      grid-template-rows: auto minmax(0, 1fr);
      background:
        radial-gradient(1200px 500px at 10% -10%, #1d3348 0%, transparent 55%),
        linear-gradient(160deg, #101820 0%, #0c1219 100%);
    }}
    .banner {{
      display: flex;
      justify-content: space-between;
      padding: 1.2% 2%;
      color: #9db0c3;
      font-size: clamp(14px, 1.4vw, 44px);
      letter-spacing: 0.06em;
      text-transform: uppercase;
    }}
    .mark {{ color: #3db8a8; font-weight: 700; }}
    .media, .card {{
      min-height: 0;
      display: flex;
      align-items: center;
      justify-content: center;
    }}
    .media img {{
      width: 100%;
      height: 100%;
      object-fit: contain;
      background: #0a1017;
    }}
    .card {{
      flex-direction: column;
      text-align: center;
      padding: 4%;
      gap: 0.6em;
    }}
    h1 {{
      margin: 0;
      font-size: clamp(28px, 3.4vw, 96px);
      line-height: 1.1;
    }}
    .kicker {{
      margin: 0;
      color: #3db8a8;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      font-size: clamp(14px, 1.4vw, 36px);
    }}
    .meta {{ margin: 0; color: #9db0c3; font-size: clamp(16px, 1.6vw, 40px); }}
  </style>
</head>
<body>
  <article class="plate">
    <header class="banner">
      <span class="mark">Cierre</span><span class="clock">{clock}</span>
    </header>
    {body}
  </article>
</body>
</html>
"""


def render_chapter_cover_html(
    chapter_index: int,
    chapter_title: str,
    summary: str,
    timestamp: str,
    video_title: str,
) -> str:
    """Placa HTML5/CSS 16:9 de portada de capítulo, autocontenida y offline."""
    title = html.escape(chapter_title)
    summary_esc = html.escape(summary)
    clock = html.escape(timestamp)
    video = html.escape(video_title)
    number = chapter_index + 1
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Capítulo {number:02d} · {title}</title>
  <style>{_COVER_CSS}</style>
</head>
<body>
  <article class="plate">
    <header class="banner">
      <span class="mark">Capítulo {number:02d}</span>
      <span class="clock">{clock}</span>
    </header>
    <section class="content">
      <p class="kicker">{video}</p>
      <h1 class="headline">{title}</h1>
      <p class="summary">{summary_esc}</p>
    </section>
    <footer class="footer">Separador de capítulo · paquete OBS 16:9</footer>
  </article>
</body>
</html>
"""


def render_deck_html(manifest: BroadcastPackageManifest) -> str:
    """Player 16:9 único offline con iframe full-bleed, HUD y controles de teclado."""
    slides_payload = [_slide_payload(slide) for slide in manifest.slides]
    slides_json = json.dumps(slides_payload, ensure_ascii=False).replace("</", "<\\/")
    video_title = html.escape(manifest.video_title)
    empty_notice = ""
    if not manifest.slides:
        empty_notice = (
            '<div id="empty" class="empty">Sin placas en la rotación. '
            "Revisá el manifiesto del paquete.</div>"
        )
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Deck · {video_title}</title>
  <style>
    * {{ box-sizing: border-box; }}
    html, body {{
      margin: 0;
      padding: 0;
      width: 100%;
      height: 100%;
      min-width: 960px;
      min-height: 540px;
      overflow: auto;
      background: #000;
      color: #f4f7fb;
      font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
    }}
    #stage {{
      position: relative;
      width: 100vw;
      height: 100vh;
      min-width: 960px;
      min-height: 540px;
      margin: 0;
      background: #000;
      outline: none;
    }}
    #frame {{
      position: absolute;
      inset: 0;
      width: 100vw;
      height: 100vh;
      min-width: 960px;
      min-height: 540px;
      border: 0;
      background: #000;
      pointer-events: none;
    }}
    #hud {{
      position: absolute;
      left: 1.2%;
      right: 1.2%;
      bottom: 1.5%;
      display: none;
      align-items: center;
      justify-content: space-between;
      gap: 1%;
      padding: 0.7% 1.1%;
      background: rgba(8, 12, 18, 0.82);
      border: 1px solid #2b3b4d;
      border-radius: 10px;
      font-size: clamp(12px, 1.15vw, 36px);
      color: #9db0c3;
      z-index: 2;
      pointer-events: auto;
    }}
    #hud.visible {{
      display: flex;
      padding-right: 6.5em;
    }}
    #hud strong {{ color: #3db8a8; }}
    #nav {{
      position: absolute;
      right: 1.2%;
      bottom: 1.5%;
      display: flex;
      gap: 0.45em;
      z-index: 3;
      pointer-events: auto;
    }}
    #nav button, #hud button {{
      pointer-events: auto;
      cursor: pointer;
      border: 1px solid #2b3b4d;
      background: rgba(15, 23, 32, 0.9);
      color: #f4f7fb;
      border-radius: 8px;
      padding: 0.15em 0.55em;
      font: inherit;
      line-height: 1.2;
    }}
    #nav button:hover, #hud button:hover {{
      border-color: #3db8a8;
      color: #3db8a8;
    }}
    .empty {{
      position: absolute;
      inset: 0;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 4%;
      text-align: center;
      font-size: clamp(20px, 2.4vw, 72px);
      color: #9db0c3;
      z-index: 1;
      pointer-events: none;
    }}
  </style>
</head>
<body>
  <div id="stage" tabindex="0">
    <iframe id="frame" title="Placa activa" src="about:blank" tabindex="-1"></iframe>
    {empty_notice}
    <div id="nav" aria-label="Navegación">
      <button type="button" id="btn-prev" aria-label="Anterior">◀</button>
      <button type="button" id="btn-next" aria-label="Siguiente">▶</button>
    </div>
    <div id="hud" aria-live="polite">
      <span><strong id="hud-index">0/0</strong></span>
      <span id="hud-clock">--:--:--</span>
      <span id="hud-chapter">—</span>
      <span id="hud-title">—</span>
    </div>
  </div>
  <script>
    const SLIDES = {slides_json};
    const stage = document.getElementById("stage");
    const frame = document.getElementById("frame");
    const hud = document.getElementById("hud");
    const hudIndex = document.getElementById("hud-index");
    const hudClock = document.getElementById("hud-clock");
    const hudChapter = document.getElementById("hud-chapter");
    const hudTitle = document.getElementById("hud-title");
    const btnPrev = document.getElementById("btn-prev");
    const btnNext = document.getElementById("btn-next");
    let index = 0;

    // Solo recuperar foco si el iframe (u otro nodo) lo robó.
    // No llamar focus() sobre window: en OBS Interactuar saca el foco del panel CEF.
    function keepFocus() {{
      const active = document.activeElement;
      if (active === stage || active === btnPrev || active === btnNext) return;
      if (active && active.closest && active.closest("#hud")) return;
      try {{
        stage.focus({{ preventScroll: true }});
      }} catch (_err) {{
        stage.focus();
      }}
    }}

    function showHudFromQuery() {{
      const params = new URLSearchParams(window.location.search);
      if (params.get("hud") === "1") {{
        hud.classList.add("visible");
      }}
    }}

    function render() {{
      const total = SLIDES.length;
      if (total === 0) {{
        if (frame.hasAttribute("src")) frame.removeAttribute("src");
        hudIndex.textContent = "0/0";
        hudClock.textContent = "--:--:--";
        hudChapter.textContent = "Sin slides";
        hudTitle.textContent = "Rotación vacía";
        return;
      }}
      if (index < 0) index = 0;
      if (index >= total) index = total - 1;
      const slide = SLIDES[index];
      const nextSrc = slide.relative_html_path;
      if (frame.getAttribute("src") !== nextSrc) {{
        frame.src = nextSrc;
      }}
      hudIndex.textContent = (index + 1) + "/" + total;
      hudClock.textContent = slide.timestamp;
      hudChapter.textContent = "Cap " + (slide.chapter_index + 1) + " · " + slide.chapter_title;
      hudTitle.textContent = slide.title;
    }}

    function next() {{
      if (SLIDES.length === 0) return;
      index = Math.min(index + 1, SLIDES.length - 1);
      render();
    }}

    function prev() {{
      if (SLIDES.length === 0) return;
      index = Math.max(index - 1, 0);
      render();
    }}

    function onKeydown(event) {{
      // Un solo handler (document capture): window+document dispararían dos veces.
      // Evitar doble avance: Space/Enter en botón ya dispara click.
      if (event.target && event.target.closest && event.target.closest("button")) {{
        if (event.key === " " || event.key === "Enter") return;
      }}
      if (event.key === "ArrowRight" || event.key === " ") {{
        event.preventDefault();
        next();
      }} else if (event.key === "ArrowLeft") {{
        event.preventDefault();
        prev();
      }} else if (event.key === "Home") {{
        event.preventDefault();
        index = 0;
        render();
      }} else if (event.key === "End") {{
        event.preventDefault();
        index = Math.max(SLIDES.length - 1, 0);
        render();
      }} else if (event.key === "h" || event.key === "H") {{
        hud.classList.toggle("visible");
      }}
    }}

    stage.addEventListener("click", (event) => {{
      if (event.target.closest("#nav") || event.target.closest("#hud")) return;
      keepFocus();
    }});
    frame.addEventListener("load", keepFocus);
    btnPrev.addEventListener("click", (event) => {{
      event.preventDefault();
      event.stopPropagation();
      prev();
      keepFocus();
    }});
    btnNext.addEventListener("click", (event) => {{
      event.preventDefault();
      event.stopPropagation();
      next();
      keepFocus();
    }});

    // Capture: llega aunque el foco esté en #stage (OBS Interactuar / CEF).
    document.addEventListener("keydown", onKeydown, true);

    showHudFromQuery();
    keepFocus();
    render();
  </script>
</body>
</html>
"""


def write_deck_files(
    chapters: ChapterizedTranscript,
    manifest: BroadcastPackageManifest,
    output_dir: Path,
) -> None:
    """Escribe portadas de capítulo (si aplica), `deck.html` y `package.json`."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if manifest.include_chapter_covers:
        chapters_dir = output_dir / "slides" / "chapters"
        chapters_dir.mkdir(parents=True, exist_ok=True)
        for chapter_index, chapter in enumerate(chapters.chapters):
            path = chapters_dir / f"ch{chapter_index:02d}_cover.html"
            path.write_text(
                render_chapter_cover_html(
                    chapter_index,
                    chapter.title,
                    chapter.summary,
                    chapter.start_time,
                    manifest.video_title,
                ),
                encoding="utf-8",
            )

    (output_dir / "deck.html").write_text(render_deck_html(manifest), encoding="utf-8")
    (output_dir / "package.json").write_text(
        json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _slide_payload(slide: PackageSlide) -> dict[str, object]:
    return {
        "slide_index": slide.slide_index,
        "chapter_index": slide.chapter_index,
        "chapter_title": slide.chapter_title,
        "cue_index": slide.cue_index,
        "timestamp": slide.timestamp,
        "kind": slide.kind,
        "status": slide.status,
        "title": slide.title,
        "relative_html_path": slide.relative_html_path,
    }
