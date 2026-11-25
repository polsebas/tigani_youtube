# Spec: `visual-assets-fetcher`

Estado: **v0 cerrado** (dedupe, licencias fail-closed, Wikimedia + Openverse, planner Agno/`--no-llm`, render 16:9, CLI). Consume `chapters.json` y produce `assets.json` + placas/imágenes para `broadcast-package-builder`.

## 1. Objective

Transformar los `visual_subjects` del `chapters.json` generado por `transcript-chapterizer` en activos visuales verificables, con licencia comercial segura para YouTube y listos para **OBS Studio (16:9)**:

* Deduplica sujetos repetidos dentro del mismo capítulo por `(chapter_index, normalized_subject_label)`.
* Busca y descarga imágenes reales únicamente desde fuentes sin API key obligatoria (**Wikimedia Commons** y **Openverse**), filtrando *fail-closed* cualquier licencia incompatible (NC, ND, *fair use* o desconocida).
* Genera un manifiesto `assets.json` (contrato consumible por `broadcast-package-builder`), un resumen `assets.md`, las imágenes descargadas localmente y placas **HTML 16:9** autocontenidas con atribución obligatoria de autor y licencia.
* Cuando no existe una imagen segura o disponible, genera una placa textual contextual (`fallback_card`) o registra `fetch_error` sin romper el resto del paquete.

## 2. Tech Stack

* **Lenguaje y gestión:** Python 3.14, `uv` (paquete `tigani_broadcast`, sin dependencias nuevas obligatorias sobre `httpx`, `pydantic` v2 y `agno==3.2.1` ya instalados).
* **Validación y contratos:** Pydantic v2 (`ConfigDict(extra="forbid")`).
* **Planificación de búsqueda (opcional/inyectable):** Agno 3.2.1 (`Agent`, `output_schema`, `temperature=0.0`, sin SDKs crudos) + planificador determinista puro (`--no-llm` / fallback offline).
* **Transporte HTTP y caché:** `httpx` con transporte inyectable (`httpx.MockTransport` en tests) y caché local en disco para búsquedas.
* **Placas 16:9:** HTML5/CSS autocontenido 100 % offline (sin CDNs ni scripts externos) referenciando las imágenes descargadas localmente por ruta relativa. Fotos verticales (`height > width`) se aceptan con encuadre parametrizado (`portrait_layout: "sidebar" | "contain"`, default `"sidebar"`).
* **Calidad:** `pytest`, `pytest-cov` (mínimo 85 %, 100 % offline), `ruff`.

## 3. Commands

```bash
# Ejecutar CLI del módulo (con normalización de queries vía Agno)
PYTHONPATH=src \
TIGANI_LLM_PROVIDER=ollama \
TIGANI_LLM_MODEL=qwen3:8b \
TIGANI_OLLAMA_THINK=false \
uv run python -m tigani_broadcast.visual_assets_fetcher \
  --input out/kP_G1sAStQE.v3.chapters.json \
  --output out/kP_G1sAStQE.assets.json \
  --assets-dir out/assets_kP_G1sAStQE \
  --markdown out/kP_G1sAStQE.assets.md

# Ejecutar en modo 100 % determinista (sin LLM, usando subject_label directo)
PYTHONPATH=src uv run python -m tigani_broadcast.visual_assets_fetcher \
  --input out/kP_G1sAStQE.v3.chapters.json \
  --output out/kP_G1sAStQE.assets.json \
  --assets-dir out/assets_kP_G1sAStQE \
  --no-llm

# Tests y cobertura (100 % offline, sin red ni tokens)
uv run pytest --cov=src --cov-report=term-missing

# Linter y formato
uv run ruff check src tests && uv run ruff format --check src tests

```

## 4. Project Structure

```text
docs/
  SPEC-visual-assets-fetcher.md          → Esta especificación
src/tigani_broadcast/visual_assets_fetcher/
  __init__.py                            → API pública del módulo
  __main__.py                            → Entrypoint `python -m`
  models.py                              → Contratos Pydantic (dedup, query draft, licencias, activos, salida)
  dedupe.py                              → Normalización y deduplicación determinista por capítulo
  licenses.py                            → Lista blanca de licencias seguras para YouTube y validador fail-closed
  cache.py                               → Caché local en disco para resultados de búsqueda
  planner.py                             → Protocolo `VisualQueryPlanner` (Agno + determinista puro)
  providers/                             → Conectores HTTP deterministas
    base.py                              → Protocolo `VisualProvider`, `VisualCandidate`, errores de dominio
    wikimedia.py                         → Wikimedia Commons API (sin auth, metadatos `extmetadata` de autor/licencia)
    openverse.py                         → Openverse API (sin auth obligatoria; primaria para conceptual_illustration)
    fetcher.py                           → Orquestador de búsqueda, filtro de licencia, fallback y descarga binaria
  render.py                              → Render de `assets.json`, `assets.md` y placas HTML 16:9 para OBS
  cli.py                                 → CLI con `argparse` y dependencias inyectables
tests/visual_assets_fetcher/             → Tests 100 % offline con `httpx.MockTransport` y planners fake

```

## 5. Data Contracts, Licensing & Resolution Policy

### Decisiones cerradas

| Tema | Decisión |
|---|---|
| Fuentes | **Wikimedia Commons** (`wikimedia`) + **Openverse** (`openverse`). Sin API key obligatoria. |
| Preferencia por `asset_kind` | `event_photo` → `wikimedia`; `conceptual_illustration` → `openverse` con fallback a `wikimedia`. |
| Planificador | **Agno por defecto** (solo genera `search_query` y `preferred_provider`, nunca URLs). `--no-llm` es modo determinista opcional. |
| Fotos verticales | Aceptadas. Encuadre en placa 16:9 vía `portrait_layout: Literal["sidebar", "contain"] = "sidebar"` (barra lateral de texto o `object-fit: contain`). |
| Deduplicación | Determinista por `(chapter_index, normalized_subject_label)`: conserva la primera aparición e incrementa `occurrences_count`. Mismo texto en capítulos distintos = sujetos separados. |
| Degradación | Por sujeto a `fallback_card` (sin licencia válida) o `fetch_error` (red/HTTP), sin abortar el resto del video. |

### Política de licencias (*fail-closed*)

* **Permitidas (código canónico):** `PD` (`Public domain`, `PD-*`, `pdm`), `CC0`, `CC-BY` (`CC BY 2.0/3.0/4.0`, Openverse `by`), `CC-BY-SA` (`CC BY-SA 2.0/3.0/4.0`, Openverse `by-sa`).
* **Rechazadas explícitamente:** cualquier licencia con restricción no comercial (`NC` / `noncommercial`), sin obras derivadas (`ND` / `noderivs`), *fair use*, `all rights reserved`, `copyrighted`, vacía o no reconocida.
* **Validación de descarga:** solo formatos de imagen seguros (`image/jpeg`, `image/png`, `image/webp`), descartando SVGs potencialmente inseguros o respuestas vacías/HTML, y con límite de tamaño máximo configurable (ej. 10 MB).

### Flujo de resolución por `VisualSubject`

1. **Deduplicación (`dedupe.py`):** agrupa por `(chapter_index, normalize_subject_label(subject_label))` conservando la primera aparición y registrando `occurrences_count`.
2. **Planificación de búsqueda (`planner.py`):** produce `VisualQueryPlan(search_query, preferred_provider, rationale)` sin generar URLs ni inventar licencias. Por defecto: `event_photo` → `wikimedia`, `conceptual_illustration` → `openverse` (con fallback a `wikimedia`).
3. **Búsqueda + filtro + descarga (`providers/fetcher.py`):** consulta el proveedor preferido, filtra candidatos por `licenses.py` y dimensiones mínimas (ej. ancho `>= 640 px`), descarga el mejor candidato en `assets_dir/images/` y registra toda la atribución. Retratos verticales se aceptan y se renderizan según `portrait_layout`.
4. **Estados finales (`AssetStatus`):**
   * `verified_asset`: imagen descargada localmente + autor + licencia verificada + placa HTML 16:9 con crédito visible.
   * `fallback_card`: sin resultados con licencia válida → placa tipográfica contextual 16:9, sin imagen inventada.
   * `fetch_error`: error HTTP/timeout/red en el proveedor → degrada solo ese sujeto sin abortar el video y genera placa de aviso para el operador.

## 6. Code Style

Mismo estilo de `transcript-chapterizer` y `official-data-charts` (Python 3.14, Pydantic v2 `extra="forbid"`, `Protocol` para inyección, `ruff`):

```python
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

AssetStatus = Literal["verified_asset", "fallback_card", "fetch_error"]
VisualProviderId = Literal["wikimedia", "openverse"]
PortraitLayout = Literal["sidebar", "contain"]


class VisualAttribution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: VisualProviderId
    author: str = Field(min_length=1)
    license_name: str = Field(min_length=1)
    license_code: str = Field(min_length=1)
    license_url: str | None = None
    source_page_url: str = Field(min_length=1)
    image_url: str = Field(min_length=1)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    mime_type: str

```

## 7. Testing Strategy

* **Framework:** `pytest` + `pytest-cov` (100 % offline, cero llamadas de red y cero consumo de tokens en CI).
* **Niveles de test:**
  * Unitarios de `models`, `dedupe` (colapsa 5 repeticiones de `"gobierno"` en el mismo capítulo y preserva sujetos iguales en capítulos distintos), `licenses` (acepta CC0/PD/CC-BY/CC-BY-SA/Openverse `pdm`/`by`/`by-sa` y rechaza NC/ND/fair-use/vacía) y `cache`.
  * Unitarios de `wikimedia.py`, `openverse.py` y `fetcher.py` con `httpx.MockTransport` (payloads reales, descarga binaria, rechazo de `Content-Type` no imagen, errores 401/429/500 y fallback `openverse -> wikimedia`).
  * Unitarios de `planner.py` (modo determinista y `AgnoVisualQueryPlanner` con agente fake), `render.py` (HTML 16:9 con ruta relativa a imagen local, escape HTML, crédito visible y `portrait_layout`) y `cli.py` E2E sobre fixture equivalente a `kP_G1sAStQE.v3.chapters.json`.
* **Cobertura mínima:** `>= 85 %` (objetivo > 90 %).

## 8. Boundaries

* **Always:** Ejecutar `pytest` con cobertura y `ruff` antes de cerrar cada corte; incluir `User-Agent` descriptivo en Wikimedia Commons y Openverse; imprimir crédito de autor y licencia en toda placa `verified_asset`; validar licencias *fail-closed*.
* **Ask first:** Agregar nuevas dependencias a `pyproject.toml`; habilitar generación de imágenes con IA o proveedores pagos; cambiar el contrato de `chapters.json` o `assets.json`.
* **Never:** Descargar o incrustar imágenes sin licencia verificada en la lista blanca; dejar que el LLM devuelva URLs directas; hardcodear API keys; abortar todo el video por un timeout en una imagen puntual; tocar código de `transcript-chapterizer`, `official-data-charts` o `broadcast-package-builder`.

## 9. Success Criteria

1. Dado `kP_G1sAStQE.v3.chapters.json`, deduplica las 5 entradas repetidas de `"gobierno"` del capítulo 2 en 1 única solicitud visual y conserva el resto de los sujetos únicos con su primer timestamp.
2. Toda entrada `verified_asset` en `assets.json` tiene imagen descargada localmente, `author`, `license_code` aprobado por `licenses.py`, `source_page_url` y placa HTML 16:9 offline con el crédito visible.
3. Ninguna imagen con licencia `NC`, `ND`, *fair use* o desconocida puede pasar a `verified_asset`; si no hay candidato seguro, degrada limpiamente a `fallback_card`.
4. Toda la suite corre 100 % offline con cobertura `>= 85 %` y `ruff check` + `ruff format --check` en verde.

## 10. Open Questions

Ninguna pendiente para el alcance actual. Decisiones de fuentes (Openverse en lugar de Pexels), planificador (Agno por defecto), orientación vertical (`portrait_layout`) y degradación por sujeto quedan cerradas en esta SPEC.
