# Guía de uso de punta a punta — `tigani-broadcast`

`tigani-broadcast` convierte una transcripción con timestamps (`.txt`, `.vtt` o `.srt`) en un paquete autocontenido de placas 16:9 listas para **OBS Studio**, con datos económicos verificables, imágenes con licencia segura para YouTube y textos listos para publicar.

---

## 1. Requisitos e instalación

- **Python 3.14** y **`uv`**
- **Un proveedor LLM compatible con Agno** (por ejemplo, **Ollama** corriendo en local con `qwen3:8b`, o un proveedor en la nube).
- **OBS Studio** (para proyectar el paquete final).

### Instalación del proyecto
```bash
uv sync

```

Verificá que el CLI quedó instalado (sin necesidad de `PYTHONPATH=src`):

```bash
uv run tigani-broadcast run --help

```

---

## 2. Variables de entorno

### Obligatorias para etapas con LLM (Módulos 1, 2 y 3)

```bash
export TIGANI_LLM_PROVIDER=ollama
export TIGANI_LLM_MODEL=qwen3:8b
export TIGANI_OLLAMA_THINK=false   # recomendado para modelos chicos locales

```

### Opcionales (fuentes de datos y caché)

```bash
# Opcional: API oficial de INDEC. Si no se define, hace fallback automático a Datos Argentina.
export INDEC_API_TOKEN="tu_token_jwt"

# Opcional: solo necesario si el video consulta series de EE. UU. en FRED.
export FRED_API_KEY="tu_api_key_fred"

# Opcional: directorio base de caché en disco para APIs de datos e imágenes.
export TIGANI_CACHE_DIR=".cache/tigani_broadcast"

```

> Nunca subas tokens ni archivos `.env` al repositorio.

---

## 3. Ejecución completa (un solo comando)

El comando `tigani-broadcast run` encadena las 4 etapas en orden:

1. **`chapterizer`** (`transcript-chapterizer`): divide la transcripción en capítulos y detecta menciones numéricas y sujetos visuales.
2. **`charts`** (`official-data-charts`): resuelve menciones contra el catálogo cerrado de 33 series (Argentina, internacionales y ADRs), descarga datos oficiales y renderiza placas HTML 16:9 con SVG puro (o placas `quoted_only` sin inventar cifras).
3. **`visuals`** (`visual-assets-fetcher`): deduplica sujetos por capítulo, busca imágenes en Wikimedia Commons y Openverse filtrando licencias *fail-closed* (solo `PD`, `CC0`, `CC BY`, `CC BY-SA`), las descarga y genera placas HTML 16:9 con crédito visible.
4. **`package`** (`broadcast-package-builder`): ensambla todo en una carpeta portable para OBS (`deck.html` + placas individuales) y genera los textos de publicación.

### Ejemplo real

```bash
TIGANI_LLM_PROVIDER=ollama \
TIGANI_LLM_MODEL=qwen3:8b \
TIGANI_OLLAMA_THINK=false \
uv run tigani-broadcast run \
  --transcript data/kP_G1sAStQE.txt \
  --publish-date 2025-12-11 \
  --video-title "Inflación, reservas y deuda: qué muestran los datos" \
  --video-url "[https://youtu.be/kP_G1sAStQE](https://youtu.be/kP_G1sAStQE)" \
  --output-dir out/run_kP_G1sAStQE

```

### Opciones útiles del CLI

| Flag | Descripción |
| --- | --- |
| `--transcript` | Ruta a la transcripción UTF-8 (`[HH:MM:SS]`, `.vtt` o `.srt`). |
| `--publish-date` | Fecha de publicación (`YYYY-MM-DD`). Ancla las ventanas temporales y evita datos futuros. |
| `--video-title` | Título del episodio (portadas, YouTube y post social). |
| `--output-dir` | Carpeta raíz del workspace (`work/`, `package/` y `pipeline_report.json`). |
| `--video-url` | URL del video (opcional; si se omite, `social_post.txt` usa `[LINK_VIDEO]`). |
| `--resume` | Saltea las etapas 1–3 si sus JSON y archivos ya existen y validan; siempre regenera `package/`. |
| `--no-llm-visuals` | Usa el planificador determinista puro en el Módulo 3 (más rápido, sin LLM). |
| `--portrait-layout` | Encuadre para retratos verticales: `sidebar` (default, barra lateral de texto) o `contain`. |
| `--no-chapter-covers` | Omite las placas separadoras de inicio de capítulo en `deck.html`. |
| `--include-errors` | Incluye placas en estado `fetch_error` dentro de `deck.html` (por defecto se excluyen del aire). |
| `--cache-dir` | Directorio de caché compartida (subcarpetas `charts/` y `visuals/`). |

---

## 4. Estructura de la carpeta generada

Al terminar, dentro de `--output-dir` (ej. `out/run_kP_G1sAStQE/`) vas a encontrar:

```text
out/run_kP_G1sAStQE/
├── pipeline_report.json          # Tiempos, estado de cada etapa y rutas finales
├── work/                         # Artefactos intermedios (usados por --resume)
│   ├── chapters.json / .md
│   ├── charts.json / .md
│   ├── charts/
│   ├── assets.json / .md
│   └── assets/
└── package/                      # CARPETA PORTABLE PARA OBS Y PUBLICACIÓN
    ├── deck.html                 # Player 16:9 único para OBS Browser Source
    ├── package.json              # Manifiesto maestro con la línea de tiempo
    ├── rundown.md                # Escaleta de operación y errores excluidos
    ├── youtube_description.txt   # Capítulos (desde 00:00), fuentes y licencias CC
    ├── social_post.txt           # Borrador promocional para X / LinkedIn / Comunidad
    └── slides/
        ├── chapters/             # Portadas de capítulo
        ├── charts/               # Placas de datos y gráficos SVG
        └── visuals/              # Placas de imágenes + subcarpeta images/

```

> Toda la carpeta `package/` usa rutas relativas y es **100 % offline** (sin CDNs). Podés copiarla a otra PC con OBS sin que se rompa ningún enlace.

---

## 5. Cómo reanudar o corregir una etapa (`--resume`)

Si la corrida tardó varios minutos y querés cambiar el título, la URL, el layout o reintentar un error puntual de red:

1. **Cambiar título, URL o flags de empaquetado (< 1 s):** volvé a correr el mismo comando agregando `--resume`. Saltea las etapas 1–3 y regenera solo `package/`.
2. **Reintentar únicamente datos (`charts`) o imágenes (`visuals`):** borrá solo el archivo intermedio correspondiente (`work/charts.json` o `work/assets.json`) y corré con `--resume`. El pipeline salteará el resto de las etapas válidas.

```bash
uv run tigani-broadcast run \
  --transcript data/kP_G1sAStQE.txt \
  --publish-date 2025-12-11 \
  --video-title "Nuevo título ajustado" \
  --output-dir out/run_kP_G1sAStQE \
  --resume

```

---

## 6. Operación en OBS Studio (16:9)

1. En OBS Studio, agregá una fuente **Navegador (Browser Source)**.
2. Marcá **Archivo local (Local file)** y seleccioná `package/deck.html`.
3. Configurá el tamaño en **Ancho: `1920**`, **Alto: `1080**`.
4. Para pasar placas durante la grabación o vivo, hacé clic derecho sobre la fuente → **Interactuar (Interact)** y usá el teclado:
* `→` o `Espacio`: placa siguiente
* `←`: placa anterior
* `Inicio` (`Home`) / `Fin` (`End`): primera / última placa
* `H`: mostrar u ocultar la barra de operador (HUD con índice, timestamp, capítulo y título)



> El HUD arranca **oculto** por defecto para salir limpio al aire. Si querés ensayar con el HUD visible desde el inicio en tu navegador, abrí `deck.html?hud=1`.

### Orden de placas y colisiones

* Cuando un mismo momento (`cue`) tiene tanto un dato como una imagen, `deck.html` siempre ubica **primero el dato/gráfico** y **después el visual**.
* Las placas con estado `fetch_error` quedan listadas en `package/rundown.md` para revisión, pero **no salen al aire** salvo que pases `--include-errors`.

---

## 7. Publicación en YouTube y redes sociales

Antes de publicar, revisá estos tres archivos dentro de `package/`:

1. **`rundown.md`**: chequeá la línea de tiempo y confirmá si hubo algún `fetch_error` excluido.
2. **`youtube_description.txt`**: copialo y pegalo en la descripción de YouTube. Incluye:
* Timestamps de capítulos comenzando en `00:00` (activa la barra de capítulos de YouTube).
* Fuentes de datos oficiales y `series_id` verificados.
* Créditos de autor, licencia y URL de origen para cada imagen (cumplimiento obligatorio de `CC BY` / `CC BY-SA`).


3. **`social_post.txt`**: borrador listo para X, LinkedIn o pestaña Comunidad de YouTube, armado únicamente con los capítulos y datos presentes en el episodio.

---

## 8. Ejecución de módulos individuales (uso avanzado)

Cada módulo también puede ejecutarse por separado:

```bash
# Módulo 1: chapterizer
uv run python -m tigani_broadcast.transcript_chapterizer --help

# Módulo 2: official-data-charts
uv run python -m tigani_broadcast.official_data_charts --help

# Módulo 3: visual-assets-fetcher
uv run python -m tigani_broadcast.visual_assets_fetcher --help

# Módulo 4: broadcast-package-builder
uv run python -m tigani_broadcast.broadcast_package_builder --help

```

---

## 9. Verificación y diagnóstico rápido

### Correr tests y linter (100 % offline)

```bash
uv run pytest --cov=src --cov-report=term-missing
uv run ruff check src tests && uv run ruff format --check src tests

```

### Problemas frecuentes

* **Falta una placa de dato en `deck.html`:** revisá `package/rundown.md` (sección de errores excluidos) y `work/charts.md`. Si fue un timeout de red, borrá `work/charts.json` y relanzá con `--resume`.
* **Error de autenticación en FRED:** definí `FRED_API_KEY` en el entorno si el episodio pide series de EE. UU. (`us_fred_*`).
* **Imágenes en `fallback_card`:** indica que ni Wikimedia Commons ni Openverse devolvieron una imagen con licencia comercial permitida (`PD`, `CC0`, `CC BY`, `CC BY-SA`) y ancho `>= 640 px`. Es comportamiento esperado (*fail-closed*) para evitar strikes de copyright.
* **Corridas lentas en local:** usá `TIGANI_OLLAMA_THINK=false`, pasá `--cache-dir` para reutilizar descargas entre corridas y `--no-llm-visuals` si querés omitir el LLM en la búsqueda de imágenes.
