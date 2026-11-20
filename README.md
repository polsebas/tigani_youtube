# Tigani Broadcast

Pipeline en Python para pasar un análisis económico de YouTube, plano a cámara y cargado de cifras, a un paquete de producción estilo noticiero para OBS Studio en 16:9.

El caso piloto son los videos del Dr. Pablo Tigani. Hoy el único módulo implementado es `transcript-chapterizer`. No genera gráficos, placas ni HTML de OBS, y no consulta BCRA, INDEC ni ninguna otra fuente oficial.

## Qué hace el chapterizer

Lee una transcripción ya cortada en cues y escribe capítulos para la escaleta. Cada capítulo trae título, resumen, rango, borrador de zócalo y el catálogo de lo dicho:

- `hard_data`: magnitud, con el texto literal y, si aparece, la referencia temporal dicha en la cue.
- `visual_subjects`: sujeto o evento, marcado como foto de archivo o ilustración conceptual.

El modelo solo propone rangos de `cue_index` y dos listas planas de menciones. Python copia cada timestamp desde la cue real y ubica la mención en el capítulo que contiene ese índice. Si la partición tiene un hueco, un solape o un índice fuera de rango, el proceso aborta y no escribe archivos. No reintenta contra el modelo.

La especificación vigente está en [`docs/SPEC-transcript-chapterizer.md`](docs/SPEC-transcript-chapterizer.md).

## Requisitos

- Python `>= 3.11`
- [uv](https://docs.astral.sh/uv/)
- Un modelo accesible por Agno: `ollama`, `openai`, `anthropic` o `google`

## Instalación

```bash
uv sync --group dev
```

Para correr con Ollama hace falta el extra `ollama`. Agno 3.2.1, al importar ese wrapper, también exige el paquete `openai`.

```bash
uv sync --group dev --extra ollama
```

Las API keys se leen del entorno. No van en el repo.

## Entrada

Un archivo UTF-8, una cue por línea:

```text
[00:00:01] Buen día, bienvenidos a un nuevo análisis de la coyuntura.
[00:00:14] El índice fue del 4,2 por ciento.
```

Horas de dos dígitos como mínimo. Minutos y segundos de exactamente dos dígitos, entre `00` y `59`. Los timestamps no pueden retroceder. El directorio `data/` queda fuera del repositorio: ahí van las transcripciones locales.

## Corrida

```bash
export TIGANI_LLM_PROVIDER=ollama
export TIGANI_LLM_MODEL=qwen3:8b

PYTHONPATH=src uv run python -m tigani_broadcast.transcript_chapterizer \
  --input transcripcion.txt \
  --output chapters.json \
  --markdown chapters.md
```

`TIGANI_LLM_MODEL` es el id del modelo en ese proveedor. `--markdown` es opcional. El proceso sale con código `0` si escribió los archivos y con código `1` si el archivo, el modelo o la validación fallan.

## Pruebas

```bash
uv run pytest --cov=src --cov-report=term-missing
uv run ruff check src tests && uv run ruff format --check src tests
```

La suite corre offline: el motor del chapterizer se inyecta y no gasta tokens. La cobertura mínima es 85 %.
