---
name: tigani-broadcast-pipeline
description: Arquitectura, reglas de rigor económico y flujo SDD para el pipeline de producción visual estilo noticiero (YouTube -> Agno/Pydantic -> MCP fuentes oficiales -> HTML 16:9 para OBS Studio). Usar en cualquier tarea de diseño, código o testing dentro de este repositorio.
---

# Tigani Broadcast Pipeline — Project Skill

Actúa como un Ingeniero de Software Senior especializado en Python, sistemas de agentes con **Agno**, **Pydantic v2** y pipelines de datos verificables para producción audiovisual en **OBS Studio (16:9)**.

## 1. Propósito del Sistema
Transformar videos de análisis económico de YouTube (plano fijo a cámara, alto volumen de datos y sin apoyo visual) en paquetes de producción estilo noticiero compuestos por:
- **Cuadro principal:** Video original del expositor.
- **Cuadro secundario:** Gráficos de datos oficiales verificados o recursos visuales/conceptuales.
- **Zócalo inferior:** Titular y texto explicativo en HTML responsivo adaptable a 16:9 para OBS Studio (licencia libre).

Caso piloto: videos del Dr. Pablo Tigani. El objetivo comercial posterior al PoC es ofrecer este servicio de producción para ese canal. Hasta que exista otra SPEC aprobada, el único módulo implementable es `transcript-chapterizer`.

## 2. Mapa de Módulos y Límites de Responsabilidad
Respetar estrictamente las fronteras y dirección de dependencias (sin ciclos):

| Module id | Responsabilidad | Depende de |
|---|---|---|
| `transcript-chapterizer` | Ingesta de transcripciones `[HH:MM:SS]`, segmentación en capítulos, títulos, borrador de zócalo y extracción de `hard_data`, `time_range` y `visual_subjects`. | — |
| `official-data-charts` | Consulta determinista de indicadores económicos vía MCP/APIs oficiales (BCRA, INDEC, datos abiertos), cálculo de variaciones y generación de gráficos con fuente y fecha. | `transcript-chapterizer` |
| `visual-assets-fetcher` | Obtención de imágenes de coyuntura con control de licencias/fuente o generación de ilustraciones conceptuales rotuladas. | `transcript-chapterizer` |
| `broadcast-package-builder` | Ensamblado del paquete por capítulo en 16:9: HTML responsivo (gráfico/placa/zócalo) para OBS y escaleta con timestamps. | `transcript-chapterizer`, `official-data-charts`, `visual-assets-fetcher` |

## 3. Reglas Críticas Innegociables (Guardrails)

### Rigor de datos y trazabilidad
- **Nunca inventar datos económicos:** Ningún agente puede estimar, completar de memoria o aproximar cotizaciones, inflación, reservas, tasas o series históricas. Todo dato numérico que vaya a gráfico debe provenir de una fuente oficial/MCP verificada.
- **Nunca inventar timestamps:** Todas las marcas de tiempo deben normalizarse a `HH:MM:SS` y corresponder a instantes reales de la transcripción. Validar siempre que `start_time <= end_time` y que toda mención caiga dentro del rango de su capítulo.
- **Preservar evidencia literal:** En la extracción de menciones, conservar el texto literal dicho por el expositor (`raw_value_text`) sin reinterpretar cálculos en la etapa de transcripción.
- **Separación visual explícita:** Distinguir siempre en metadata y en pantalla entre **dato oficial verificado** (con fuente y período), **imagen de archivo/prensa** (con atribución/licencia) e **ilustración conceptual generada por IA**.

### Arquitectura con Agno y Python
- **Entorno:** Python `>=3.11`, gestionado con `uv` (`pyproject.toml`, `uv.lock`).
- **Capa LLM agnóstica:** Usar siempre **Agno** (`agno.models`) inyectado por configuración/entorno. Prohibido importar SDKs de proveedores (OpenAI, Anthropic, etc.) directamente en la lógica de dominio.
- **Salidas tipadas y determinismo:** En Agno 3.2.1 la salida estructurada entra por `output_schema` en `Agent` (esa versión no tiene `response_model`). `temperature=0.0` se configura sobre el modelo inyectado de `agno.models`, no como argumento de `Agent`. El CLI de `transcript-chapterizer` lee `TIGANI_LLM_PROVIDER` y `TIGANI_LLM_MODEL` (`ollama`, `openai`, `anthropic`, `google`).
- **Separación determinista vs. probabilística:** El LLM solo interpreta texto y propone estructura; la validación de esquemas, rangos temporales, cálculos matemáticos y renderizado de archivos se ejecutan en código Python determinista.
- **Testabilidad offline:** Todo componente que invoque Agno o APIs/MCPs externos debe aceptar un adaptador/mock inyectable para ejecutar `pytest` completamente offline.

### Seguridad y calidad
- **Cero secretos en el repo:** Nunca hardcodear ni commitear API keys, tokens o archivos `.env`.
- **Validación obligatoria por tarea:** No cerrar ninguna tarea sin ejecutar:
  - `uv run pytest --cov=src --cov-report=term-missing` (cobertura objetivo `>= 85%` en módulos core)
  - `uv run ruff check src tests && uv run ruff format --check src tests`

## 4. Flujo de Trabajo (Spec-Driven Development)
1. Verificar la especificación vigente en `docs/SPEC-<module-id>.md` antes de escribir código.
2. No agregar dependencias externas ni alterar contratos JSON entre módulos sin aprobación previa.
3. Implementar en incrementos pequeños (un archivo/componente + sus tests por corte), siguiendo `tasks/plan.md` y `tasks/todo.md`.
4. Si falta información crítica de negocio o de una fuente oficial/MCP, detenerse y preguntar antes de asumir.
5. No crear paquetes, clientes, prompts ni contratos de un módulo que no tenga `docs/SPEC-<module-id>.md` aprobada. `official-data-charts`, `visual-assets-fetcher` y `broadcast-package-builder` quedan fuera del PoC actual.