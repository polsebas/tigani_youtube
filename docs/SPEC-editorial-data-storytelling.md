# Spec: `editorial-data-storytelling` (Valor Agregado de `official-data-charts`)

Estado: **Corte 2 cerrado** (`resolver.py` + `render.py` con `NarrativeMode`, ventanas ampliadas y layout SVG/HTML narrativo).

## 1. Objective

Convertir `official-data-charts` de un verificador literal de cifras en un **motor de narrativa visual económica** que aclare conceptos y aporte contexto inmediato que el locutor no necesita leer en voz alta.

El núcleo de valor agregado se activa **por defecto en todo `verified_series`**: cada serie verificada produce un `ChartNarrative` determinista (badge de variación + hasta 3 KPIs + bandas de gestión cuando corresponde).

Ante una mención como *"la inflación subió al 2,2 % en el último mes"*, la placa 16:9 en OBS deja de repetir un número aislado y entrega automáticamente:

* **Curva de tendencia con ventana narrativa inteligente** (12 meses en `trend_with_callout`, YTD o hasta 48 meses según modo).
* **Callout editorial anclado al dato citado** (punto resaltado + badge de variación vs. período anterior, ej. `▲ +0,3 p.p. vs. mes ant.`).
* **Bandas de gestión** sombreadas suavemente en el fondo del gráfico SVG (apellido + período) para dar perspectiva histórica de un vistazo.
* **Barra de hasta 3 micro-métricas derivadas en Python** (período anterior, acumulado del año YTD e interanual 12m, o rango/máx del período si la serie no alcanza).

## 2. Tech Stack

* **Lenguaje y gestión:** Python 3.14, `uv` (paquete `tigani_broadcast`, **cero dependencias externas nuevas**).
* **Contratos y validación:** Pydantic v2 (`ConfigDict(extra="forbid")`).
* **Clasificación de intención narrativa (Corte 2):** Agno 3.2.1 (extendiendo el `output_schema` del resolver existente, `temperature=0.0`, sin llamadas extra al LLM por mención).
* **Cálculo:** Python puro en `metrics.py` + `regimes.py` (**cero números generados por LLM**).
* **Render (Corte 2):** SVG + HTML 16:9 100 % offline en `render.py`.
* **Calidad:** `pytest`, `pytest-cov` (mínimo 85 %, 100 % offline), `ruff`.

## 3. Commands

```bash
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
  models.py                                    → Extensión aditiva: NarrativeMode, EditorialKpi, ChartNarrative, RegimeBand
  regimes.py                                   → Catálogo determinista de gestiones (recortadas a publish_date)
  metrics.py                                   → KPIs derivados + build_chart_narrative (Corte 1)
  resolver.py                                  → Clasificación de narrative_mode + ventana (Corte 2)
  render.py                                    → Layout SVG/HTML con bandas, callout y KPIs (Corte 2)
tests/official_data_charts/
  test_regimes.py                              → Intersección, recorte a publish_date, scope
  test_metrics.py                              → Composición IPC, nivel, series cortas, anti-redundancia
```

## 5. Decisiones cerradas (Corte 1)

### Modos narrativos (`NarrativeMode`)

```text
NarrativeMode = Literal["trend_with_callout", "ytd_focus", "term_comparison"]
```

1. **`trend_with_callout` (default):** ventana visible de **12 meses** hasta `publish_date` (fetch de **13 meses** para disponer de base exacta del mes t−12). Muestra **ambos KPIs** al pie — `Acum. año (YTD)` e `Interanual (12m)` — con regla anti-redundancia en enero/diciembre.
2. **`ytd_focus`:** ventana desde el 1° de enero del año de `publish_date` (incluyendo el cierre de diciembre previo como línea base).
3. **`term_comparison`:** ventana ampliada **hasta 48 meses** con bandas de gestión. Solo series de alcance Argentina.

### Anti-redundancia enero / diciembre

* **Enero:** no emitir `Acum. año (YTD)` si el año calendario del ancla tiene un solo mes (duplicaría el dato mensual). Completar con `Máx. del período` o `Rango del período` (mín – máx reales de la ventana).
* **Diciembre:** si YTD e interanual 12m coinciden (año completo = últimos 12 meses), no duplicar: conservar uno y reemplazar el otro por `Rango del período`.

### Bandas de gestión (`regimes.py`)

Etiquetas con apellido corto (neutras, sin adjetivos):

| Label | Inicio | Fin |
|---|---|---|
| `Macri (2015–19)` | `2015-12-10` | `2019-12-09` |
| `Fernández (2019–23)` | `2019-12-10` | `2023-12-09` |
| `Milei (2023–act.)` | `2023-12-10` | abierto |

* Solo si `scope == "argentina"`.
* Techo efectivo: `min(window_end, publish_date)`. Nunca fechas `> publish_date`.
* Se emiten si la ventana visible cruza **≥ 2 gestiones** (`include_single=False` por defecto).

### Cálculo determinista de KPIs (`metrics.py`)

* **Series `is_monthly_pct_change` (ej. IPC mensual) o tasas `%`:** delta en **p.p.** (`v[t] − v[t−1]`). YTD / interanual 12m por **composición geométrica** exacta `(∏(1 + rᵢ/100) − 1) × 100`.
* **Series de nivel / stock / precio:** delta en **%** si `v[t−1] ≠ 0`. YTD vs. último dato del año calendario anterior. Interanual vs. punto ~12 meses atrás (tolerancia 330–395 días).
* Fail-closed: sin interpolación, sin división por cero; KPIs faltantes se rellenan con `Máx. del período` / `Rango del período`.

### Contratos aditivos

`ChartArtifact.narrative: ChartNarrative | None = None` — 100 % compatible hacia atrás con tests y `broadcast-package-builder`.

## 6. Code Style

Mismo estilo del repositorio (Python 3.14, Pydantic v2 `extra="forbid"`, funciones puras deterministas, `ruff`):

```python
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

NarrativeMode = Literal["trend_with_callout", "ytd_focus", "term_comparison"]
DeltaDirection = Literal["up", "down", "flat"]
```

## 7. Testing Strategy

* **Framework:** `pytest` + `pytest-cov` (100 % offline).
* **Corte 1:** `test_regimes.py` + ampliación de `test_metrics.py` (IPC compuesto, anti-redundancia, nivel, serie corta, cero `ZeroDivisionError`).
* **Corte 2:** `test_resolver.py` + `test_render.py` (ventanas, SVG/HTML, escape, cero CDN).
* **Cobertura mínima:** `>= 85 %` (objetivo > 92 % total).

## 8. Boundaries

* **Always:** Ejecutar `pytest` con cobertura y `ruff` antes de cerrar cada corte; calcular todos los KPIs en Python determinista; recortar series e hitos a `<= publish_date`; mantener compatibilidad con `broadcast-package-builder` y `pipeline-orchestrator`.
* **Ask first:** Agregar dependencias externas a `pyproject.toml`; cambiar las credenciales/proveedores de datos; modificar el contrato de salida de `transcript-chapterizer` o `broadcast-package-builder`.
* **Never:** Permitir que el LLM calcule o escriba valores numéricos en los KPIs; mostrar datos o hitos posteriores a `publish_date`; romper el render offline 16:9 sin CDNs; etiquetar gestiones con juicios de valor políticos; modificar `resolver.py` / `render.py` en Corte 1.

## 9. Success Criteria (Corte 1)

1. Existen los contratos `NarrativeMode`, `DeltaDirection`, `RegimeBand`, `EditorialKpi`, `ChartNarrative` y el campo opcional `ChartArtifact.narrative`.
2. `resolve_regime_bands` recorta a `publish_date`, excluye `scope != "argentina"` y emite etiquetas con apellido.
3. `build_chart_narrative` produce badge + KPIs deterministas (IPC p.p./YTD/YoY geométricos, nivel `%`, anti-redundancia ene/dic, series cortas sin inventar).
4. Suite offline verde con cobertura `>= 85 %` y `ruff` OK; ningún test previo roto.

## 10. Decisiones cerradas (antes Open Questions)

1. **Ventana `trend_with_callout`:** **12 meses** visibles (fetch 13 meses para base exacta), mostrando ambos KPIs YTD + interanual 12m con anti-redundancia ene/dic.
2. **Etiquetas de gestiones:** apellido corto — `Macri (2015–19)`, `Fernández (2019–23)`, `Milei (2023–act.)`.
