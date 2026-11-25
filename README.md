# Tigani Broadcast

Pipeline en Python para pasar un análisis económico de YouTube — plano a cámara y cargado de cifras — a un **paquete de producción autocontenido** estilo noticiero para **OBS Studio 16:9**, más kit de publicación para YouTube y redes.

Caso piloto: videos del Dr. Pablo Tigani. El PoC v0 implementa los **cuatro módulos** del pipeline. Las cifras de gráfico solo salen de fuentes oficiales/de mercado verificadas; las imágenes solo con licencia segura para YouTube; los timestamps siempre vienen de la transcripción real.

## Módulos

| Módulo | Entrada | Salida | Rol |
|---|---|---|---|
| [`transcript-chapterizer`](docs/SPEC-transcript-chapterizer.md) | Transcripción `[HH:MM:SS]` | `chapters.json` / `.md` | Capítulos, zócalo, `hard_data` y `visual_subjects` |
| [`official-data-charts`](docs/SPEC-official-data-charts.md) | `chapters.json` | `charts.json` + HTML 16:9 | Series oficiales/mercado, métricas y placas de dato |
| [`visual-assets-fetcher`](docs/SPEC-visual-assets-fetcher.md) | `chapters.json` | `assets.json` + HTML/imágenes | Imágenes CC/PD (Wikimedia + Openverse) o fallback |
| [`broadcast-package-builder`](docs/SPEC-broadcast-package-builder.md) | chapters + charts + assets | `deck.html`, `package.json`, rundown y textos | Paquete OBS portable + kit de publicación |

Dirección de dependencias (sin ciclos): chapterizer → charts / visuals → package-builder.

## Requisitos

- Python `>= 3.11` (desarrollo tipado contra 3.14)
- [uv](https://docs.astral.sh/uv/)
- Un modelo accesible por Agno para chapterizer / charts / planner visual: `ollama`, `openai`, `anthropic` o `google`
- Tokens opcionales según fuente (`INDEC_API_TOKEN`, `FRED_API_KEY`, …). Nunca en el repo.

## Instalación

```bash
uv sync --group dev
```

Para Ollama hace falta el extra `ollama`. Agno 3.2.1, al importar ese wrapper, también exige el paquete `openai`:

```bash
uv sync --group dev --extra ollama
```

## Flujo completo (piloto)

```bash
export TIGANI_LLM_PROVIDER=ollama
export TIGANI_LLM_MODEL=qwen3:8b
export TIGANI_OLLAMA_THINK=false

# 1) Capítulos
PYTHONPATH=src uv run python -m tigani_broadcast.transcript_chapterizer \
  --input data/transcripcion.txt \
  --output out/video.chapters.json \
  --markdown out/video.chapters.md

# 2) Charts oficiales
PYTHONPATH=src uv run python -m tigani_broadcast.official_data_charts \
  --input out/video.chapters.json \
  --publish-date 2025-11-25 \
  --output out/video.charts.json \
  --charts-dir out/charts_video \
  --markdown out/video.charts.md

# 3) Activos visuales (sin LLM: --no-llm)
PYTHONPATH=src uv run python -m tigani_broadcast.visual_assets_fetcher \
  --input out/video.chapters.json \
  --output out/video.assets.json \
  --assets-dir out/assets_video \
  --markdown out/video.assets.md \
  --no-llm

# 4) Paquete OBS + publicación
PYTHONPATH=src uv run python -m tigani_broadcast.broadcast_package_builder \
  --chapters out/video.chapters.json \
  --charts out/video.charts.json \
  --assets out/video.assets.json \
  --output-dir out/package_video \
  --video-title "Título del episodio" \
  --video-url "https://youtu.be/VIDEO_ID"
```

En OBS Studio: Browser Source → `out/package_video/deck.html` (1920×1080). Controles: flechas / espacio, `Home`/`End`, `H` para el HUD; `?hud=1` lo muestra al iniciar.

Flags útiles del empaquetador:

- `--no-chapter-covers` — omite portadas de capítulo
- `--include-errors` — incluye placas `fetch_error` en la rotación

## Entrada del chapterizer

Archivo UTF-8, una cue por línea:

```text
[00:00:01] Buen día, bienvenidos a un nuevo análisis de la coyuntura.
[00:00:14] El índice fue del 4,2 por ciento.
```

Horas con al menos dos dígitos; minutos y segundos exactos `00`–`59`. Los timestamps no pueden retroceder. El directorio `data/` queda fuera del repo (transcripciones locales).

## Guardrails

- **No inventar cifras:** todo dato de gráfico viene de fuente verificada (BCRA, INDEC, FRED, etc.) o queda `quoted_only` / `fetch_error`.
- **No inventar timestamps:** siempre desde la cue real.
- **Licencias fail-closed:** solo `PD`, `CC0`, `CC-BY`, `CC-BY-SA` en imágenes.
- **LLM vs. determinismo:** el modelo interpreta texto; validación, métricas, render y empaquetado son Python determinista.
- **Tests 100 % offline** con dependencias inyectables / mocks.

## Pruebas

```bash
uv run pytest --cov=src --cov-report=term-missing
uv run ruff check src tests && uv run ruff format --check src tests
```

Cobertura mínima: **85 %**.

## Especificaciones

- [`docs/SPEC-transcript-chapterizer.md`](docs/SPEC-transcript-chapterizer.md)
- [`docs/SPEC-official-data-charts.md`](docs/SPEC-official-data-charts.md)
- [`docs/SPEC-visual-assets-fetcher.md`](docs/SPEC-visual-assets-fetcher.md)
- [`docs/SPEC-broadcast-package-builder.md`](docs/SPEC-broadcast-package-builder.md)
