"""Orquestación en proceso de los 4 módulos con `--resume` y fail-fast."""

from __future__ import annotations

import contextlib
import io
import json
import time
import traceback
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from tigani_broadcast.broadcast_package_builder.cli import run_cli as run_package_cli
from tigani_broadcast.official_data_charts.cli import run_cli as run_charts_cli
from tigani_broadcast.official_data_charts.models import ChartsPackage
from tigani_broadcast.pipeline.models import (
    PipelineConfig,
    PipelineReport,
    StageName,
    StageResult,
)
from tigani_broadcast.transcript_chapterizer.cli import main as run_chapterizer_cli
from tigani_broadcast.transcript_chapterizer.models import ChapterizedTranscript
from tigani_broadcast.visual_assets_fetcher.cli import run_cli as run_visuals_cli
from tigani_broadcast.visual_assets_fetcher.models import VisualAssetsPackage

StageRunner = Callable[[list[str]], int]


@dataclass(frozen=True, slots=True)
class StageRunners:
    """Runners inyectables de cada etapa (por defecto: `run_cli` en proceso)."""

    chapterizer: StageRunner
    charts: StageRunner
    visuals: StageRunner
    package: StageRunner


def default_stage_runners() -> StageRunners:
    """Fábrica por defecto: invoca los CLI de cada módulo en el mismo proceso."""
    return StageRunners(
        chapterizer=_as_list_runner(run_chapterizer_cli),
        charts=_as_list_runner(run_charts_cli),
        visuals=_as_list_runner(run_visuals_cli),
        package=_as_list_runner(run_package_cli),
    )


def run_pipeline(
    config: PipelineConfig,
    *,
    runners: StageRunners | None = None,
    clock_fn: Callable[[], float] = time.monotonic,
    on_stage_complete: Callable[[StageResult], None] | None = None,
) -> PipelineReport:
    """Ejecuta las 4 etapas en orden estricto con fail-fast y reporte en disco."""
    active = runners if runners is not None else default_stage_runners()
    output_dir = Path(config.output_dir)
    work_dir = output_dir / "work"
    package_dir = output_dir / "package"
    work_dir.mkdir(parents=True, exist_ok=True)
    package_dir.mkdir(parents=True, exist_ok=True)

    paths = _WorkspacePaths(work_dir=work_dir, package_dir=package_dir)
    stage_results: list[StageResult] = []
    started = clock_fn()
    succeeded = True

    plan: list[tuple[StageName, StageRunner, list[str], Path | None, Callable[[], bool]]] = [
        (
            "chapterizer",
            active.chapterizer,
            _chapterizer_argv(config, paths),
            paths.chapters_json,
            lambda: _can_skip_chapterizer(paths),
        ),
        (
            "charts",
            active.charts,
            _charts_argv(config, paths),
            paths.charts_json,
            lambda: _can_skip_charts(config, paths),
        ),
        (
            "visuals",
            active.visuals,
            _visuals_argv(config, paths),
            paths.assets_json,
            lambda: _can_skip_visuals(config, paths),
        ),
        (
            "package",
            active.package,
            _package_argv(config, paths),
            package_dir,
            lambda: False,
        ),
    ]

    for stage, runner, argv, output_path, can_skip in plan:
        stage_started = clock_fn()
        if config.resume and can_skip():
            result = StageResult(
                stage=stage,
                status="skipped",
                duration_seconds=_elapsed(stage_started, clock_fn),
                output_path=str(output_path) if output_path is not None else None,
            )
            stage_results.append(result)
            if on_stage_complete is not None:
                on_stage_complete(result)
            continue

        code, error_message = _invoke_runner(runner, argv)
        duration = _elapsed(stage_started, clock_fn)
        if code != 0:
            result = StageResult(
                stage=stage,
                status="failed",
                duration_seconds=duration,
                output_path=str(output_path) if output_path is not None else None,
                error_message=error_message or f"etapa {stage} salió con código {code}",
            )
            stage_results.append(result)
            if on_stage_complete is not None:
                on_stage_complete(result)
            succeeded = False
            break

        result = StageResult(
            stage=stage,
            status="executed",
            duration_seconds=duration,
            output_path=str(output_path) if output_path is not None else None,
        )
        stage_results.append(result)
        if on_stage_complete is not None:
            on_stage_complete(result)

    report = _build_report(
        config,
        stages=stage_results,
        succeeded=succeeded,
        total_duration_seconds=_elapsed(started, clock_fn),
        package_dir=package_dir,
    )
    _write_report(output_dir / "pipeline_report.json", report)
    return report


def _as_list_runner(run_cli: Callable[..., int]) -> StageRunner:
    def _runner(argv: list[str]) -> int:
        return run_cli(argv)

    return _runner


def _invoke_runner(runner: StageRunner, argv: list[str]) -> tuple[int, str | None]:
    buffer = io.StringIO()
    try:
        with contextlib.redirect_stderr(buffer):
            code = runner(argv)
    except Exception as exc:  # noqa: BLE001 — fail-fast con mensaje auditable
        captured = buffer.getvalue().strip()
        detail = str(exc).strip() or traceback.format_exc(limit=3).strip()
        if captured:
            detail = f"{captured}\n{detail}"
        return 1, detail
    captured = buffer.getvalue().strip()
    if code != 0:
        return code, captured or f"código de salida {code}"
    return code, None


def _elapsed(started: float, clock_fn: Callable[[], float]) -> float:
    return max(0.0, clock_fn() - started)


@dataclass(frozen=True, slots=True)
class _WorkspacePaths:
    work_dir: Path
    package_dir: Path

    @property
    def chapters_json(self) -> Path:
        return self.work_dir / "chapters.json"

    @property
    def chapters_md(self) -> Path:
        return self.work_dir / "chapters.md"

    @property
    def charts_json(self) -> Path:
        return self.work_dir / "charts.json"

    @property
    def charts_md(self) -> Path:
        return self.work_dir / "charts.md"

    @property
    def charts_dir(self) -> Path:
        return self.work_dir / "charts"

    @property
    def assets_json(self) -> Path:
        return self.work_dir / "assets.json"

    @property
    def assets_md(self) -> Path:
        return self.work_dir / "assets.md"

    @property
    def assets_dir(self) -> Path:
        return self.work_dir / "assets"


def _chapterizer_argv(config: PipelineConfig, paths: _WorkspacePaths) -> list[str]:
    return [
        "--input",
        str(config.transcript_path),
        "--output",
        str(paths.chapters_json),
        "--markdown",
        str(paths.chapters_md),
    ]


def _charts_argv(config: PipelineConfig, paths: _WorkspacePaths) -> list[str]:
    argv = [
        "--input",
        str(paths.chapters_json),
        "--publish-date",
        config.publish_date.isoformat(),
        "--output",
        str(paths.charts_json),
        "--charts-dir",
        str(paths.charts_dir),
        "--markdown",
        str(paths.charts_md),
    ]
    if config.cache_dir is not None:
        argv.extend(["--cache-dir", str(Path(config.cache_dir) / "charts")])
    return argv


def _visuals_argv(config: PipelineConfig, paths: _WorkspacePaths) -> list[str]:
    argv = [
        "--input",
        str(paths.chapters_json),
        "--output",
        str(paths.assets_json),
        "--assets-dir",
        str(paths.assets_dir),
        "--markdown",
        str(paths.assets_md),
        "--portrait-layout",
        config.portrait_layout,
    ]
    if config.no_llm_visuals:
        argv.append("--no-llm")
    if config.cache_dir is not None:
        argv.extend(["--cache-dir", str(Path(config.cache_dir) / "visuals")])
    return argv


def _package_argv(config: PipelineConfig, paths: _WorkspacePaths) -> list[str]:
    argv = [
        "--chapters",
        str(paths.chapters_json),
        "--charts",
        str(paths.charts_json),
        "--assets",
        str(paths.assets_json),
        "--output-dir",
        str(paths.package_dir),
        "--video-title",
        config.video_title,
    ]
    if config.video_url is not None:
        argv.extend(["--video-url", config.video_url])
    if not config.include_chapter_covers:
        argv.append("--no-chapter-covers")
    if config.include_errors:
        argv.append("--include-errors")
    return argv


def _can_skip_chapterizer(paths: _WorkspacePaths) -> bool:
    if not paths.chapters_json.is_file():
        return False
    try:
        ChapterizedTranscript.model_validate_json(paths.chapters_json.read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError, json.JSONDecodeError):
        return False
    return True


def _can_skip_charts(config: PipelineConfig, paths: _WorkspacePaths) -> bool:
    if not paths.charts_json.is_file():
        return False
    try:
        package = ChartsPackage.model_validate_json(paths.charts_json.read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError, json.JSONDecodeError):
        return False
    if package.publish_date != config.publish_date:
        return False
    for item in package.items:
        if item.html_path is None or item.html_path.strip() == "":
            return False
        if not Path(item.html_path).is_file():
            return False
    return True


def _can_skip_visuals(config: PipelineConfig, paths: _WorkspacePaths) -> bool:
    if not paths.assets_json.is_file():
        return False
    try:
        package = VisualAssetsPackage.model_validate_json(
            paths.assets_json.read_text(encoding="utf-8")
        )
    except (OSError, ValidationError, ValueError, json.JSONDecodeError):
        return False
    if package.portrait_layout != config.portrait_layout:
        return False
    for item in package.items:
        if item.html_path is None or item.html_path.strip() == "":
            return False
        if not Path(item.html_path).is_file():
            return False
        if item.status == "verified_asset":
            if item.local_image_path is None or item.local_image_path.strip() == "":
                return False
            if not Path(item.local_image_path).is_file():
                return False
    return True


def _build_report(
    config: PipelineConfig,
    *,
    stages: Sequence[StageResult],
    succeeded: bool,
    total_duration_seconds: float,
    package_dir: Path,
) -> PipelineReport:
    deck = package_dir / "deck.html"
    youtube = package_dir / "youtube_description.txt"
    social = package_dir / "social_post.txt"
    return PipelineReport(
        transcript_path=str(config.transcript_path),
        publish_date=config.publish_date,
        video_title=config.video_title,
        output_dir=str(config.output_dir),
        resume=config.resume,
        succeeded=succeeded,
        total_duration_seconds=total_duration_seconds,
        stages=list(stages),
        deck_html_path=str(deck) if succeeded and deck.is_file() else None,
        youtube_description_path=str(youtube) if succeeded and youtube.is_file() else None,
        social_post_path=str(social) if succeeded and social.is_file() else None,
    )


def _write_report(path: Path, report: PipelineReport) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
