"""CLI de transcript-chapterizer. El motor se puede inyectar para correr sin red."""

import argparse
import importlib
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from agno.models.base import Model

from tigani_broadcast.transcript_chapterizer.chapterizer import (
    AgnoChapterizer,
    ChapterizerEngine,
    ChapterizerError,
    chapterize_transcript,
)
from tigani_broadcast.transcript_chapterizer.parse import (
    FileTranscriptSource,
    TranscriptFormatError,
)
from tigani_broadcast.transcript_chapterizer.render import write_json, write_markdown
from tigani_broadcast.transcript_chapterizer.validate import ChapterValidationError

EXIT_OK = 0
EXIT_ERROR = 1

# El wrapper de Ollama no tiene campo temperature: la API lo lee desde options.
_PROVIDERS: dict[str, tuple[str, str]] = {
    "ollama": ("agno.models.ollama", "Ollama"),
    "openai": ("agno.models.openai", "OpenAIChat"),
    "anthropic": ("agno.models.anthropic", "Claude"),
    "google": ("agno.models.google", "Gemini"),
}


class ModelConfigError(ChapterizerError):
    """Falta el proveedor, el id del modelo, o el wrapper de Agno no carga."""


def build_agno_model_from_env(environ: Mapping[str, str] | None = None) -> Model:
    """Arma un modelo de agno.models con temperature 0.0. No lee ni guarda API keys."""
    env = os.environ if environ is None else environ
    provider = env.get("TIGANI_LLM_PROVIDER", "").strip().lower()
    model_id = env.get("TIGANI_LLM_MODEL", "").strip()
    if provider == "" or model_id == "":
        raise ModelConfigError("faltan TIGANI_LLM_PROVIDER y TIGANI_LLM_MODEL")
    spec = _PROVIDERS.get(provider)
    if spec is None:
        supported = ", ".join(sorted(_PROVIDERS))
        raise ModelConfigError(f"proveedor no soportado: {provider}. Usá {supported}.")

    module_name, class_name = spec
    try:
        module = importlib.import_module(module_name)
        model_cls = getattr(module, class_name)
    except (ImportError, AttributeError) as exc:
        raise ModelConfigError(
            f"no se pudo cargar el wrapper de Agno para {provider}: {exc}"
        ) from exc

    if provider == "ollama":
        model = model_cls(id=model_id, options={"temperature": 0.0})
    else:
        model = model_cls(id=model_id, temperature=0.0)
    model.temperature = 0.0
    return model


def main(argv: Sequence[str] | None = None, engine: ChapterizerEngine | None = None) -> int:
    """Capitula un archivo y escribe JSON. Con engine, no consulta el entorno ni la red."""
    parser = _parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        active = engine if engine is not None else AgnoChapterizer(build_agno_model_from_env())
        cues = FileTranscriptSource(args.input).load()
        transcript = chapterize_transcript(cues, active)
        write_json(args.output, transcript)
        if args.markdown is not None:
            write_markdown(args.markdown, transcript)
    except (TranscriptFormatError, ChapterValidationError, ChapterizerError) as exc:
        print(exc, file=sys.stderr)
        return EXIT_ERROR
    return EXIT_OK


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tigani_broadcast.transcript_chapterizer",
        description="Capitula una transcripción [HH:MM:SS] y escribe el JSON del módulo.",
    )
    parser.add_argument("--input", required=True, type=Path, help="Archivo UTF-8 de cues")
    parser.add_argument("--output", required=True, type=Path, help="Destino chapters.json")
    parser.add_argument("--markdown", type=Path, help="Destino opcional de la escaleta")
    return parser
