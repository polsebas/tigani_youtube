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
  background: #000;
  color: var(--ink);
  font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
}
.plate {
  width: 100%;
  max-width: 1920px;
  height: 1080px;
  margin: 0 auto;
  aspect-ratio: 16 / 9;
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
  font-size: clamp(14px, 1.4vw, 22px);
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
  font-size: clamp(16px, 1.6vw, 28px);
  letter-spacing: 0.08em;
  text-transform: uppercase;
  margin: 0 0 0.6em;
  font-weight: 700;
}
.headline {
  font-size: clamp(36px, 4.6vw, 72px);
  font-weight: 700;
  line-height: 1.05;
  margin: 0 0 0.45em;
}
.summary {
  color: var(--muted);
  font-size: clamp(18px, 2vw, 32px);
  line-height: 1.35;
  margin: 0;
  max-width: 42ch;
}
.footer {
  border-top: 1px solid var(--line);
  padding-top: 0.9%;
  color: var(--muted);
  font-size: clamp(12px, 1.1vw, 18px);
}
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
      background: #000;
      color: #f4f7fb;
      font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
      overflow: hidden;
    }}
    #stage {{
      position: relative;
      width: 100%;
      max-width: 1920px;
      height: 1080px;
      margin: 0 auto;
      aspect-ratio: 16 / 9;
      background: #000;
    }}
    #frame {{
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      border: 0;
      background: #000;
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
      font-size: clamp(12px, 1.15vw, 18px);
      color: #9db0c3;
      z-index: 2;
    }}
    #hud.visible {{ display: flex; }}
    #hud strong {{ color: #3db8a8; }}
    .empty {{
      position: absolute;
      inset: 0;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 4%;
      text-align: center;
      font-size: clamp(20px, 2.4vw, 36px);
      color: #9db0c3;
      z-index: 1;
    }}
  </style>
</head>
<body>
  <div id="stage">
    <iframe id="frame" title="Placa activa" src="about:blank"></iframe>
    {empty_notice}
    <div id="hud" aria-live="polite">
      <span><strong id="hud-index">0/0</strong></span>
      <span id="hud-clock">--:--:--</span>
      <span id="hud-chapter">—</span>
      <span id="hud-title">—</span>
    </div>
  </div>
  <script>
    const SLIDES = {slides_json};
    const frame = document.getElementById("frame");
    const hud = document.getElementById("hud");
    const hudIndex = document.getElementById("hud-index");
    const hudClock = document.getElementById("hud-clock");
    const hudChapter = document.getElementById("hud-chapter");
    const hudTitle = document.getElementById("hud-title");
    let index = 0;

    function showHudFromQuery() {{
      const params = new URLSearchParams(window.location.search);
      if (params.get("hud") === "1") {{
        hud.classList.add("visible");
      }}
    }}

    function render() {{
      const total = SLIDES.length;
      if (total === 0) {{
        frame.removeAttribute("src");
        hudIndex.textContent = "0/0";
        hudClock.textContent = "--:--:--";
        hudChapter.textContent = "Sin slides";
        hudTitle.textContent = "Rotación vacía";
        return;
      }}
      if (index < 0) index = 0;
      if (index >= total) index = total - 1;
      const slide = SLIDES[index];
      frame.src = slide.relative_html_path;
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

    document.addEventListener("keydown", (event) => {{
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
    }});

    showHudFromQuery();
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
