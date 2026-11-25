# Spec: `official-data-charts`

## 1. Objective

Transformar cada `HardDataMention` del `chapters.json` generado por `transcript-chapterizer` en un artefacto periodístico verificable para el paquete de producción en OBS Studio (16:9):

* Si la mención corresponde a una serie verificable de nuestro catálogo curado, consulta la fuente oficial (o de mercado Tier 2 cuando no exista API oficial primaria), calcula métricas de resumen en Python determinista y genera un gráfico HTML 16:9 con cita explícita de fuente, identificador de serie y período.
* Si la mención es coyuntural, puntual o un indicador derivado no publicado directamente (ej. colocación puntual de un bono, monto de swap o reservas netas), la clasifica como `quoted_only` y genera una placa textual limpia de dato citado, **sin inventar ni sustituir series**.

## 2. Tech Stack

* **Lenguaje y gestión:** Python 3.14, `uv` (mismo proyecto `tigani_broadcast`).
* **Validación y contratos:** Pydantic v2.
* **Agentes:** Agno 3.2.1 (`Agent`, `output_schema`, `post_hooks`, modelos inyectables de `agno.models` con `temperature=0.0`, sin importar SDKs crudos).
* **MCP y transporte HTTP:** `mcp` (`FastMCP`) + `httpx` con caché local determinista en disco.
* **Gráficos 16:9:** HTML5/CSS con **SVG puro generado desde Python** (cero dependencias JS, 100 % determinista y offline en OBS Browser Source).
* **Calidad:** `pytest`, `pytest-cov` (mínimo 85 %, objetivo 100 % offline), `ruff`.

## 3. Commands

```bash
# Ejecutar CLI del módulo
uv run python -m tigani_broadcast.official_data_charts \
  --input out/video.chapters.json \
  --publish-date 2025-12-11 \
  --output out/video.charts.json \
  --charts-dir out/charts \
  --markdown out/video.charts.md

# Levantar servidor MCP propio (stdio)
uv run python -m tigani_broadcast.official_data_charts.mcp_server

# Tests y cobertura (100 % offline, sin red ni tokens)
uv run pytest --cov=src --cov-report=term-missing

# Linter y formato
uv run ruff check src tests && uv run ruff format --check src tests

```

## 4. Project Structure

```text
docs/
  SPEC-official-data-charts.md           → Esta especificación
src/tigani_broadcast/official_data_charts/
  __init__.py                            → API pública del módulo
  __main__.py                            → Entrypoint `python -m`
  models.py                              → Contratos Pydantic (resolución, series, métricas, salida)
  catalog.py                             → Catálogo cerrado de indicadores y tickers verificados
  cache.py                               → Caché local en disco con TTL configurable
  providers/                             → Conectores HTTP deterministas por fuente
    base.py                              → Protocolo `DataProvider` y normalización de errores
    bcra.py                              → BCRA Estadísticas Monetarias v4.0 (sin auth)
    indec.py                             → API-INDEC v1 (JWT Bearer opcional) + signos convencionales
    datos_ar.py                          → Datos Argentina Series de Tiempo (sin auth, fallback INDEC)
    argentinadatos.py                    → Tier 2: Riesgo País y dólares MEP/CCL/Blue (caché >= 3h)
    international.py                     → BCB (BR), FMI DataMapper (Global), BCE (EU), FRED (US), World Bank
    us_adrs.py                           → Tier 2: ADRs argentinos NYSE/NASDAQ + ARGT
  mcp_server.py                          → Servidor FastMCP exponiendo catálogo y consultas tipadas
  resolver.py                            → Agente Agno (`output_schema` + `post_hooks`) que mapea menciones
  guardrails.py                          → Guardrails deterministas (catálogo cerrado, rangos, anti-sustitución)
  metrics.py                             → Cálculos deterministas en Python (variaciones, min/max, último valor)
  render.py                              → Render de `charts.json`, `charts.md` y placas HTML 16:9 para OBS
  cli.py                                 → CLI con `argparse` y motor/proveedores inyectables
tests/official_data_charts/              → Tests 100 % offline con respuestas HTTP y motores mockeados

```

## 5. Data Contracts, Sources & Resolution Policy

### Niveles de fuente (`source_tier`)

1. **`official_primary`** (siempre prioridad 1):
* **AR:** `bcra` (v4.0), `indec` (`api.indec.gob.ar/v1` vía `INDEC_API_TOKEN`), `datos_ar` (fallback sin token).
* **Internacional:** `bcb` (Brasil), `imf` (DataMapper WEO), `ecb` (Eurozona), `worldbank` (Global), `fred` (EE. UU. vía `FRED_API_KEY`).


2. **`market_secondary`** (solo cuando no existe API oficial primaria; cita doble obligatoria en pantalla):
* `argentinadatos`: exclusivamente **Riesgo País** (`Fuente: Ámbito vía ArgentinaDatos`) y **dólares financieros/paralelos MEP, CCL, Blue** (`Fuente: DolarApi vía ArgentinaDatos`).
* `us_adrs`: ADRs argentinos (`GGAL`, `YPF`, `BMA`, `BBAR`, `PAM`, `TGS`, `EDN`, `CEPU`, `SUPV`, `LOMA`, `CRESY`) y `ARGT` con cita de bolsa (`NYSE`/`NASDAQ`).



### Reglas de resolución y rigor

* **Catálogo cerrado:** El agente solo propone `catalog_id` (o `null`). Python deriva `resolution_status`: `catalog_id` nulo/`""`/`none`/`null`/`quoted_only` → `quoted_only`; ID presente → `verified_series` tras validar contra `catalog.py`. Cualquier ID fuera de catálogo falla *fail-closed* en guardrail.
* **Fechas deterministas:** Si el LLM omite `start_date`/`end_date` en una serie verificable, Python completa `end_date = publish_date` (o la fecha dada) y `start_date` según frecuencia del catálogo (`daily`: 90 días, `monthly`: 365 días, `quarterly`/`annual`: 5 años). Si el rango resultante es válido pero más corto que la ventana mínima (`daily`: 30 días, `monthly`: 365 días, `quarterly`/`annual`: 5 años) —p. ej. `start_date == end_date` ante `time_reference="hoy"`—, Python expande `start_date` hacia atrás. Rangos invertidos o `end_date > publish_date` siguen fallando *fail-closed*.
* **Reintento acotado (1):** Si la salida del LLM no parsea o un guardrail rechaza el borrador, `AgnoMentionResolver` reintenta **una vez** con el motivo del error en el prompt. Si vuelve a fallar, lanza `ResolutionValidationError`.
* **Anti-sustitución en v0:** Un guardrail determinista bloquea mapear `reservas netas` a la serie de `reservas brutas` del BCRA.
* **Comparativas entre países:** Para coyuntura diaria/mensual se usan bancos centrales alineando unidad y frecuencia; para comparativas estructurales anuales (PBI, deuda/PBI) se prioriza `imf` o `worldbank` para todos los países del mismo gráfico.
* **Cero matemática del LLM:** Variaciones intermensuales/interanuales, extremos y etiquetas de eje se calculan en `metrics.py` o se leen directamente del campo publicado por INDEC (preservando signos convencionales como `*` provisorio).
* **Degradación por mención:** Si falta `INDEC_API_TOKEN`, `indec` hace fallback automático y trazable a `datos_ar`. Si falla el fetch (`ProviderError` / `MetricsCalculationError`) **o** la resolución (`ResolutionValidationError`) de una mención puntual, esa mención se degrada a `fetch_error` en `charts.json` con mensaje explícito y **sin inventar observaciones**; el resto del video sigue procesándose.

## 6. Code Style

Mismo estilo estricto de `transcript-chapterizer` (tipado completo Python 3.14, Pydantic v2 con modelos inmutables donde corresponda, `ruff`, inyección de dependencias por `Protocol`):

```python
from datetime import date
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class ChartResolutionDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resolution_status: Literal["verified_series", "quoted_only"]
    catalog_id: str | None = Field(
        default=None,
        description="ID exacto del catálogo curado; obligatorio si verified_series, None si quoted_only.",
    )
    start_date: date | None = None
    end_date: date | None = None
    rationale: str = Field(min_length=1, max_length=240)

```

## 7. Testing Strategy

* **Framework:** `pytest` + `pytest-cov` (100 % offline, cero llamadas de red y cero consumo de tokens en CI).
* **Niveles de test:**
* Unitarios de `models`, `catalog`, `metrics`, `cache` y `guardrails` (bloqueo de IDs inexistentes, bloqueo de `reservas netas -> reservas brutas`, fechas inválidas).
* Unitarios de cada proveedor con `httpx.MockTransport` sobre payloads reales capturados como fixtures (incluyendo errores HTTP 401/429/500, signos convencionales del INDEC y fallback `indec -> datos_ar`).
* Integración offline del resolver Agno + ensamblado + render HTML 16:9 usando `kP_G1sAStQE.v3.chapters.json` como fixture de prueba.


* **Cobertura mínima:** `>= 85 %` (objetivo mantener el 100 % como en Módulo 1).

## 8. Boundaries

* **Always:** Ejecutar `pytest` con cobertura y `ruff` antes de cerrar cada corte; citar fuente oficial/secundaria, período y signos provisorios en toda placa HTML; validar entradas *fail-closed*; usar variables de entorno para tokens (`INDEC_API_TOKEN`, `FRED_API_KEY`).
* **Ask first:** Agregar nuevas dependencias a `pyproject.toml`; cambiar el esquema de `chapters.json` o `charts.json`; habilitar sustitución de indicadores derivados (ej. mostrar reservas brutas como proxy de netas).
* **Never:** Inventar observaciones, interpolar datos faltantes silenciosamente o dejar que el LLM calcule variaciones; hardcodear API keys o tokens JWT; usar ArgentinaDatos para series donde existe `official_primary` directo; tocar código de `visual-assets-fetcher` o `broadcast-package-builder`.

## 9. Success Criteria

1. Dado `kP_G1sAStQE.v3.chapters.json` con `--publish-date`, el pipeline clasifica `índice de inflación (2.5%)` como `verified_series` (INDEC/BCRA) y los datos puntuales/derivados (`reservas netas`, `4600 M`, `9.26%`, `900 M`, `swap`, `55%`) como `quoted_only`, generando sus placas HTML 16:9 sin inventar ninguna serie.
2. Ningún dato de serie ni variación porcentual es calculado por el LLM; toda observación trazada en `charts.json` incluye `provider`, `source_tier`, `series_id`, `source_url` y `date_range`.
3. Todas las pruebas corren 100 % offline con cobertura `>= 85 %` (objetivo 100 %) y `ruff check` + `ruff format --check` en verde.
4. El servidor MCP propio expone herramientas tipadas consumibles por Agno y cualquier cliente MCP estándar.

## 10. Closed Decisions

1. **Render de gráficos HTML 16:9 offline:** Placas generadas con **SVG puro desde Python** (cero dependencias JS, 100 % determinista y offline en OBS Browser Source). Sin Chart.js / ECharts en v0.
2. **Política ante caída de red, error de API o fallo de resolución en una mención puntual:** Degradar solo esa mención a `fetch_error` en `charts.json` (mensaje explícito, sin inventar datos) **sin abortar** el resto del video. Incluye `ResolutionValidationError` tras el reintento acotado del resolvedor.
3. **Proveedor inicial de `us_adrs` (Corte 5):** Sin API key obligatoria, detrás de caché local y conector enchufable (p. ej. CSV/Stooq u otra fuente libre). Una API con key queda como opción futura, no como requisito de v0.
4. **Esquema LLM desacoplado (Corte 4.1):** El agente Agno emite `_LLMResolutionPayload` (`catalog_id`, fechas, `rationale`); Python deriva `ChartResolutionDraft`, completa rangos faltantes y aplica guardrails. Un reintento máximo ante rechazo.

---