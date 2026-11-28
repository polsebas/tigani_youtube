# Spec: `editorial-data-storytelling` (Valor Agregado de `official-data-charts`)

## 1. Objective

Convertir `official-data-charts` de un verificador literal de cifras en un **motor de narrativa visual económica** que aclare conceptos y aporte contexto inmediato que el locutor no necesita leer en voz alta.

Ante una mención como *"la inflación subió al 2,2 % en el último mes"*, la placa 16:9 en OBS deja de repetir un número aislado y entrega automáticamente:

* **Curva de tendencia con ventana narrativa inteligente** (últimos 12–18 meses, año en curso o horizonte de gestión según la intención del tramo).
* **Callout editorial anclado al dato citado** (punto resaltado + badge de variación vs. período anterior, ej. `▲ +0,3 p.p. vs. mes ant.`).
* **Bandas de gestión e hitos macroeconómicos** sombreados suavemente en el fondo del gráfico SVG (ej. inicio de mandato) para dar perspectiva histórica de un vistazo.
* **Barra de 3 micro-métricas derivadas en Python** (período anterior, acumulado del año YTD e interanual YoY, o pico/piso del período si la serie no alcanza 12 meses).

## 2. Tech Stack

* **Lenguaje y gestión:** Python 3.14, `uv` (paquete `tigani_broadcast`, **cero dependencias externas nuevas**).
* **Contratos y validación:** Pydantic v2 (`ConfigDict(extra="forbid")`).
* **Clasificación de intención narrativa:** Agno 3.2.1 (extendiendo el `output_schema` del resolver existente, `temperature=0.0`, sin llamadas extra al LLM por mención).
* **Cálculo y render:** Python puro (`metrics.py`, `regimes.py`, `render.py`) generando SVG + HTML 16:9 100 % offline.
* **Calidad:** `pytest`, `pytest-cov` (mínimo 85 %, 100 % offline), `ruff`.

## 3. Commands

```bash
# Ejecutar módulo de datos con narrativa visual enriquecida
TIGANI_LLM_PROVIDER=ollama \
TIGANI_LLM_MODEL=qwen3:8b \
TIGANI_OLLAMA_THINK=false \
uv run python -m tigani_broadcast.official_data_charts \
  --input out/run_kP_G1sAStQE/work/chapters.json \
  --publish-date 2025-12-11 \
  --output out/run_kP_G1sAStQE/work/charts.json \
  --charts-dir out/run_kP_G1sAStQE/work/charts \
  --markdown out/run_kP_G1sAStQE/work/charts.md

# Re-ejecutar dentro del pipeline completo (solo charts + package)
rm -f out/run_kP_G1sAStQE/work/charts.json && \
uv run tigani-broadcast run \
  --transcript data/kP_G1sAStQE.txt \
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
  SPEC-editorial-data-storytelling.md          → Esta especificación
src/tigani_broadcast/official_data_charts/
  models.py                                    → Extensión con `NarrativeMode`, `EditorialKpi`, `ChartNarrative`, `RegimeBand`
  regimes.py                                   → Catálogo determinista de gestiones e hitos macroeconómicos (recortados a `publish_date`)
  metrics.py                                   → Cálculo determinista de KPIs derivados (delta p.p./%, YTD compuesto o simple, YoY, min/max) y selección de punto callout
  resolver.py                                  → Clasificación de `narrative_mode` + ventana de descarga ampliada según modo
  render.py                                    → Nuevo layout SVG/HTML 16:9 con bandas de gestión, callout destacado, badge de variación y barra de KPIs
tests/official_data_charts/
  test_regimes.py                              → Recorte por ventana y `publish_date`, solapamiento de bandas
  test_metrics.py                              → Tests de cálculo compuesto (IPC), variaciones de nivel, series cortas y bordes
  test_render.py                               → Verificación de elementos SVG/HTML (bandas, callout, KPIs, escape HTML, cero CDN)
  test_resolver.py                             → Selección de ventana narrativa y compatibilidad con `charts.json`

```

## 5. Editorial Narrative & Calculation Rules

### Modos narrativos (`NarrativeMode`)

1. **`trend_with_callout` (default):** ventana de **18 meses** (para series mensuales) o **12 meses** (para series diarias) hasta `publish_date`, con el último punto (o el período citado) destacado en un callout con flecha de dirección (`▲`/`▼`/`=`). Ideal para *"la inflación subió al 2,2 %"*.
2. **`ytd_focus`:** ventana desde el **1° de enero del año de `publish_date**` (incluyendo el cierre de diciembre previo como línea base para mostrar la trayectoria del año). Ideal para *"en lo que va del año..."*.
3. **`term_comparison`:** ventana ampliada (**hasta 48 meses** si la serie lo soporta) con **bandas de gestión** sombreadas en el fondo del SVG para contrastar etapas de gobierno. Ideal para *"comparado con el gobierno anterior..."*.

### Cálculo determinista de micro-métricas (`metrics.py`)

Según el tipo de unidad de la serie en el catálogo (`series_kind`: `"monthly_pct_change"` vs. `"level_or_rate"`):

* **Series de variación mensual porcentual (ej. IPC mensual):**
* **Período anterior:** valor del punto `t-1` y delta en **puntos porcentuales (`p.p.`)** (`v[t] - v[t-1]`).
* **Acumulado del año (YTD):** composición geométrica exacta $\left(\prod (1 + r_i/100) - 1\right) \times 100$ sobre los meses del año calendario de la fecha ancla.
* **Interanual (YoY):** composición geométrica de los últimos 12 meses (solo si existen los 12 puntos consecutivos; si no, omite el KPI en lugar de estimarlo).


* **Series de nivel, stock, precio o tasa (ej. Reservas brutas, Dólar, Riesgo País, EMAE, ADRs):**
* **Período anterior:** valor previo y variación porcentual (`%`) o en `p.p.` si es tasa.
* **Acumulado del año (YTD):** variación desde el último dato del año calendario anterior.
* **Interanual (YoY):** variación contra el dato de 12 meses atrás (o **Rango del período: mín / máx** si la ventana es menor a 12 meses).


* **Regla *fail-closed*:** Nunca se interpolan ni se inventan KPIs; si faltan puntos para calcular YoY o YTD, esa tarjeta se reemplaza automáticamente por un dato real presente en la serie (ej. *Máximo del período* o *Mínimo del período*).

### Bandas de gestión (`regimes.py`)

* Lista determinista de períodos presidenciales argentinos recientes (ej. `2015-12-10`–`2019-12-09`, `2019-12-10`–`2023-12-09`, `2023-12-10`–presente) con etiquetas sobrias y neutras (solo apellido/período, sin adjetivos).
* Se aplican únicamente a series de alcance **Argentina** (`scope == "argentina"`), recortadas a la intersección `[window_start, min(window_end, publish_date)]`, y solo se renderizan si la ventana visible abarca al menos dos gestiones o un cambio de gestión dentro del gráfico.

## 6. Code Style

Mismo estilo del repositorio (Python 3.14, Pydantic v2 `extra="forbid"`, funciones puras deterministas, `ruff`):

```python
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

NarrativeMode = Literal["trend_with_callout", "ytd_focus", "term_comparison"]
DeltaDirection = Literal["up", "down", "flat"]


class EditorialKpi(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=40)
    formatted_value: str = Field(min_length=1, max_length=40)
    detail: str | None = Field(default=None, max_length=60)


class ChartNarrative(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: NarrativeMode
    headline_badge: str | None = Field(default=None, max_length=60)
    delta_direction: DeltaDirection | None = None
    anchor_date: str = Field(min_length=1)
    anchor_label: str = Field(min_length=1, max_length=60)
    kpis: list[EditorialKpi] = Field(default_factory=list, max_length=3)

```

## 7. Testing Strategy

* **Framework:** `pytest` + `pytest-cov` (100 % offline, cero llamadas de red y cero consumo de LLM).
* **Niveles de test:**
* `test_regimes.py`: intersección exacta de bandas de gestión con ventanas cortas/largas, recorte estricto a `publish_date` y exclusión para series internacionales/ADRs.
* `test_metrics.py`: verificación numérica exacta de inflación compuesta YTD/YoY, delta en `p.p.`, variaciones `%` para series de nivel, fallback limpio a `min`/`max` cuando la serie tiene pocos puntos, y cero divisiones por cero.
* `test_resolver.py`: mapeo de `NarrativeMode` a ventanas de descarga (`18m`, `ytd`, `48m`) y generación de `ChartNarrative` en `ChartArtifact`.
* `test_render.py`: presencia de callout destacado, badge de dirección, tarjetas de KPIs y bandas de gestión en el SVG/HTML 16:9, escape HTML estricto y 0 dependencias externas.


* **Cobertura mínima:** `>= 85 %` (objetivo > 92 % total).

## 8. Boundaries

* **Always:** Ejecutar `pytest` con cobertura y `ruff` antes de cerrar cada corte; calcular todos los KPIs en Python determinista; recortar series e hitos a `<= publish_date`; mantener compatibilidad con `broadcast-package-builder` y `pipeline-orchestrator`.
* **Ask first:** Agregar dependencias externas a `pyproject.toml`; cambiar las credenciales/proveedores de datos; modificar el contrato de salida de `transcript-chapterizer` o `broadcast-package-builder`.
* **Never:** Permitir que el LLM calcule o escriba valores numéricos en los KPIs; mostrar datos o hitos posteriores a `publish_date`; romper el render offline 16:9 sin CDNs; etiquetar gestiones con juicios de valor políticos.

## 9. Success Criteria

1. Ante una mención de inflación mensual (ej. *"la inflación subió al 2,2 %"*), `official-data-charts` genera una placa SVG 16:9 con la tendencia de 18 meses, el punto ancla resaltado, el badge de variación en `p.p.` vs. mes anterior y 3 KPIs verificados al pie (mes anterior, acumulado YTD e interanual YoY).
2. Cuando el texto compara gestiones (`term_comparison`), el gráfico amplía la ventana y renderiza bandas de gestión sobrias y neutras en el fondo del SVG, estrictamente acotadas a `<= publish_date`.
3. Todas las placas existentes (`quoted_only`, `fetch_error`, `deck.html`, `social_post.txt`) siguen funcionando sin regresiones.
4. Toda la suite (incluyendo los nuevos tests de `regimes`, `metrics`, `resolver` y `render`) corre 100 % offline con cobertura `>= 85 %` y `ruff` en verde.

## 10. Open Questions

1. **Ventana por defecto en `trend_with_callout`:** ¿Te parece bien **18 meses** para series mensuales (como IPC o EMAE) y **12 meses** para series diarias (como dólar o reservas), o preferís una ventana más corta (12 meses para todo)?
2. **Etiquetas de las bandas de gestión en `regimes.py`:** ¿Preferís etiquetas puramente institucionales por período (`2019–2023`, `2023–act.`) o con apellido presidencial corto (`Fernández (2019–23)`, `Milei (2023–act.)`)?
