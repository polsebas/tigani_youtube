"""CLI de broadcast-package-builder. Ensambla el paquete OBS y el kit de publicación."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from tigani_broadcast.broadcast_package_builder.assemble import (
    PackageValidationError,
    assemble_broadcast_package,
)
from tigani_broadcast.broadcast_package_builder.deck import write_deck_files
from tigani_broadcast.broadcast_package_builder.publishing import write_publishing_files
from tigani_broadcast.official_data_charts.models import ChartsPackage
from tigani_broadcast.transcript_chapterizer.models import ChapterizedTranscript
from tigani_broadcast.visual_assets_fetcher.models import VisualAssetsPackage

EXIT_OK = 0
EXIT_ERROR = 1


class PackageBuilderCliError(ValueError):
    """Error de argumentos, archivo o JSON inválido del CLI."""


def run_cli(argv: Sequence[str] | None = None) -> int:
    """Lee chapters/charts/assets y escribe el paquete portable completo."""
    parser = _parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        chapters = _load_chapters(args.chapters)
        charts = _load_charts(args.charts)
        assets = _load_assets(args.assets)
        output_dir: Path = args.output_dir

        manifest = assemble_broadcast_package(
            chapters,
            charts,
            assets,
            output_dir=output_dir,
            video_title=args.video_title,
            video_url=args.video_url,
            include_chapter_covers=not args.no_chapter_covers,
            include_errors=args.include_errors,
            outro_image=args.outro_image,
        )
        write_deck_files(chapters, manifest, output_dir)
        write_publishing_files(chapters, charts, manifest, output_dir)
    except (
        PackageBuilderCliError,
        PackageValidationError,
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


def _load_chapters(path: Path) -> ChapterizedTranscript:
    payload = _load_json(path, label="chapters.json")
    try:
        # JSON trae strings; strict=False permite coerción ISO → date/tipos.
        return ChapterizedTranscript.model_validate(payload, strict=False)
    except ValidationError as exc:
        raise PackageBuilderCliError(f"chapters.json inválido: {exc}") from exc


def _load_charts(path: Path) -> ChartsPackage:
    payload = _load_json(path, label="charts.json")
    try:
        return ChartsPackage.model_validate(payload, strict=False)
    except ValidationError as exc:
        raise PackageBuilderCliError(f"charts.json inválido: {exc}") from exc


def _load_assets(path: Path) -> VisualAssetsPackage:
    payload = _load_json(path, label="assets.json")
    try:
        return VisualAssetsPackage.model_validate(payload, strict=False)
    except ValidationError as exc:
        raise PackageBuilderCliError(f"assets.json inválido: {exc}") from exc


def _load_json(path: Path, *, label: str) -> object:
    if not path.is_file():
        raise PackageBuilderCliError(f"no existe el archivo {label}: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PackageBuilderCliError(f"{label} inválido (JSON): {exc}") from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tigani_broadcast.broadcast_package_builder",
        description=(
            "Ensambla chapters/charts/assets en un paquete OBS 16:9 "
            "con deck.html y kit de publicación."
        ),
    )
    parser.add_argument("--chapters", type=Path, required=True, help="Ruta a chapters.json")
    parser.add_argument("--charts", type=Path, required=True, help="Ruta a charts.json")
    parser.add_argument("--assets", type=Path, required=True, help="Ruta a assets.json")
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directorio destino del paquete portable",
    )
    parser.add_argument("--video-title", required=True, help="Título del video")
    parser.add_argument("--video-url", default=None, help="URL pública del video (opcional)")
    parser.add_argument(
        "--no-chapter-covers",
        action="store_true",
        help="Omite las portadas de capítulo en la rotación",
    )
    parser.add_argument(
        "--include-errors",
        action="store_true",
        help="Incluye placas fetch_error en deck.html",
    )
    parser.add_argument(
        "--outro-image",
        type=Path,
        default=None,
        help="Imagen del cierre promocional (si no, assets/outro.png o assets/outro.jpg)",
    )
    return parser
