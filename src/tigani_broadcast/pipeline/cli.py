"""CLI raíz del pipeline: `tigani-broadcast run ...`."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from tigani_broadcast.pipeline.models import PipelineConfig, StageResult
from tigani_broadcast.pipeline.runner import StageRunners, run_pipeline

EXIT_OK = 0
EXIT_ERROR = 1

_STAGE_INDEX: dict[str, int] = {
    "chapterizer": 1,
    "charts": 2,
    "visuals": 3,
    "package": 4,
}


class PipelineCliError(ValueError):
    """Error de argumentos o validación del CLI raíz."""


def build_parser() -> argparse.ArgumentParser:
    """Parser raíz con subcomando `run` y flags del orquestador."""
    parser = argparse.ArgumentParser(
        prog="tigani-broadcast",
        description=(
            "Orquesta transcript-chapterizer, official-data-charts, "
            "visual-assets-fetcher y broadcast-package-builder."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser(
        "run",
        help="Ejecuta las 4 etapas del pipeline y escribe work/ + package/",
    )
    run.add_argument(
        "--transcript",
        type=Path,
        required=True,
        help="Ruta a la transcripción UTF-8 ([HH:MM:SS] o .vtt/.srt)",
    )
    run.add_argument(
        "--publish-date",
        required=True,
        help="Fecha de publicación del video (YYYY-MM-DD)",
    )
    run.add_argument("--video-title", required=True, help="Título del video")
    run.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directorio raíz del workspace (work/, package/, pipeline_report.json)",
    )
    run.add_argument("--video-url", default=None, help="URL pública del video (opcional)")
    run.add_argument(
        "--resume",
        action="store_true",
        help="Saltea etapas 1–3 si sus salidas ya existen y validan (package siempre se regenera)",
    )
    run.add_argument(
        "--rerender-only",
        action="store_true",
        help=(
            "Regenera HTML y el paquete desde work/chapters.json, charts.json y assets.json "
            "sin LLM ni descargas"
        ),
    )
    run.add_argument(
        "--no-llm-visuals",
        action="store_true",
        help="Pasa --no-llm al visual-assets-fetcher",
    )
    run.add_argument(
        "--portrait-layout",
        choices=("sidebar", "contain"),
        default="sidebar",
        help='Encuadre de retratos verticales (default: "sidebar")',
    )
    run.add_argument(
        "--no-chapter-covers",
        action="store_true",
        help="Omite portadas de capítulo en el paquete OBS",
    )
    run.add_argument(
        "--include-errors",
        action="store_true",
        help="Incluye placas fetch_error en deck.html",
    )
    run.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help="Caché compartida (subcarpetas charts/ y visuals/)",
    )
    return parser


def run_cli(
    argv: Sequence[str] | None = None,
    *,
    runners: StageRunners | None = None,
) -> int:
    """Parsea `run`, ejecuta el pipeline y reporta etapas/rutas en consola."""
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.command != "run":
        parser.error(f"comando no soportado: {args.command}")

    try:
        publish_date = _parse_publish_date(args.publish_date)
        transcript_path = Path(args.transcript)
        if not transcript_path.is_file():
            raise PipelineCliError(f"no existe el archivo de transcripción: {transcript_path}")
        config = PipelineConfig(
            transcript_path=transcript_path,
            publish_date=publish_date,
            video_title=args.video_title,
            output_dir=Path(args.output_dir),
            video_url=args.video_url,
            resume=bool(args.resume),
            rerender_only=bool(args.rerender_only),
            no_llm_visuals=bool(args.no_llm_visuals),
            portrait_layout=args.portrait_layout,
            include_chapter_covers=not bool(args.no_chapter_covers),
            include_errors=bool(args.include_errors),
            cache_dir=Path(args.cache_dir) if args.cache_dir is not None else None,
        )
    except PipelineCliError as exc:
        print(exc, file=sys.stderr)
        return EXIT_ERROR

    report = run_pipeline(
        config,
        runners=runners,
        on_stage_complete=lambda result: _print_stage_line(
            result,
            rerender_only=bool(config.rerender_only),
        ),
    )
    report_path = Path(config.output_dir) / "pipeline_report.json"

    if report.succeeded:
        print("")
        print("Pipeline OK")
        if report.deck_html_path is not None:
            print(f"  deck.html: {report.deck_html_path}")
        if report.youtube_description_path is not None:
            print(f"  youtube_description.txt: {report.youtube_description_path}")
        if report.social_post_path is not None:
            print(f"  social_post.txt: {report.social_post_path}")
        print(f"  pipeline_report.json: {report_path}")
        return EXIT_OK

    failed = next((stage for stage in reversed(report.stages) if stage.status == "failed"), None)
    stage_name = failed.stage if failed is not None else "desconocida"
    detail = failed.error_message if failed is not None else "sin detalle"
    print(f"Pipeline falló en etapa {stage_name}: {detail}", file=sys.stderr)
    print(f"Ver reporte: {report_path}", file=sys.stderr)
    return EXIT_ERROR


def main(argv: Sequence[str] | None = None) -> None:
    """Entrypoint de consola / `python -m tigani_broadcast`."""
    raise SystemExit(run_cli(argv))


def _parse_publish_date(raw: str) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise PipelineCliError(f"publish-date inválida: {raw!r}. Usá YYYY-MM-DD.") from exc


def _print_stage_line(result: StageResult, *, rerender_only: bool = False) -> None:
    index = _STAGE_INDEX.get(result.stage, 0)
    if result.status == "skipped":
        reason = "rerender-only" if rerender_only else "resume"
        print(f"[{index}/4] {result.stage}: skipped ({reason})")
        return
    if result.status == "failed":
        print(
            f"[{index}/4] {result.stage}: failed ({result.duration_seconds:.1f}s) — "
            f"{result.error_message}"
        )
        return
    print(f"[{index}/4] {result.stage}: executed ({result.duration_seconds:.1f}s)")
