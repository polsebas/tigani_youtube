# SPEC — `transcript-chapterizer`

Estado: **v0 cerrado** (parser, capítulos, Agno inyectable, JSON/Markdown y CLI). El corte 4.1 separa la propuesta plana del agente del contrato público, sin cambiar `chapters.json`. El cliente de YouTube sigue sin implementarse. Este módulo **solo cataloga lo dicho**; los módulos `official-data-charts`, `visual-assets-fetcher` y `broadcast-package-builder` viven en sus propias SPECs (también v0 cerradas en el PoC).

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

`HardDataMention`: `cue_index` (`>= 0`), `timestamp`, `indicator_label`, `raw_value_text`, `time_reference: str | None = None`. `indicator_label` y `raw_value_text` tienen que seguir teniendo contenido después de `strip()`. `time_reference` no se resuelve a una fecha. Una cadena vacía o solo con espacios (`""`, `"   "`) se normaliza a `None` antes de guardar, en el borrador y en la mención pública.

`VisualSubjectMention`: `cue_index`, `timestamp`, `subject_label`, `context_text` y `asset_kind` (`event_photo` o `conceptual_illustration`). `subject_label` y `context_text` tienen que seguir teniendo contenido después de `strip()`.

## 6. Agente

El agente no escribe `chapters.json`. `AgnoChapterizer` arma un `Workflow` de Agno 3.2.1 con dos `Step` (`max_retries=0`, `on_error=fail`, `telemetry=False`). El default de Agno es saltear un paso que falla; acá un error aborta el workflow. El paso 1 devuelve un `StepOutput` con el plan; si devolviera el modelo pelado, el paso siguiente recibiría solo su texto. El contrato que se ensambla al final sigue siendo `ChapterizedTranscript`.

El paso 1, `segmentar`, llama a un `Agent` con `output_schema=DraftChapterPlan`. Recibe la transcripción completa, una línea `indice | [HH:MM:SS] texto` por cue, sin el pre-escaneo de cifras. Solo propone fronteras y títulos. Para un video de unos 5 minutos la instrucción pide entre 2 y 5 bloques, sin fragmentar de más. En cuanto vuelve el plan, Python corre `validate_chapter_plan`. Si hay hueco, solape, índice fuera de rango o cobertura incompleta, lanza `ChapterValidationError` y el paso `extraer` no arranca.

El paso 2, `extraer`, corre una vez por capítulo y solo si el plan cerró. Cada llamada recibe únicamente las cues `[start_cue_index..end_cue_index]`, con sus índices globales, más `Cues con cifras detectadas: [...]` de ese tramo. El `Agent` usa `output_schema=DraftChapterDetails`. Tiene que respetar el signo de lo dicho, no poner texto meta en el zócalo (`(sin fecha)`, `N/A`) y catalogar `hard_data` y `visual_subjects` del tramo. Los post-hooks corren sobre ese capítulo. `CueGroundingGuardrail` ancla dentro de `[start_cue_index, end_cue_index]`: primero la cue declarada, después una coincidencia única en `±1`, y si ahí no está, una coincidencia única en todo el tramo. Cero apariciones o dos o más cues del capítulo lanzan `OutputCheckError`. Una cifra fuera del tramo no cuenta. Si `raw_value_text` no tiene ningún dígito (`cinco clases más`), o el dígito no se puede anclar a una sola cue del tramo (`5` cuando el texto dice «cinco» y `45`), esa mención se descarta y el capítulo sigue. No se traduce la palabra a un número ni se elige una cue entre varias.

| Modelo interno | Campos |
|---|---|
| `DraftChapterBoundary` | `start_cue_index`, `end_cue_index`, `title` |
| `DraftChapterPlan` | `chapters` (al menos uno) |
| `DraftChapterDetails` | `summary`, `suggested_lower_third`, `hard_data`, `visual_subjects` |

`DraftChapter` y `DraftChapterizedTranscript` siguen siendo el borrador que entra a `assemble_chapterized_transcript`. No se serializan. El paso 2 arma ese borrador uniendo plan y detalles.

| Modelo | Campos |
|---|---|
| `DraftChapter` | `start_cue_index`, `end_cue_index`, `title`, `summary`, `suggested_lower_third` |
| `DraftHardDataMention` | `cue_index`, `indicator_label`, `raw_value_text`, `time_reference: str \| None = None` |
| `DraftVisualSubjectMention` | `cue_index`, `subject_label`, `asset_kind`, `context_text` |
| `DraftChapterizedTranscript` | `chapters` (al menos uno), `hard_data` (default `[]`), `visual_subjects` (default `[]`) |

Esos modelos usan `extra="forbid"`, `strict=True` y `frozen=True`. `asset_kind` sigue siendo `event_photo` o `conceptual_illustration`. `indicator_label`, `raw_value_text`, `subject_label` y `context_text` tienen que tener contenido después de `strip()`. Esta propuesta no se serializa como salida del módulo. Las instrucciones le piden al modelo rangos de `cue_index` y dos listas planas referenciadas solo por `cue_index`: no copia timestamps y no anida menciones. Incluyen dos ejemplos que separan `indicator_label`, `raw_value_text` y `time_reference`. `time_reference` guarda la marca dicha (`hoy`, `2015`, `último mes`, `9 de enero`, `enero 2018`) y el año no queda en `indicator_label`. `cue_index` es el de la cifra literal. `suggested_lower_third` es un zócalo 16:9 de hasta 100 caracteres y no mezcla un monto de vencimiento con un monto colocado. Toda cifra relevante del `summary` también va en `hard_data`.

`format_cue_lines` deja cada línea `indice | [HH:MM:SS] texto` intacta. `format_chapterizer_input` le agrega `Cues con cifras detectadas: [...]`, con los `cue_index` del tramo cuyo texto tiene un dígito o un `%`. El paso 1 usa solo las líneas. El paso 2 usa las líneas del capítulo más ese pre-escaneo.

Cada `Agent` recibe su `expected_output`. Los post-hooks están solo en el extractor. `CueGroundingGuardrail` normaliza separadores (`8,000`, `8.000` y `8000` coinciden; `2.5` y `2,5` también). Si la cifra está en la cue declarada, el índice no cambia. Si no, mira `[cue_index - 1, cue_index + 1]` recortado al capítulo. Si ahí no hay una coincidencia única, busca una sola aparición en todo el tramo y reancla a esa cue. Cero apariciones o dos o más cues del capítulo lanzan `OutputCheckError`. Una cifra fuera del tramo no cuenta. `TimeReferenceGuardrail` falla si `indicator_label` trae un año `19xx` o `20xx` y `time_reference` es `None`. `LowerThirdLengthGuardrail` falla si el zócalo supera `MAX_LOWER_THIRD_LENGTH` (100). `SummaryHardDataConsistencyGuardrail` falla si `hard_data` está vacío y el `summary` trae una métrica explícita (`2.5%`, `26,000 millones`, dólares, pesos o USD). `SpanishLanguageGuardrail` falla si en `summary` o `suggested_lower_third` hay al menos dos marcas propias del inglés (`the`, `and`, `with`, `including`, `which`, `current`, `previously`, `highlights` y otras del mismo grupo) y superan a las marcas del español. `swap`, `default` y `USD` no cuentan como inglés. El extractor tiene que redactar `summary`, `suggested_lower_third`, `indicator_label`, `subject_label` y `context_text` en español, y una cifra económica no va como `event_photo`.

En Agno 3.2.1 un `OutputCheckError` de un post-hook no sale de `Agent.run`: el run vuelve con `RunStatus.error`. `AgnoChapterizer` también atrapa `OutputCheckError` si el doble de pruebas lo propaga. En los dos casos traduce a `ChapterValidationError` y no ensambla.

`AgnoChapterizer.chapterize` corre el workflow y devuelve el `ChapterizedTranscript` público de la sección 5. `chapterize_transcript(cues, engine)` rechaza una lista vacía, llama al `ChapterizerEngine` y después corre `validate_chapterized_transcript`. Un motor inyectado puede devolver el contrato público ya armado; el validador lo revisa igual. Si un paso no devuelve el modelo que le toca, falla cerrado con `ChapterizerOutputError`.

En Agno 3.2.1 la salida estructurada entra por `output_schema` en `Agent`. Esa versión no tiene `response_model`. `temperature=0.0` se configura sobre el modelo inyectado de `agno.models`, porque `Agent` no recibe ese argumento. El código no importa SDKs crudos de proveedores.

`build_agno_model_from_env()` lee `TIGANI_LLM_PROVIDER` y `TIGANI_LLM_MODEL`. Los wrappers admitidos son `ollama` (`Ollama`), `openai` (`OpenAIChat`), `anthropic` (`Claude`) y `google` (`Gemini`). En Ollama la temperatura va en `options`, porque ese wrapper no declara el campo `temperature`; igual queda en `0.0`. El mismo wrapper no declara `think`. Con `TIGANI_LLM_PROVIDER=ollama`, `TIGANI_OLLAMA_THINK` es opcional: `true`/`1` o `false`/`0`, sin importar mayúsculas. Si está definida, se manda en `request_params` como `{"think": true|false}`, porque `Client.chat` de Ollama recibe ese argumento y Agno reenvía `request_params`. Si no está definida, no se toca el default del modelo. Un valor inválido es `ModelConfigError`, sale por stderr y el proceso termina con código `1`. Si falta el proveedor, el id, el proveedor no está en la lista o el wrapper no carga, el error también es `ModelConfigError`. No se hardcodean API keys.

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

La partición no exige que `raw_value_text` sea un substring ni filtra dígitos nuevos en el título. El anclaje numérico y el tope del zócalo corren antes, en los post-hooks.

## 8. Errores

| Situación | Error |
|---|---|
| Archivo ilegible, línea inválida, texto vacío, reloj fuera de rango o timestamps decrecientes | `TranscriptFormatError` |
| Hueco, solape, cobertura incompleta, índice fuera de `0..len(cues)-1`, rango invertido, mención que no cae en un único capítulo, reloj distinto al de la cue o mención mal ubicada | `ChapterValidationError` |
| Plan del paso 1 con hueco, solape, índice inválido o cobertura incompleta | `ChapterValidationError` antes de invocar el paso 2 |
| Cifra ausente o repetida en el capítulo, anclaje ambiguo en `±1`, año en `indicator_label` con `time_reference` vacío, zócalo de más de 100 caracteres, resumen con cifras y `hard_data` vacío, o prosa en inglés | `OutputCheckError` dentro del post-hook; `AgnoChapterizer` lo traduce a `ChapterValidationError` cuando `Agent.run` devuelve `RunStatus.error` o cuando la excepción sale del `run` |
| `TIGANI_OLLAMA_THINK` con un valor distinto de `true`, `false`, `1` o `0` | `ModelConfigError` en stderr, código `1` |

No se reintenta contra un modelo dentro de este módulo. El ensamblado determinista no vuelve a llamar al agente ni corrige un JSON anidado. El reanclaje dentro del capítulo tampoco es un reintento: mueve el `cue_index` en Python y no llama otra vez al modelo.

## 9. Arquitectura

v0 completo. El cliente de YouTube no está implementado.

```text
src/tigani_broadcast/transcript_chapterizer/
  source.py           # Protocol TranscriptSource; sin cliente de YouTube
  parse.py            # archivo [HH:MM:SS] -> cues
  models.py           # Cue, contrato público y propuesta plana del agente
  validate.py         # validate_chapterized_transcript
  guardrails.py       # post_hooks: anclaje, año, zócalo, cifras y español
  chapterizer.py      # Workflow de 2 pasos, assemble y chapterize_transcript
  render.py           # JSON indent=2 y Markdown
  cli.py              # argparse y build_agno_model_from_env
  __main__.py         # python -m tigani_broadcast.transcript_chapterizer
tests/transcript_chapterizer/
```

```text
cues = parse(entrada)
plan = segmentar(lineas completas)      # DraftChapterPlan
validate_chapter_plan(plan, cues)       # si falla, no hay paso 2
por cada capítulo:
    detalle = extraer(cues del tramo)   # DraftChapterDetails + post_hooks
paquete = assemble_chapterized_transcript(plan + detalles, cues)
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
6. Corte 4.2. Pre-escaneo de cifras, `expected_output`, ejemplos en las instrucciones y tres post-hooks de Agno. Hecho. Sin otra llamada al modelo y sin cambio de `chapters.json` ni `chapters.md`.
7. Corte 4.3. Workflow de dos pasos con contexto aislado por capítulo, y `time_reference` vacío normalizado a `None`. Hecho. El contrato público no cambia.
8. Corte 4.4. `TIGANI_OLLAMA_THINK`, español obligatorio en el extractor, y guardrails de cifras en el resumen y de idioma. Hecho. El contrato público no cambia.

## 12. Salida a disco y CLI

`render_json` escribe UTF-8 con `indent=2` y `ensure_ascii=False`. `render_markdown` arma una sección por capítulo con el rango `[start_time - end_time]`, el título, el zócalo (`suggested_lower_third`), el resumen y las menciones con su timestamp.

```text
python -m tigani_broadcast.transcript_chapterizer \
  --input transcripcion.txt \
  --output chapters.json \
  [--markdown chapters.md]
```

`main(argv, engine=None)` usa el motor inyectado y no lee el entorno. Sin motor, construye `AgnoChapterizer` desde las variables. Código `0` si escribió los archivos. Código `1` y un mensaje en stderr ante archivo ilegible, `TranscriptFormatError`, `ChapterValidationError` o `ModelConfigError`.
