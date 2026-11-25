"""CLI de official-data-charts. Resolver y fetcher inyectables para tests offline."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from pydantic import ValidationError

from tigani_broadcast.official_data_charts.cache import DiskSeriesCache
from tigani_broadcast.official_data_charts.providers.factory import build_default_providers
from tigani_broadcast.official_data_charts.providers.fetcher import SeriesFetcher
from tigani_broadcast.official_data_charts.render import write_charts_package
from tigani_broadcast.official_data_charts.resolver import (
    AgnoMentionResolver,
    MentionResolverEngine,
    ResolutionValidationError,
    resolve_chapters_to_artifacts,
)
from tigani_broadcast.transcript_chapterizer.cli import (
    ModelConfigError,
    build_agno_model_from_env,
)
from tigani_broadcast.transcript_chapterizer.models import ChapterizedTranscript

EXIT_OK = 0
EXIT_ERROR = 1


class ChartsCliError(ValueError):
    """Error de argumentos, archivo o configuración del CLI."""


def build_default_series_fetcher(cache_dir: Path | None = None) -> SeriesFetcher:
    """Fetcher de producción con caché local opcional (AR + internacional + ADRs)."""
    cache = DiskSeriesCache(cache_dir=cache_dir) if cache_dir is not None else DiskSeriesCache()
    return SeriesFetcher(providers=build_default_providers(), cache=cache)


def run_cli(
    argv: Sequence[str] | None = None,
    *,
    resolver: MentionResolverEngine | None = None,
    fetcher: SeriesFetcher | None = None,
) -> int:
    """
    Lee chapters.json, resuelve menciones y escribe charts.json / HTML / markdown.

    Con `resolver` y `fetcher` inyectados no consulta entorno ni red (tests offline).
    """
    parser = _parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        publish_date = _parse_publish_date(args.publish_date)
        chapters = _load_chapters(args.input)
        active_resolver = resolver
        active_fetcher = fetcher
        if active_resolver is None:
            active_resolver = AgnoMentionResolver(build_agno_model_from_env())
        if active_fetcher is None:
            active_fetcher = build_default_series_fetcher(cache_dir=args.cache_dir)

        package = resolve_chapters_to_artifacts(
            chapters,
            publish_date,
            active_resolver,
            active_fetcher,
            source_chapters_path=str(args.input),
        )
        write_charts_package(
            package,
            output_json=args.output,
            charts_dir=args.charts_dir,
            markdown_path=args.markdown,
        )
    except (
        ChartsCliError,
        ModelConfigError,
        ResolutionValidationError,
        ValidationError,
        OSError,
        json.JSONDecodeError,
    ) as exc:
        print(exc, file=sys.stderr)
        return EXIT_ERROR
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    """Entrypoint del módulo."""
    return run_cli(argv)


def _parse_publish_date(raw: str) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise ChartsCliError(f"publish-date inválida: {raw!r}. Usá YYYY-MM-DD.") from exc


def _load_chapters(path: Path) -> ChapterizedTranscript:
    if not path.is_file():
        raise ChartsCliError(f"no existe el archivo de entrada: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ChartsCliError(f"chapters.json inválido (JSON): {exc}") from exc
    try:
        return ChapterizedTranscript.model_validate(payload)
    except ValidationError as exc:
        raise ChartsCliError(f"chapters.json inválido: {exc}") from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tigani_broadcast.official_data_charts",
        description=(
            "Resuelve HardDataMention de chapters.json contra fuentes oficiales "
            "y genera charts.json + placas HTML 16:9."
        ),
    )
    parser.add_argument(
        "--input",
        required=True,
        type=Path,
        help="Ruta a chapters.json (salida de transcript-chapterizer)",
    )
    parser.add_argument(
        "--publish-date",
        required=True,
        help="Fecha de publicación del video (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Destino charts.json",
    )
    parser.add_argument(
        "--charts-dir",
        required=True,
        type=Path,
        help="Directorio de placas HTML 16:9",
    )
    parser.add_argument(
        "--markdown",
        type=Path,
        help="Destino opcional charts.md",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        help="Override del directorio de DiskSeriesCache",
    )
    return parser
