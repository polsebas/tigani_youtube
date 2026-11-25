# Spec: `pipeline-orchestrator`

Estado: **Corte 1 cerrado** (contratos + `run_pipeline` + packaging editable). CLI raíz y `__main__.py` quedan para el Corte 2.

## 1. Objective

Unificar los 4 módulos del pipeline (`transcript-chapterizer`, `official-data-charts`, `visual-assets-fetcher` y `broadcast-package-builder`) detrás de un único comando CLI determinista que, a partir de una transcripción, una fecha de publicación y un título, genere todo el paquete de producción para OBS Studio (16:9) y el kit de publicación para YouTube y redes sociales.

## 2. Tech Stack

* **Lenguaje y gestión:** Python 3.14, `uv` (paquete `tigani_broadcast` instalable en editable, **cero dependencias externas nuevas**).
* **Validación y contratos:** Pydantic v2 (`ConfigDict(extra="forbid")`), reutilizando `ChapterizedTranscript`, `ChartsPackage`, `VisualAssetsPackage` y `BroadcastPackageManifest`.
* **CLI:** `argparse` con subcomando `run` (Corte 2) + entrypoint `tigani-broadcast`.
* **Calidad:** `pytest`, `pytest-cov` (mínimo 85 %, 100 % offline), `ruff`.

## 3. Commands

```bash
# Corrida completa de punta a punta (Corte 2: sin PYTHONPATH)
TIGANI_LLM_PROVIDER=ollama \
TIGANI_LLM_MODEL=qwen3:8b \
TIGANI_OLLAMA_THINK=false \
uv run tigani-broadcast run \
  --transcript data/kP_G1sAStQE.vtt \
  --publish-date 2025-12-11 \
  --video-title "Inflación, reservas y deuda: qué muestran los datos" \
  --video-url "https://youtu.be/kP_G1sAStQE" \
  --output-dir out/run_kP_G1sAStQE

# Equivalente vía módulo (Corte 2)
uv run python -m tigani_broadcast run \
  --transcript data/kP_G1sAStQE.vtt \
  --publish-date 2025-12-11 \
  --video-title "Inflación, reservas y deuda: qué muestran los datos" \
  --output-dir out/run_kP_G1sAStQE

# Reanudar sin repetir etapas 1–3 ya válidas (la etapa package siempre se regenera)
uv run tigani-broadcast run \
  --transcript data/kP_G1sAStQE.vtt \
  --publish-date 2025-12-11 \
  --video-title "Inflación, reservas y deuda: qué muestran los datos" \
  --output-dir out/run_kP_G1sAStQE \
  --resume

# Tests y cobertura (100 % offline)
uv run pytest --cov=src --cov-report=term-missing

# Linter y formato
uv run ruff check src tests && uv run ruff format --check src tests

```

## 4. Project Structure

```text
docs/
  SPEC-pipeline-orchestrator.md          → Esta especificación
src/tigani_broadcast/
  __main__.py                            → Entrypoint raíz `python -m tigani_broadcast` (Corte 2)
  pipeline/
    __init__.py                          → API pública del orquestador
    models.py                            → `PipelineConfig`, `StageResult`, `PipelineReport`
    runner.py                            → `run_pipeline(...)` con etapas inyectables y `--resume`
    cli.py                               → CLI raíz (`run`) con `argparse` (Corte 2)
tests/pipeline/
  __init__.py
  test_models.py                         → Contratos y validadores de configuración y reporte
  test_runner.py                         → Ejecución secuencial, `--resume`, fail-fast y flags
  test_cli.py                            → CLI E2E offline (Corte 2)

```

### Estructura del workspace generado (`--output-dir`)

```text
out/run_<video_id>/
  pipeline_report.json                   → Estado, tiempos y rutas de las 4 etapas
  work/
    chapters.json                        → Salida Módulo 1
    chapters.md
    charts.json                          → Salida Módulo 2
    charts.md
    charts/                              → Placas HTML 16:9 de datos/gráficos
    assets.json                          → Salida Módulo 3
    assets.md
    assets/                              → Placas HTML 16:9 + images/
  package/                               → Salida Módulo 4 (carpeta portable para OBS)
    deck.html
    package.json
    rundown.md
    youtube_description.txt
    social_post.txt
    slides/

```

## 5. Decisiones cerradas (v0)

| Tema | Decisión |
|---|---|
| Ejecución | En proceso vía `run_cli` de cada módulo. Sin duplicar lógica de negocio. Sin `subprocess`. |
| Workspace | `work/` (intermedios), `package/` (OBS portable), `pipeline_report.json` en la raíz de `--output-dir`. |
| Empaquetado | Editable en `pyproject.toml` con entrypoint `tigani-broadcast` → `tigani_broadcast.pipeline.cli:main` (CLI en Corte 2). |
| `--resume` | Saltea etapas 1–3 si JSON + archivos referenciados existen y validan. **Etapa 4 (`package`) siempre se regenera** (< 1 s). |
| Fallos | Fail-fast entre etapas; deja `pipeline_report.json` con `succeeded=False` y el motivo. |

### Orden estricto de etapas

1. `chapterizer` (`transcript-chapterizer`): lee `--transcript` → escribe `work/chapters.json` y `work/chapters.md`.
2. `charts` (`official-data-charts`): lee `work/chapters.json` + `--publish-date` → escribe `work/charts.json`, `work/charts.md` y `work/charts/`.
3. `visuals` (`visual-assets-fetcher`): lee `work/chapters.json` → escribe `work/assets.json`, `work/assets.md` y `work/assets/`.
4. `package` (`broadcast-package-builder`): lee los 3 JSON de `work/` → escribe el paquete autocontenido en `package/`.

### Flags de control y pass-through

* `--resume`: valida con Pydantic si `work/chapters.json`, `work/charts.json` o `work/assets.json` ya existen y son válidos (y en `charts`/`assets` verifica también que los HTML/imágenes referenciados existan en disco) antes de saltear cada etapa; si el archivo está ausente o corrupto, re-ejecuta la etapa. **Nunca saltea `package`.**
* `--no-llm-visuals`: pasa `--no-llm` al Módulo 3.
* `--portrait-layout {sidebar,contain}`: pasa el layout vertical al Módulo 3 (default `sidebar`).
* `--no-chapter-covers` y `--include-errors`: pasan al Módulo 4.
* `--cache-dir`: pasa subcarpetas `charts` y `visuals` a Módulos 2 y 3.

### Validación de reanudación

* `chapterizer`: `work/chapters.json` existe y valida con `ChapterizedTranscript`.
* `charts`: `work/charts.json` existe, valida con `ChartsPackage`, `publish_date == config.publish_date`, y todo `item.html_path` existe en disco.
* `visuals`: `work/assets.json` existe, valida con `VisualAssetsPackage`, `portrait_layout == config.portrait_layout`, todo `item.html_path` existe, y todo `verified_asset.local_image_path` existe.
* `package`: nunca se saltea.

### Salida en consola (Corte 2)

Imprime un resumen breve por etapa (`[1/4] chapterizer: ok (12.4s)` o `skipped (resume)`) y al final la ruta a `package/deck.html`, `package/youtube_description.txt` y `package/social_post.txt`.

## 6. Code Style

Mismo estilo de los 4 módulos existentes (Python 3.14, Pydantic v2 `extra="forbid"`, runners inyectables, `ruff`):

```python
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

StageName = Literal["chapterizer", "charts", "visuals", "package"]
StageStatus = Literal["executed", "skipped", "failed"]


class StageResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: StageName
    status: StageStatus
    duration_seconds: float = Field(ge=0.0)
    output_path: str | None = None
    error_message: str | None = None
```

## 7. Testing Strategy

* **Framework:** `pytest` + `pytest-cov` (100 % offline, cero llamadas de red y cero consumo de LLM).
* **Niveles de test:**
  * `test_models.py`: validación *fail-closed* de `PipelineConfig`, `StageResult` y `PipelineReport`.
  * `test_runner.py`: ejecución completa en orden con runners fake, `--resume` salteando 1–3, re-ejecución ante JSON corrupto o placa faltante, fail-fast escribiendo `pipeline_report.json`, y propagación exacta de flags.
  * `test_cli.py` (Corte 2): parseo `run`, validación de fechas/transcript, códigos `0`/`1`.
* **Cobertura mínima:** `>= 85 %` (objetivo > 95 % en `pipeline/`).

## 8. Boundaries

* **Always:** Ejecutar `pytest` con cobertura y `ruff` antes de cerrar cada corte; validar *fail-closed* los JSON existentes antes de saltearlos con `--resume`; registrar tiempos y estado en `pipeline_report.json`.
* **Ask first:** Agregar dependencias nuevas; modificar contratos internos de los Módulos 1–4.
* **Never:** Duplicar lógica de negocio de los Módulos 1–4 dentro de `pipeline/`; usar `subprocess` cuando se puede invocar en proceso; silenciar fallos fatales de una etapa continuando con datos incompletos.

## 9. Success Criteria

1. Un único comando `uv run tigani-broadcast run ...` (o `python -m tigani_broadcast run ...`) encadena los 4 módulos y produce `work/`, `package/deck.html`, `package/youtube_description.txt`, `package/social_post.txt` y `pipeline_report.json`.
2. Con `--resume`, una segunda corrida sobre el mismo `--output-dir` saltea las etapas 1–3 ya válidas y reconstruye `package/` en menos de 1 segundo.
3. Si falla una etapa intermedia, el proceso corta inmediatamente con `exit 1` y deja registrado en `pipeline_report.json` qué etapa falló y por qué.
4. Toda la suite corre 100 % offline con cobertura `>= 85 %` y `ruff check` + `ruff format --check` en verde.
5. `uv run python -c "import tigani_broadcast"` funciona sin `PYTHONPATH=src`.

## 10. Open Questions

Ninguna. Decisiones de empaquetado editable y de `--resume` (siempre regenerar `package/`) cerradas en la sección 5.
