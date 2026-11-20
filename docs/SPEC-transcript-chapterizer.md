# SPEC — `transcript-chapterizer`

Estado: **v0 cerrado** (parser, capítulos, Agno inyectable, JSON/Markdown y CLI). El corte 4.1 separa la propuesta plana del agente del contrato público, sin cambiar `chapters.json`. El cliente de YouTube sigue sin implementarse. No autoriza código de `official-data-charts`, `visual-assets-fetcher` ni `broadcast-package-builder`.

Schema de salida: `transcript-chapterizer/v0`.

## 1. Objetivo

Convertir una transcripción ya segmentada en cues con timestamp en un paquete de capítulos listo para la escaleta. Cada capítulo lleva título, resumen, rango de cues, borrador de zócalo y el catálogo de:

- `hard_data`: magnitud dicha por el expositor (`raw_value_text`, `indicator_label` y, si aparece, `time_reference`)
- `visual_subjects`: sujeto o evento (`subject_label`, `context_text`) con `asset_kind` `event_photo` o `conceptual_illustration`

Este módulo **cataloga lo dicho**. No verifica cifras, no calcula variaciones y no consulta BCRA, INDEC ni ninguna otra fuente.

## 2. Fuera de alcance

- Descargar el video o elegir una librería cliente de YouTube.
- Corregir, traducir o resumir la transcripción más allá del título y del borrador de zócalo.
- Resolver expresiones relativas («el año pasado», «el mes anterior») a un rango calendario.
- Asignar un código de serie oficial (`serie_id`, IPC, tipo de cambio, reservas, tasa).
- Parsear `raw_value_text` a `float` o a una unidad normalizada.
- Generar gráficos, placas, HTML de OBS o imágenes.
- Inventar timestamps, cues o cifras que no estén en la entrada.

## 3. Decisiones de ingesta y cobertura

Confirmadas para `v0`:

1. El núcleo opera sobre `cues`. El adaptador concreto lee un archivo UTF-8 con una cue por línea en la forma `[HH:MM:SS] texto`.
2. El cliente de YouTube es solo un `Protocol` (`TranscriptSource`). No se implementa en `v0` y no se agrega una librería para bajar subtítulos.
3. Los capítulos son una partición ordenada, contigua y sin solapes del 100 % de las cues. Ninguna cue queda afuera ni se repite. La contigüidad se valida por índice de cue, no por el reloj: entre el timestamp final de un capítulo y el inicial del siguiente puede haber un salto de segundos, como en los subtítulos de YouTube. Ese salto no se rellena con timestamps inventados.
4. Un tramo de intro u outro puede ir en su propio capítulo con `hard_data=[]` y `visual_subjects=[]`.

Siguen en el contrato, sin pedido de cambio:

5. Cada `timestamp` de un capítulo o una mención tiene que ser exactamente el de su cue.
6. No hay tope de caracteres del zócalo en `v0`.
7. Una corrida procesa una sola transcripción.

## 4. Entrada

### 4.1 Archivo de transcripción

- Codificación UTF-8. Si hay BOM al inicio del archivo, se descarta.
- Saltos de línea LF o CRLF.
- Una cue por línea, con corchetes obligatorios: `[HH:MM:SS] texto`. Sin corchetes la línea es inválida.
- Horas de uno o más dígitos. Minutos y segundos de exactamente dos dígitos, en rango `00..59`.
- Se rechaza `MM:SS`, milisegundos, marcas SRT (`-->`) y cualquier línea que no sea cue ni esté vacía.
- Las líneas vacías se ignoran. Una línea no reconocida aborta el archivo entero.
- El texto de la cue es el resto de la línea, sin el timestamp y sin espacios de separación inmediatos. No se colapsan espacios internos. El texto no puede quedar vacío.
- Los timestamps de la lista tienen que ser no decrecientes. Puede haber dos cues con el mismo timestamp. El orden de lectura es el orden de índice.

Forma canónica guardada: `HH:MM:SS` con horas de dos dígitos como mínimo (`00:00:03`, `1:02:03` se guarda `01:02:03`). Si las horas superan 99, se conservan todos los dígitos.

### 4.2 Modelo de cue

| Campo | Tipo | Regla |
|---|---|---|
| `cue_index` | `int` | `>= 0`, único, secuencia `0..n-1` asignada por el parser |
| `timestamp` | `str` | Canónico `HH:MM:SS`, copiado de la entrada |
| `text` | `str` | Texto literal de la cue |

`source_id` lo aporta el llamador (id de video o nombre de archivo). El módulo no lo deduce del contenido.

## 5. Contrato de capítulos aprobado en el corte 2

Todos los modelos usan `extra="forbid"`, `strict=True` y `frozen=True`. Las cues no viajan dentro de `ChapterizedTranscript`: el validador las recibe aparte. Este paquete no es dato oficial.

```json
{
  "chapters": [
    {
      "start_cue_index": 0,
      "end_cue_index": 0,
      "start_time": "00:00:01",
      "end_time": "00:00:01",
      "title": "Intro",
      "summary": "Apertura del programa.",
      "suggested_lower_third": "Arranca el análisis.",
      "hard_data": [],
      "visual_subjects": []
    },
    {
      "start_cue_index": 1,
      "end_cue_index": 2,
      "start_time": "00:00:14",
      "end_time": "00:00:21",
      "title": "La inflación de marzo",
      "summary": "El expositor cita el índice y al Banco Central.",
      "suggested_lower_third": "El índice fue del 4,2 por ciento.",
      "hard_data": [
        {
          "cue_index": 1,
          "timestamp": "00:00:14",
          "indicator_label": "inflación",
          "raw_value_text": "4,2 por ciento",
          "time_reference": "marzo"
        }
      ],
      "visual_subjects": [
        {
          "cue_index": 2,
          "timestamp": "00:00:21",
          "subject_label": "Banco Central",
          "asset_kind": "event_photo",
          "context_text": "publicó el dato"
        }
      ]
    }
  ]
}
```

El JSON es un ejemplo de forma. No es una serie ni un dato oficial. `asset_kind` también puede ser `conceptual_illustration`.

### 5.1 `ChapterizedTranscript`

| Campo | Tipo | Regla |
|---|---|---|
| `chapters` | lista | Al menos un capítulo |

### 5.2 `Chapter`

| Campo | Tipo | Regla |
|---|---|---|
| `start_cue_index` / `end_cue_index` | `int >= 0` | `start_cue_index <= end_cue_index` |
| `start_time` / `end_time` | `str` | Canónico `HH:MM:SS`. El validador exige el timestamp de esas cues |
| `title` / `summary` / `suggested_lower_third` | `str` | Texto del capítulo y borrador de zócalo |
| `hard_data` | lista | Default `[]`. Un intro u outro puede ir vacío |
| `visual_subjects` | lista | Default `[]`. Un intro u outro puede ir vacío |

### 5.3 Menciones

`HardDataMention`: `cue_index` (`>= 0`), `timestamp`, `indicator_label`, `raw_value_text`, `time_reference: str | None = None`. `indicator_label` y `raw_value_text` tienen que seguir teniendo contenido después de `strip()`. `time_reference` no se resuelve a una fecha.

`VisualSubjectMention`: `cue_index`, `timestamp`, `subject_label`, `context_text` y `asset_kind` (`event_photo` o `conceptual_illustration`). `subject_label` y `context_text` tienen que seguir teniendo contenido después de `strip()`.

## 6. Agente

El agente no escribe `chapters.json`. Su `output_schema` es `DraftChapterizedTranscript`, una propuesta interna sin timestamps y sin menciones anidadas en los capítulos:

| Modelo | Campos |
|---|---|
| `DraftChapter` | `start_cue_index`, `end_cue_index`, `title`, `summary`, `suggested_lower_third` |
| `DraftHardDataMention` | `cue_index`, `indicator_label`, `raw_value_text`, `time_reference: str \| None = None` |
| `DraftVisualSubjectMention` | `cue_index`, `subject_label`, `asset_kind`, `context_text` |
| `DraftChapterizedTranscript` | `chapters` (al menos uno), `hard_data` (default `[]`), `visual_subjects` (default `[]`) |

Esos modelos usan `extra="forbid"`, `strict=True` y `frozen=True`. `asset_kind` sigue siendo `event_photo` o `conceptual_illustration`. `indicator_label`, `raw_value_text`, `subject_label` y `context_text` tienen que tener contenido después de `strip()`. Esta propuesta no se serializa como salida del módulo. Las instrucciones le piden al modelo rangos de `cue_index` y dos listas planas referenciadas solo por `cue_index`: no copia timestamps y no anida menciones.

`AgnoChapterizer.chapterize` pide ese borrador, lo pasa por `assemble_chapterized_transcript` y devuelve el `ChapterizedTranscript` público de la sección 5. `chapterize_transcript(cues, engine)` rechaza una lista vacía, llama al `ChapterizerEngine` y después corre `validate_chapterized_transcript`. Un motor inyectado puede devolver el contrato público ya armado; el validador lo revisa igual. Si `run(...).content` no es un `DraftChapterizedTranscript`, falla cerrado con `ChapterizerOutputError`.

En Agno 3.2.1 la salida estructurada entra por `output_schema` en `Agent`. Esa versión no tiene `response_model`. `temperature=0.0` se configura sobre el modelo inyectado de `agno.models`, porque `Agent` no recibe ese argumento. El código no importa SDKs crudos de proveedores.

`build_agno_model_from_env()` lee `TIGANI_LLM_PROVIDER` y `TIGANI_LLM_MODEL`. Los wrappers admitidos son `ollama` (`Ollama`), `openai` (`OpenAIChat`), `anthropic` (`Claude`) y `google` (`Gemini`). En Ollama la temperatura va en `options`, porque ese wrapper no declara el campo `temperature`; igual queda en `0.0`. Si falta una variable, el proveedor no está en la lista o el wrapper no carga, el error es `ModelConfigError`. No se hardcodean API keys.

El extra opcional `ollama` declara los paquetes `ollama` y `openai`. Agno 3.2.1, al importar el wrapper de Ollama, carga `OllamaResponses` y ese módulo exige el paquete `openai`. El dominio no importa ese SDK. `uv sync --extra ollama` deja el entorno reproducible.

## 7. Validación determinista

`assemble_chapterized_transcript(draft, cues)` arma el contrato público antes de validar. Copia `start_time`, `end_time` y cada `timestamp` desde `cues[idx].timestamp`. Asigna cada mención al único capítulo cuyo rango contiene su `cue_index`, ordenando por `cue_index` y conservando el orden de llegada si el índice se repite. Un índice fuera de `0..len(cues)-1`, un rango invertido o una mención que no cae en un único capítulo lanza `ChapterValidationError`. No se descarta la mención. El objeto armado pasa siempre por `validate_chapterized_transcript`.

`validate_chapterized_transcript` compara el paquete con la secuencia real de cues. Si una regla falla, no hay corrección ni resultado parcial.

1. Tiene que haber al menos una cue.
2. El primer capítulo arranca en la cue `0`.
3. Cada capítulo siguiente arranca en `anterior.end_cue_index + 1`.
4. El último termina en `len(cues) - 1`.
5. Ningún índice de capítulo cae fuera de la secuencia.
6. `start_time` y `end_time` son exactamente `cues[start_cue_index].timestamp` y `cues[end_cue_index].timestamp`. Un salto de reloj entre capítulos contiguos se acepta.
7. Cada ítem de `hard_data` y `visual_subjects` tiene su `cue_index` dentro del capítulo, y su `timestamp` es exactamente el de `cues[cue_index]`.
8. Un capítulo con ambas listas vacías es válido.

No entra en este corte la exigencia de que `raw_value_text` sea un substring de la cue, ni el filtro de dígitos nuevos en el título o el zócalo.

## 8. Errores

| Situación | Error |
|---|---|
| Archivo ilegible, línea inválida, texto vacío, reloj fuera de rango o timestamps decrecientes | `TranscriptFormatError` |
| Hueco, solape, cobertura incompleta, índice fuera de `0..len(cues)-1`, rango invertido, mención que no cae en un único capítulo, reloj distinto al de la cue o mención mal ubicada | `ChapterValidationError` |

No se reintenta contra un modelo dentro de este módulo. El ensamblado determinista no vuelve a llamar al agente ni corrige un JSON anidado.

## 9. Arquitectura

v0 completo. El cliente de YouTube no está implementado.

```text
src/tigani_broadcast/transcript_chapterizer/
  source.py           # Protocol TranscriptSource; sin cliente de YouTube
  parse.py            # archivo [HH:MM:SS] -> cues
  models.py           # Cue, contrato público y propuesta plana del agente
  validate.py         # validate_chapterized_transcript
  chapterizer.py      # AgnoChapterizer, assemble_chapterized_transcript, chapterize_transcript
  render.py           # JSON indent=2 y Markdown
  cli.py              # argparse y build_agno_model_from_env
  __main__.py         # python -m tigani_broadcast.transcript_chapterizer
tests/transcript_chapterizer/
```

```text
cues = parse(entrada)
borrador = agente(cues)                 # DraftChapterizedTranscript
paquete = assemble_chapterized_transcript(borrador, cues)
render_json(paquete) / render_markdown(paquete)
```

- `ChapterizerEngine` se inyecta. Los tests no abren red ni gastan tokens.
- `chapterizer.py` importa `agno.agent` y `agno.models.base`. El CLI importa el wrapper de `agno.models` recién cuando arma el modelo.
- Queda prohibido importar el SDK de un proveedor en el módulo.
- El modelo de lenguaje se elige por configuración inyectada. No se fija vendor ni se guarda una API key en el repo.

## 10. Criterios de aceptación del corte 2

- Una partición completa, con intro y cierre sin menciones y con un salto de segundos entre capítulos, se acepta.
- Un hueco, un solape, un arranque distinto de la cue 0 o un final que no llega a la última cue se rechazan.
- Un `start_time` o `end_time` distinto al de su cue se rechaza.
- Una mención con `cue_index` fuera del capítulo, o con un timestamp que no es el de esa cue, se rechaza.
- La suite queda cubierta al menos al 85 % y pasa `ruff check` y `ruff format --check`.

## 11. Cortes de implementación

Un corte por vez, cada uno con sus tests.

1. Cue normalizada, `TranscriptSource`, parser del archivo `[HH:MM:SS] texto` y `TranscriptFormatError`. Hecho.
2. Modelos de capítulos y menciones, más `ChapterValidationError` contra las cues. Hecho. Sin Agno ni CLI.
3. `chapterizer.py` con `ChapterizerEngine`, `AgnoChapterizer` y tests offline. Hecho.
4. JSON, Markdown, fábrica por entorno y CLI. Hecho. El cliente de YouTube no se implementa ni suma dependencias hasta una aprobación aparte.
5. Corte 4.1. Propuesta plana del agente, ensamblado determinista de timestamps y menciones, y extra opcional `ollama`. Hecho. Sin reintentos y sin cambio de `chapters.json`.

## 12. Salida a disco y CLI

`render_json` escribe UTF-8 con `indent=2` y `ensure_ascii=False`. `render_markdown` arma una sección por capítulo con el rango `[start_time - end_time]`, el título, el zócalo (`suggested_lower_third`), el resumen y las menciones con su timestamp.

```text
python -m tigani_broadcast.transcript_chapterizer \
  --input transcripcion.txt \
  --output chapters.json \
  [--markdown chapters.md]
```

`main(argv, engine=None)` usa el motor inyectado y no lee el entorno. Sin motor, construye `AgnoChapterizer` desde las variables. Código `0` si escribió los archivos. Código `1` y un mensaje en stderr ante archivo ilegible, `TranscriptFormatError`, `ChapterValidationError` o `ModelConfigError`.
