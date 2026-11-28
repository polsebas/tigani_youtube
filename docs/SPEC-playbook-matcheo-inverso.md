# Spec: `playbook-matcheo-inverso` (Playbook v1 de Gráficos Explicativos)

## 1. Objective

Incorporar **matcheo inverso por capítulo** en `official-data-charts`: en lugar de depender únicamente de que el locutor mencione un número exacto con serie oficial 1 a 1, el sistema evalúa la **tesis económica de cada capítulo** contra un **Playbook cerrado de 5 gráficos estándar** alimentados por datos oficiales (INDEC, BCRA, Datos Argentina, ArgentinaDatos) y genera placas explicativas animadas en **Apache ECharts** que aclaran el concepto central del tramo.

Por ejemplo, en el video piloto (`kP_G1sAStQE`), un tramo que dice *"productos y servicios 55 % más caros en dólares"* o *"reservas netas… 2015 vs. hoy"* deja de producir solo tarjetas textuales aisladas y dispara automáticamente gráficos oficiales de contexto (**Inflación vs. Dólar Base 100**, **Reservas BCRA con bandas de gestión** y **Riesgo País**).

## 2. Tech Stack

* **Lenguaje y empaquetado:** Python 3.14, `uv` (paquete `tigani_broadcast`, **cero dependencias externas nuevas**).
* **Contratos:** Pydantic v2 (`ConfigDict(extra="forbid")`).
* **Selección editorial:** Agno (LLM) devolviendo únicamente `playbook_id` del catálogo cerrado + `cue_index` + `rationale` breve (`temperature=0.0`), con **fallback determinista por palabras clave temáticas** si el LLM local devuelve vacío o falla el parseo.
* **Cálculo y render:** Python determinista (`playbook.py`, `metrics.py`, `render.py`) + **Apache ECharts** offline (`echarts.min.js`).
* **Calidad:** `pytest`, `pytest-cov` (`>= 85 %`, 100 % offline), `ruff`.

## 3. Commands

```bash
# Re-ejecutar charts + package sobre el piloto con matcheo inverso
rm -f out/run_kP_G1sAStQE/work/charts.json && \
TIGANI_LLM_PROVIDER=ollama \
TIGANI_LLM_MODEL=qwen3:8b \
TIGANI_OLLAMA_THINK=false \
uv run tigani-broadcast run \
  --transcript data/kP_G1sAStQE.txt \
  --publish-date 2025-12-11 \
  --video-title "Inflación, reservas y deuda: qué muestran los datos" \
  --video-url "https://youtu.be/kP_G1sAStQE" \
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
  SPEC-playbook-matcheo-inverso.md                → Esta especificación
src/tigani_broadcast/official_data_charts/
  playbook.py                                     → Catálogo cerrado Playbook v1 (5 specs), alineación dual Base 100 y matcher determinista de respaldo
  models.py                                       → Extensión aditiva (`PlaybookId`, `SecondarySeriesData`, `ChartArtifact.playbook_id`, `ChartArtifact.secondary_series`)
  resolver.py                                     → Etapa de matcheo inverso por capítulo (LLM + fallback determinista, tope 2/capítulo, deduplicación contra menciones directas)
  render.py                                       → Soporte ECharts para doble línea Base 100 (`dual_base100`) y barras divergentes con eje cero (`bar_diverging`)
tests/official_data_charts/
  test_playbook.py                                → Cálculo exacto Base 100, alineación de fechas, triggers temáticos, recorte a `publish_date`
  test_resolver.py                                → Matcheo inverso por capítulo, no-duplicación con series ya resueltas, tope de 2 por capítulo
  test_render.py                                  → Render ECharts para `dual_base100` y `bar_diverging` (offline, responsivo, escape HTML)

```

## 5. Playbook v1 — Definición de los 5 gráficos estándar

| `playbook_id` | Tipo ECharts | Series del catálogo | Ventana por defecto | Nota editorial / KPIs |
| --- | --- | --- | --- | --- |
| `ipc_trend` | `single_line` | `ar_indec_ipc_mensual` | 12 meses (fetch 13m) | Badge `p.p.`, mes ant., YTD, interanual. |
| `ipc_vs_dolar_base100` | `dual_base100` | `ar_indec_ipc_mensual` (compuesto a índice) + `ar_bcra_dolar_mayorista` | 12 meses (fetch 13m, base `t0 = 100`) | *"Índices re-indexados a Base 100 en el mes inicial de la ventana"*. KPIs: IPC acum., dólar oficial acum. y brecha real. |
| `reservas_bcra_regimes` | `single_line` | `ar_bcra_reservas_brutas` | 48 meses (`term_comparison`) | *"Reservas internacionales brutas BCRA (incluye encajes y swap)"*. Bandas de gestión. |
| `emae_activity` | `bar_diverging` | `ar_indec_emae_mensual` | 12 meses | Barras verdes (`>= 0`) y rojas (`< 0`) sobre eje cero. |
| `riesgo_pais_trend` | `single_line` | `ar_mkt_riesgo_pais` | 12 meses | Último valor en pb, variación vs. mes ant., YTD y rango mín/máx. |

## 6. Code Style

Mismo estilo del repositorio (Python 3.14, Pydantic v2 `extra="forbid"`, funciones puras deterministas, `ruff`):

```python
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

PlaybookId = Literal[
    "ipc_trend",
    "ipc_vs_dolar_base100",
    "reservas_bcra_regimes",
    "emae_activity",
    "riesgo_pais_trend",
]
PlaybookChartType = Literal["single_line", "dual_base100", "bar_diverging"]


class PlaybookChartSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    playbook_id: PlaybookId
    title: str = Field(min_length=1, max_length=80)
    chart_type: PlaybookChartType
    series_keys: tuple[str, ...] = Field(min_length=1, max_length=2)
    default_window_months: int = Field(ge=6, le=60)
    editorial_note: str | None = Field(default=None, max_length=140)

```

## 7. Testing Strategy

* **Framework:** `pytest` + `pytest-cov` (100 % offline, cero llamadas de red y cero consumo de LLM).
* **Niveles de test:**
* `test_playbook.py`: re-indexación exacta Base 100 (IPC compuesto mensual + dólar oficial diario agregado a mensual), alineación por mes común, manejo de series sin solapamiento, recorte a `<= publish_date`, y triggers temáticos deterministas.
* `test_resolver.py`: inserción de gráficos de playbook por capítulo, respeto al tope de 2 por capítulo, no-duplicación si `ar_indec_ipc_mensual` ya fue graficado por mención directa, y degradación limpia si falla el fetch de una serie.
* `test_render.py`: render ECharts válido para `dual_base100` (dos series + leyenda + eje Y Base 100) y `bar_diverging` (barras con color por signo sobre eje cero), 100 % responsivo y sin CDNs.


* **Cobertura mínima:** `>= 85 %` (mantener > 92 % total).

## 8. Boundaries

* **Always:** Ejecutar `pytest` con cobertura y `ruff` antes de cerrar cada corte; calcular Base 100 y KPIs en Python determinista; recortar todas las series a `<= publish_date`; mantener 100 % de compatibilidad con `broadcast-package-builder` y `deck.html`.
* **Ask first:** Agregar dependencias externas a `pyproject.toml`; agregar proveedores de datos nuevos fuera de los existentes; modificar el contrato de `transcript-chapterizer`.
* **Never:** Inventar puntos para alinear dos series de distinta frecuencia; confundir reservas brutas con netas (siempre aclarar en `editorial_note`); duplicar en un mismo capítulo una serie que ya salió como `verified_series`; romper el modo offline.

## 9. Success Criteria

1. Sobre el video piloto (`kP_G1sAStQE`), el matcheo inverso detecta automáticamente contexto para **Inflación vs. Dólar (Base 100)**, **Reservas BCRA con bandas de gestión** y **Riesgo País**, además del **IPC mensual**, generando placas animadas y responsivas en Apache ECharts dentro de `deck.html`.
2. La re-indexación a Base 100 en `ipc_vs_dolar_base100` es matemáticamente exacta, 100 % determinista y acotada a `<= publish_date`.
3. Ningún capítulo supera el tope de 2 gráficos de playbook ni duplica series ya resueltas por mención directa.
4. Toda la suite corre 100 % offline con cobertura `>= 85 %` y `ruff` en verde.

## 10. Decisiones cerradas (Corte 1)

1. **Playbook v1 cerrado** de exactamente 5 gráficos: `ipc_trend`, `ipc_vs_dolar_base100`, `reservas_bcra_regimes`, `emae_activity`, `riesgo_pais_trend`. Las claves de serie son las del catálogo vigente (`ar_bcra_dolar_mayorista`, `ar_indec_emae_mensual`, `ar_mkt_riesgo_pais`), no alias ilustrativos.
2. **Convivencia con `quoted_only`:** se mantienen ambas placas. Primero la cita textual y después el gráfico oficial del playbook.
3. **Ventana de `ipc_vs_dolar_base100`:** 12 meses visibles. El fetch es de 13 meses para construir la base `t0 = 100` (el mes inicial no se aplica como tasa; ancla el índice).
4. **Tope editorial:** máximo 2 gráficos de playbook por capítulo. No se duplica una serie ya resuelta como `verified_series` en el mismo capítulo (se excluye el playbook cuya serie primaria ya está en ese conjunto).
5. **Cálculo:** 100 % determinista en Python. Cero números generados por el LLM. Toda observación se recorta a `<= publish_date` antes de alinear, re-indexar o armar KPIs.
