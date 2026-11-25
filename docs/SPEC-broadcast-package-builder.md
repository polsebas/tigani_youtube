# Spec: `broadcast-package-builder`

Estado: **v0 cerrado** (contratos, ensamblado portable, `deck.html` OBS, portadas de capítulo, kit de publicación y CLI). 100 % determinista: sin LLM ni red. Cierra el pipeline PoC.

## 1. Objective

Ensamblar los resultados validados de `transcript-chapterizer` (`chapters.json`), `official-data-charts` (`charts.json`) y `visual-assets-fetcher` (`assets.json`) en un **paquete de producción autocontenido para OBS Studio (16:9)** y **kit de publicación para YouTube y redes sociales**:

* Valida integridad referencial *fail-closed* (que existan todos los archivos HTML e imágenes locales referenciados antes de empaquetar).
* Construye una línea de tiempo única y ordenada de placas (ante colisión en el mismo cue: `chapter_cover` → `chart` → `visual`).
* Empaqueta las placas individuales, las imágenes locales y un navegador único `deck.html` 16:9 offline listo para usar como **Browser Source** en OBS Studio.
* Genera el manifiesto maestro `package.json`, la escaleta operativa `rundown.md`, el texto listo para pegar en YouTube (`youtube_description.txt` con capítulos, fuentes de datos y créditos/licencias CC obligatorios) y un borrador promocional para redes sociales (`social_post.txt`).

## 2. Tech Stack

* **Lenguaje y gestión:** Python 3.14, `uv` (paquete `tigani_broadcast`, **cero dependencias externas nuevas** — solo biblioteca estándar + Pydantic v2 ya instalado).
* **Validación y contratos:** Pydantic v2 (`ConfigDict(extra="forbid")`), reutilizando `ChapterizedTranscript`, `ChartsPackage` y `VisualAssetsPackage`.
* **Player 16:9 (`deck.html`):** HTML5 + CSS + JavaScript vanilla inline (100 % offline, cero CDN, sin build step).
* **Calidad:** `pytest`, `pytest-cov` (mínimo 85 %, 100 % offline), `ruff`.
* **Determinismo:** el módulo es **100 % determinista** (sin LLM ni red). Solo lee JSON/archivos locales y escribe el paquete portable.

## 3. Commands

```bash
# Construir el paquete final autocontenido para OBS y publicación
PYTHONPATH=src uv run python -m tigani_broadcast.broadcast_package_builder \
  --chapters out/kP_G1sAStQE.v3.chapters.json \
  --charts out/kP_G1sAStQE.charts.json \
  --assets out/kP_G1sAStQE.assets.json \
  --output-dir out/package_kP_G1sAStQE \
  --video-title "Inflación, reservas y deuda: qué muestran los datos" \
  --video-url "https://youtu.be/kP_G1sAStQE"

# Sin portadas de capítulo
PYTHONPATH=src uv run python -m tigani_broadcast.broadcast_package_builder \
  --chapters out/kP_G1sAStQE.v3.chapters.json \
  --charts out/kP_G1sAStQE.charts.json \
  --assets out/kP_G1sAStQE.assets.json \
  --output-dir out/package_kP_G1sAStQE \
  --video-title "Inflación, reservas y deuda: qué muestran los datos" \
  --no-chapter-covers

# Incluir placas fetch_error en la rotación de deck.html
PYTHONPATH=src uv run python -m tigani_broadcast.broadcast_package_builder \
  --chapters out/kP_G1sAStQE.v3.chapters.json \
  --charts out/kP_G1sAStQE.charts.json \
  --assets out/kP_G1sAStQE.assets.json \
  --output-dir out/package_kP_G1sAStQE \
  --video-title "Inflación, reservas y deuda: qué muestran los datos" \
  --include-errors

# Tests y cobertura (100 % offline)
uv run pytest --cov=src --cov-report=term-missing

# Linter y formato
uv run ruff check src tests && uv run ruff format --check src tests

```

## 4. Project Structure

```text
docs/
  SPEC-broadcast-package-builder.md      → Esta especificación
src/tigani_broadcast/broadcast_package_builder/
  __init__.py                            → API pública del módulo
  __main__.py                            → Entrypoint `python -m`
  models.py                              → Contratos Pydantic (timeline, slides, créditos, manifiesto)
  assemble.py                            → Validación de entradas, ordenamiento y copia portable
  deck.py                                → Generación de `deck.html` 16:9 y placas separadoras
  publishing.py                          → `youtube_description.txt`, `social_post.txt`, `rundown.md`
  cli.py                                 → CLI con `argparse`
tests/broadcast_package_builder/         → Tests 100 % offline sobre paquetes sintéticos

```

### Estructura del directorio de salida (`--output-dir`)

```text
out/package_<video_id>/
  deck.html                              → Player 16:9 único para OBS Browser Source
  package.json                           → Manifiesto maestro validado con toda la línea de tiempo
  rundown.md                             → Escaleta de operación por capítulo y timestamp
  youtube_description.txt                → Descripción lista para YouTube (capítulos + fuentes + licencias CC)
  social_post.txt                        → Texto promocional listo para redes sociales
  slides/
    charts/                              → Placas HTML 16:9 copiadas desde official-data-charts
    visuals/                             → Placas HTML 16:9 copiadas desde visual-assets-fetcher
    visuals/images/                      → Imágenes locales verificadas (rutas relativas intactas)
    chapters/                            → Placas separadoras 16:9 de inicio de capítulo (opcionales)

```

## 5. Decisiones cerradas (v0)

| Tema | Decisión |
|---|---|
| Determinismo | **100 % determinista**. Sin LLM ni red. |
| Operación en OBS (v0) | `deck.html` 16:9 offline + placas individuales en carpeta autocontenida. **Sin** OBS Scene Collection en v0. |
| Colisión en mismo `(chapter_index, cue_index)` | Orden estricto: `chapter_cover` (0) → `chart` (1) → `visual` (2), luego `original_index`. |
| Portadas de capítulo | **Activas por defecto** al inicio de cada capítulo (`cue_index = start_cue_index`). Se desactivan con `--no-chapter-covers`. |
| Placas `fetch_error` | **Excluidas por defecto** de la rotación de `deck.html` / `slides`. Quedan registradas en `package.json` (`excluded_errors`) y en `rundown.md`. Incluibles con `--include-errors`. |
| Kit de publicación | `youtube_description.txt` (capítulos desde `00:00`, fuentes de datos, créditos/licencias CC) + `social_post.txt` (post promocional determinista). |

### Reglas de ensamblado y validación (*fail-closed*)

* Verifica que todos los `chapter_index` presentes en `charts.json` y `assets.json` existan en `chapters.json`.
* Verifica que toda `html_path` declarada en `charts.json` / `assets.json` exista en disco, y que toda `local_image_path` de un `verified_asset` exista en disco antes de copiar. Si falta un archivo requerido, aborta con error explícito (`PackageValidationError`).
* **Política de ordenamiento:** para cada slide se ordena por `(chapter_index, cue_index, kind_priority, original_index)` con `kind_priority = {"chapter_cover": 0, "chart": 1, "visual": 2}`:
  1. `chapter_cover` (al inicio de cada capítulo, `cue_index = chapter.start_cue_index`, si `include_chapter_covers` está activo; activo por defecto).
  2. `chart` (datos/gráficos de `official-data-charts`).
  3. `visual` (imágenes/placas de `visual-assets-fetcher`).
* **Filtro de placas de error:** por defecto las placas en estado `fetch_error` se excluyen de `slides` / rotación al aire y se registran en `excluded_errors` (también visibles en `rundown.md` con advertencia). Con `--include-errors` entran a la línea de tiempo.

### Reglas del Player OBS (`deck.html`)

* Viewport 16:9 limpio (`1920×1080`), fondo negro `#000`, `<iframe>` a pantalla completa cargando la placa relativa activa (`slides/...`).
* Controles por teclado: `ArrowRight` / `Space` (siguiente), `ArrowLeft` (anterior), `Home` / `End` (inicio/fin), `H` (mostrar/ocultar barra HUD del operador con número de slide, timestamp, capítulo y título).
* El HUD inicia **oculto** o discretamente minimizable para que en OBS Browser Source salga la señal limpia al aire, con parámetro opcional `?hud=1` en la URL para modo operador/ensayo.

### Reglas de publicación (`youtube_description.txt` y `social_post.txt`)

* **`youtube_description.txt`:**
  1. Resumen breve del episodio (derivado de los capítulos) + fecha de publicación (`charts.publish_date`).
  2. **Capítulos para YouTube** en formato exacto `MM:SS Título` (o `HH:MM:SS` si supera 1 h), comenzando en `00:00` en el primer capítulo para que YouTube active automáticamente la barra de capítulos.
  3. **Fuentes de datos oficiales y de mercado:** lista deduplicada de `source_attribution` + `series_id` de todos los `verified_series`.
  4. **Créditos y licencias de imágenes:** lista deduplicada de `author`, `license_name`, `provider` y `source_page_url` de todos los `verified_asset` (cumplimiento estricto de `CC BY` / `CC BY-SA`).

* **`social_post.txt`:**
  * Post promocional estructurado y determinista en español pensado para X / LinkedIn / Comunidad de YouTube:
  * Gancho con título del video y temas principales (títulos de capítulos).
  * 2 a 4 viñetas con los ejes y datos destacados presentes en el video (priorizando `verified_series` con su último dato oficial y luego citas clave).
  * Cierre con llamado a ver el video (`--video-url` o `[LINK_VIDEO]`) y hashtags sobrios de economía/actualidad.

## 6. Code Style

Mismo estilo de los módulos 1, 2 y 3 (Python 3.14, Pydantic v2 `extra="forbid"`, `ruff`, funciones puras y rutas `Path`):

```python
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

SlideKind = Literal["chapter_cover", "chart", "visual"]


class PackageSlide(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slide_index: int = Field(ge=0)
    chapter_index: int = Field(ge=0)
    chapter_title: str = Field(min_length=1)
    cue_index: int = Field(ge=0)
    timestamp: str = Field(min_length=1)
    kind: SlideKind
    status: str = Field(min_length=1)
    title: str = Field(min_length=1)
    relative_html_path: str = Field(min_length=1)
    source_ref: str | None = None
```

## 7. Testing Strategy

* **Framework:** `pytest` + `pytest-cov` (100 % offline, usando `tmp_path`).
* **Niveles de test:**
  * `test_models.py`: contratos de `PackageSlide`, `BroadcastPackageManifest` y validadores *fail-closed*.
  * `test_assemble.py`: ordenamiento determinista (colisión en mismo cue → `chapter_cover` → `chart` → `visual`), copia portable de HTMLs e imágenes preservando rutas relativas, exclusión por defecto de `fetch_error` vs `--include-errors`, `include_chapter_covers=False`, deduplicación de créditos y rechazo *fail-closed* si falta un HTML/imagen o si un `chapter_index` no existe.
  * `test_deck.py`: `deck.html` 100 % offline (sin CDN), lista ordenada de slides en JSON embebido, escape seguro y portadas de capítulo.
  * `test_publishing.py`: formato de capítulos YouTube, deduplicación de fuentes/créditos, `social_post.txt` y `rundown.md`.
  * `test_cli.py`: ejecución E2E sobre fixtures de los 3 módulos.
* **Cobertura mínima:** `>= 85 %` (objetivo > 90 %).

## 8. Boundaries

* **Always:** Ejecutar `pytest` con cobertura y `ruff` antes de cerrar cada corte; copiar todos los activos al directorio destino para portabilidad real en OBS; incluir todos los créditos CC en `youtube_description.txt`; validar existencia física de archivos *fail-closed*.
* **Ask first:** Agregar nuevas dependencias a `pyproject.toml`; agregar llamadas a LLM en este módulo; cambiar los esquemas de `chapters.json`, `charts.json` o `assets.json`.
* **Never:** Inventar cifras, fuentes o créditos que no provengan de los 3 JSON de entrada; dejar rutas absolutas locales dentro de `deck.html` o de las placas copiadas; incrustar scripts/fuentes desde CDN en `deck.html`; tocar código de los módulos 1, 2 o 3.

## 9. Success Criteria

1. Dados `kP_G1sAStQE.v3.chapters.json`, `kP_G1sAStQE.charts.json` y `kP_G1sAStQE.assets.json`, genera un directorio autocontenido con `deck.html`, `package.json`, `rundown.md`, `youtube_description.txt`, `social_post.txt` y todas las placas + imágenes copiadas.
2. En el cue `14` (`00:01:50`, colisión entre dato y visual), `package.json` y `deck.html` ubican primero la placa de `chart` y a continuación la placa de `visual` (si hay `chapter_cover` en el mismo cue, va antes que ambos).
3. `youtube_description.txt` comienza sus timestamps en `00:00`, cita la fuente del IPC verificado y lista los créditos/licencias de las imágenes verificadas; `social_post.txt` produce un post promocional limpio sin datos inventados.
4. Toda la suite corre 100 % offline con cobertura `>= 85 %` y `ruff check` + `ruff format --check` en verde.

## 10. Open Questions

Ninguna. Decisiones de v0 cerradas en la sección 5 (portadas activas por defecto con `--no-chapter-covers`; sin Scene Collection OBS en v0). El módulo y el pipeline PoC están implementados.
