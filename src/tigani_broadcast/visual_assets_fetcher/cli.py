"""CLI de visual-assets-fetcher. Planner y fetcher inyectables para tests offline."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from tigani_broadcast.transcript_chapterizer.cli import (
    ModelConfigError,
    build_agno_model_from_env,
)
from tigani_broadcast.transcript_chapterizer.models import ChapterizedTranscript
from tigani_broadcast.visual_assets_fetcher.cache import DiskVisualSearchCache
from tigani_broadcast.visual_assets_fetcher.models import PortraitLayout
from tigani_broadcast.visual_assets_fetcher.planner import (
    AgnoVisualQueryPlanner,
    DeterministicVisualQueryPlanner,
    PlannerError,
    VisualQueryPlanner,
    resolve_chapters_to_visual_assets,
)
from tigani_broadcast.visual_assets_fetcher.providers.fetcher import VisualAssetFetcher
from tigani_broadcast.visual_assets_fetcher.providers.openverse import OpenverseProvider
from tigani_broadcast.visual_assets_fetcher.providers.wikimedia import WikimediaCommonsProvider
from tigani_broadcast.visual_assets_fetcher.render import write_visual_assets_package

EXIT_OK = 0
EXIT_ERROR = 1


class VisualAssetsCliError(ValueError):
    """Error de argumentos, archivo o configuración del CLI."""


def build_default_visual_fetcher(cache_dir: Path | None = None) -> VisualAssetFetcher:
    """Fetcher de producción con Wikimedia + Openverse y caché local."""
    cache = (
        DiskVisualSearchCache(cache_dir=cache_dir)
        if cache_dir is not None
        else DiskVisualSearchCache()
    )
    return VisualAssetFetcher(
        providers={
            "wikimedia": WikimediaCommonsProvider(),
            "openverse": OpenverseProvider(),
        },
        cache=cache,
    )


def run_cli(
    argv: Sequence[str] | None = None,
    *,
    planner: VisualQueryPlanner | None = None,
    fetcher: VisualAssetFetcher | None = None,
) -> int:
    """
    Lee chapters.json, resuelve sujetos visuales y escribe assets.json / HTML / markdown.

    Con `planner` y `fetcher` inyectados no consulta entorno ni red (tests offline).
    """
    parser = _parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        chapters = _load_chapters(args.input)
        portrait_layout = _parse_portrait_layout(args.portrait_layout)
        active_planner = planner
        active_fetcher = fetcher
        if active_planner is None:
            if args.no_llm:
                active_planner = DeterministicVisualQueryPlanner()
            else:
                active_planner = AgnoVisualQueryPlanner(build_agno_model_from_env())
        if active_fetcher is None:
            active_fetcher = build_default_visual_fetcher(cache_dir=args.cache_dir)

        assets_dir: Path = args.assets_dir
        images_dir = assets_dir / "images"
        package = resolve_chapters_to_visual_assets(
            chapters,
            planner=active_planner,
            fetcher=active_fetcher,
            images_dir=images_dir,
            portrait_layout=portrait_layout,
            source_chapters_path=str(args.input),
        )
        write_visual_assets_package(
            package,
            output_json=args.output,
            assets_dir=assets_dir,
            markdown_path=args.markdown,
        )
    except (
        VisualAssetsCliError,
        ModelConfigError,
        PlannerError,
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
    if not path.is_file():
        raise VisualAssetsCliError(f"no existe el archivo de entrada: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise VisualAssetsCliError(f"chapters.json inválido (JSON): {exc}") from exc
    try:
        return ChapterizedTranscript.model_validate(payload)
    except ValidationError as exc:
        raise VisualAssetsCliError(f"chapters.json inválido: {exc}") from exc


def _parse_portrait_layout(raw: str) -> PortraitLayout:
    if raw in ("sidebar", "contain"):
        return raw  # type: ignore[return-value]
    raise VisualAssetsCliError(f"portrait-layout inválido: {raw!r}. Usá sidebar o contain.")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tigani_broadcast.visual_assets_fetcher",
        description=(
            "Resuelve visual_subjects de chapters.json contra Wikimedia/Openverse "
            "y genera assets.json + placas HTML 16:9."
        ),
    )
    parser.add_argument(
        "--input",
        required=True,
        type=Path,
        help="Ruta a chapters.json (salida de transcript-chapterizer)",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Destino assets.json",
    )
    parser.add_argument(
        "--assets-dir",
        required=True,
        type=Path,
        help="Directorio de placas HTML 16:9 e images/",
    )
    parser.add_argument(
        "--markdown",
        type=Path,
        help="Destino opcional assets.md",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Usá DeterministicVisualQueryPlanner (sin Agno)",
    )
    parser.add_argument(
        "--portrait-layout",
        default="sidebar",
        help='Encuadre de retratos verticales: "sidebar" (default) o "contain"',
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        help="Override del directorio de DiskVisualSearchCache",
    )
    return parser
