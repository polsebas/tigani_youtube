"""Orquestador: orden, flags, resume, fail-fast — 100 % offline con runners fake."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from tigani_broadcast.official_data_charts.models import (
    ChartArtifact,
    ChartsPackage,
    SeriesData,
    SeriesMetrics,
    SeriesObservation,
)
from tigani_broadcast.pipeline.models import PipelineConfig
from tigani_broadcast.pipeline.runner import StageRunners, run_pipeline
from tigani_broadcast.transcript_chapterizer.models import Chapter, ChapterizedTranscript
from tigani_broadcast.visual_assets_fetcher.models import (
    PortraitLayout,
    VisualAssetArtifact,
    VisualAssetsPackage,
    VisualAttribution,
)


class _FakeClock:
    def __init__(self) -> None:
        self.value = 100.0

    def __call__(self) -> float:
        current = self.value
        self.value += 0.5
        return current


class _RecordingRunners:
    def __init__(self, *, fail_at: str | None = None) -> None:
        self.calls: dict[str, list[str]] = {}
        self.order: list[str] = []
        self.fail_at = fail_at

    def as_stage_runners(self, output_dir: Path) -> StageRunners:
        work = output_dir / "work"
        package = output_dir / "package"

        def chapterizer(argv: list[str]) -> int:
            return self._run("chapterizer", argv, lambda: _write_chapters(work))

        def charts(argv: list[str]) -> int:
            return self._run("charts", argv, lambda: _write_charts(work))

        def visuals(argv: list[str]) -> int:
            return self._run("visuals", argv, lambda: _write_visuals(work))

        def package_stage(argv: list[str]) -> int:
            return self._run("package", argv, lambda: _write_package(package))

        return StageRunners(
            chapterizer=chapterizer,
            charts=charts,
            visuals=visuals,
            package=package_stage,
        )

    def _run(self, name: str, argv: list[str], writer) -> int:
        self.order.append(name)
        self.calls[name] = list(argv)
        if self.fail_at == name:
            print(f"{name} falló a propósito", file=__import__("sys").stderr)
            return 1
        writer()
        return 0


def _config(tmp_path: Path, **overrides: object) -> PipelineConfig:
    transcript = tmp_path / "transcript.txt"
    transcript.write_text("[00:00:01] Hola\n", encoding="utf-8")
    payload: dict[str, object] = {
        "transcript_path": transcript,
        "publish_date": date(2025, 11, 25),
        "video_title": "Episodio piloto",
        "output_dir": tmp_path / "run",
        "video_url": "https://youtu.be/abc",
        "resume": False,
        "no_llm_visuals": True,
        "portrait_layout": "contain",
        "include_chapter_covers": False,
        "include_errors": True,
        "cache_dir": tmp_path / "cache",
    }
    payload.update(overrides)
    return PipelineConfig.model_validate(payload)


def _write_chapters(work: Path) -> None:
    work.mkdir(parents=True, exist_ok=True)
    chapters = ChapterizedTranscript(
        chapters=[
            Chapter(
                start_cue_index=0,
                end_cue_index=1,
                start_time="00:00:01",
                end_time="00:00:10",
                title="Apertura",
                summary="Resumen",
                suggested_lower_third="Apertura",
            )
        ]
    )
    (work / "chapters.json").write_text(chapters.model_dump_json(indent=2), encoding="utf-8")
    (work / "chapters.md").write_text("# chapters\n", encoding="utf-8")


def _write_charts(work: Path, *, publish_date: date = date(2025, 11, 25)) -> None:
    work.mkdir(parents=True, exist_ok=True)
    charts_dir = work / "charts"
    charts_dir.mkdir(parents=True, exist_ok=True)
    html = charts_dir / "ch00_cue000_00.html"
    html.write_text("<html>chart</html>", encoding="utf-8")
    series = SeriesData(
        catalog_id="ar_indec_ipc_mensual",
        provider="indec",
        source_tier="official_primary",
        series_id="ipc",
        source_url="https://example.org/ipc",
        source_attribution="Fuente: INDEC",
        unit="%",
        frequency="monthly",
        observations=[
            SeriesObservation(obs_date=date(2025, 1, 1), value=2.0),
            SeriesObservation(obs_date=date(2025, 2, 1), value=2.5),
        ],
    )
    metrics = SeriesMetrics(
        observation_count=2,
        valid_count=2,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 2, 1),
        first_value=2.0,
        latest_value=2.5,
        min_value=2.0,
        min_date=date(2025, 1, 1),
        max_value=2.5,
        max_date=date(2025, 2, 1),
        absolute_change=0.5,
        percent_change=25.0,
        has_provisional_flags=False,
        flags_present=[],
    )
    package = ChartsPackage(
        publish_date=publish_date,
        items=[
            ChartArtifact(
                chapter_index=0,
                cue_index=0,
                timestamp="00:00:01",
                indicator_label="IPC",
                raw_value_text="2,5%",
                resolution_status="verified_series",
                rationale="Catálogo",
                series=series,
                metrics=metrics,
                html_path=str(html),
            )
        ],
    )
    (work / "charts.json").write_text(
        json.dumps(package.model_dump(mode="json"), indent=2),
        encoding="utf-8",
    )
    (work / "charts.md").write_text("# charts\n", encoding="utf-8")


def _write_visuals(work: Path, *, portrait_layout: PortraitLayout = "contain") -> None:
    work.mkdir(parents=True, exist_ok=True)
    assets_dir = work / "assets"
    images_dir = assets_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    html = assets_dir / "ch00_cue000_00.html"
    image = images_dir / "gobierno.jpg"
    html.write_text('<html><img src="images/gobierno.jpg"/></html>', encoding="utf-8")
    image.write_bytes(b"fake-image")
    attribution = VisualAttribution(
        provider="wikimedia",
        author="Jane Doe",
        license_name="CC BY 4.0",
        license_code="CC-BY",
        source_page_url="https://commons.wikimedia.org/wiki/File:Example.jpg",
        image_url="https://upload.wikimedia.org/wikipedia/commons/example.jpg",
        width=1280,
        height=720,
        mime_type="image/jpeg",
    )
    package = VisualAssetsPackage(
        portrait_layout=portrait_layout,
        items=[
            VisualAssetArtifact(
                chapter_index=0,
                cue_index=0,
                timestamp="00:00:01",
                subject_label="gobierno",
                asset_kind="event_photo",
                context_text="contexto",
                occurrences_count=1,
                search_query="gobierno",
                status="verified_asset",
                attribution=attribution,
                local_image_path=str(image),
                html_path=str(html),
            )
        ],
    )
    (work / "assets.json").write_text(
        json.dumps(package.model_dump(mode="json"), indent=2),
        encoding="utf-8",
    )
    (work / "assets.md").write_text("# assets\n", encoding="utf-8")


def _write_package(package_dir: Path) -> None:
    package_dir.mkdir(parents=True, exist_ok=True)
    (package_dir / "deck.html").write_text("<html>deck</html>", encoding="utf-8")
    (package_dir / "youtube_description.txt").write_text("desc\n", encoding="utf-8")
    (package_dir / "social_post.txt").write_text("post\n", encoding="utf-8")
    (package_dir / "package.json").write_text("{}\n", encoding="utf-8")


def test_run_pipeline_completa_propaga_flags(tmp_path: Path) -> None:
    config = _config(tmp_path)
    recorder = _RecordingRunners()
    clock = _FakeClock()
    completed: list[str] = []

    report = run_pipeline(
        config,
        runners=recorder.as_stage_runners(config.output_dir),
        clock_fn=clock,
        on_stage_complete=lambda result: completed.append(f"{result.stage}:{result.status}"),
    )

    assert report.succeeded is True
    assert recorder.order == ["chapterizer", "charts", "visuals", "package"]
    assert completed == [
        "chapterizer:executed",
        "charts:executed",
        "visuals:executed",
        "package:executed",
    ]

    chapterizer_argv = recorder.calls["chapterizer"]
    assert "--input" in chapterizer_argv
    assert str(config.transcript_path) in chapterizer_argv

    charts_argv = recorder.calls["charts"]
    assert "--publish-date" in charts_argv
    assert "2025-11-25" in charts_argv
    assert "--cache-dir" in charts_argv
    cache_charts = charts_argv[charts_argv.index("--cache-dir") + 1]
    assert cache_charts.endswith("cache/charts") or cache_charts.endswith("cache\\charts")

    visuals_argv = recorder.calls["visuals"]
    assert "--no-llm" in visuals_argv
    assert "--portrait-layout" in visuals_argv
    assert "contain" in visuals_argv
    cache_visuals = visuals_argv[visuals_argv.index("--cache-dir") + 1]
    assert cache_visuals.endswith("cache/visuals") or cache_visuals.endswith("cache\\visuals")

    package_argv = recorder.calls["package"]
    assert "--video-title" in package_argv
    assert "Episodio piloto" in package_argv
    assert "--video-url" in package_argv
    assert "https://youtu.be/abc" in package_argv
    assert "--no-chapter-covers" in package_argv
    assert "--include-errors" in package_argv

    report_path = Path(config.output_dir) / "pipeline_report.json"
    assert report_path.is_file()
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["succeeded"] is True
    assert payload["deck_html_path"] is not None
    assert payload["youtube_description_path"] is not None
    assert payload["social_post_path"] is not None


def test_resume_salta_1_2_3_y_siempre_ejecuta_package(tmp_path: Path) -> None:
    config = _config(tmp_path, resume=True)
    work = Path(config.output_dir) / "work"
    _write_chapters(work)
    _write_charts(work)
    _write_visuals(work)

    recorder = _RecordingRunners()
    report = run_pipeline(
        config,
        runners=recorder.as_stage_runners(config.output_dir),
        clock_fn=_FakeClock(),
    )

    assert report.succeeded is True
    assert recorder.order == ["package"]
    statuses = {stage.stage: stage.status for stage in report.stages}
    assert statuses == {
        "chapterizer": "skipped",
        "charts": "skipped",
        "visuals": "skipped",
        "package": "executed",
    }


def test_resume_reejecuta_si_json_corrupto(tmp_path: Path) -> None:
    config = _config(tmp_path, resume=True)
    work = Path(config.output_dir) / "work"
    work.mkdir(parents=True, exist_ok=True)
    (work / "chapters.json").write_text("{no-json", encoding="utf-8")
    _write_charts(work)
    _write_visuals(work)

    recorder = _RecordingRunners()
    report = run_pipeline(
        config,
        runners=recorder.as_stage_runners(config.output_dir),
        clock_fn=_FakeClock(),
    )

    assert report.succeeded is True
    assert "chapterizer" in recorder.order
    assert recorder.order[0] == "chapterizer"
    assert "package" in recorder.order


def test_resume_reejecuta_si_cambia_publish_date(tmp_path: Path) -> None:
    config = _config(tmp_path, resume=True, publish_date=date(2025, 12, 1))
    work = Path(config.output_dir) / "work"
    _write_chapters(work)
    _write_charts(work, publish_date=date(2025, 11, 25))
    _write_visuals(work)

    recorder = _RecordingRunners()
    report = run_pipeline(
        config,
        runners=recorder.as_stage_runners(config.output_dir),
        clock_fn=_FakeClock(),
    )

    assert report.succeeded is True
    assert "charts" in recorder.order
    assert recorder.calls["charts"][recorder.calls["charts"].index("--publish-date") + 1] == (
        "2025-12-01"
    )


def test_resume_reejecuta_si_cambia_portrait_layout(tmp_path: Path) -> None:
    config = _config(tmp_path, resume=True, portrait_layout="sidebar")
    work = Path(config.output_dir) / "work"
    _write_chapters(work)
    _write_charts(work)
    _write_visuals(work, portrait_layout="contain")

    recorder = _RecordingRunners()
    report = run_pipeline(
        config,
        runners=recorder.as_stage_runners(config.output_dir),
        clock_fn=_FakeClock(),
    )

    assert report.succeeded is True
    assert "visuals" in recorder.order
    visuals_argv = recorder.calls["visuals"]
    assert visuals_argv[visuals_argv.index("--portrait-layout") + 1] == "sidebar"


def test_resume_reejecuta_si_falta_html_de_chart(tmp_path: Path) -> None:
    config = _config(tmp_path, resume=True)
    work = Path(config.output_dir) / "work"
    _write_chapters(work)
    _write_charts(work)
    _write_visuals(work)
    html = work / "charts" / "ch00_cue000_00.html"
    html.unlink()

    recorder = _RecordingRunners()
    report = run_pipeline(
        config,
        runners=recorder.as_stage_runners(config.output_dir),
        clock_fn=_FakeClock(),
    )

    assert report.succeeded is True
    assert "charts" in recorder.order


def test_resume_reejecuta_si_falta_imagen_verified_asset(tmp_path: Path) -> None:
    config = _config(tmp_path, resume=True)
    work = Path(config.output_dir) / "work"
    _write_chapters(work)
    _write_charts(work)
    _write_visuals(work)
    image = work / "assets" / "images" / "gobierno.jpg"
    image.unlink()

    recorder = _RecordingRunners()
    report = run_pipeline(
        config,
        runners=recorder.as_stage_runners(config.output_dir),
        clock_fn=_FakeClock(),
    )

    assert report.succeeded is True
    assert "visuals" in recorder.order


def test_fail_fast_en_charts_no_corre_visuals_ni_package(tmp_path: Path) -> None:
    config = _config(tmp_path)
    recorder = _RecordingRunners(fail_at="charts")

    report = run_pipeline(
        config,
        runners=recorder.as_stage_runners(config.output_dir),
        clock_fn=_FakeClock(),
    )

    assert report.succeeded is False
    assert recorder.order == ["chapterizer", "charts"]
    assert "visuals" not in recorder.order
    assert "package" not in recorder.order
    failed = report.stages[-1]
    assert failed.stage == "charts"
    assert failed.status == "failed"
    assert failed.error_message is not None
    assert "falló a propósito" in failed.error_message

    report_path = Path(config.output_dir) / "pipeline_report.json"
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["succeeded"] is False
    assert payload["stages"][-1]["status"] == "failed"
    assert payload["deck_html_path"] is None


def test_fail_fast_por_excepcion_del_runner(tmp_path: Path) -> None:
    config = _config(tmp_path)

    def boom(_argv: list[str]) -> int:
        print("stderr previo", file=__import__("sys").stderr)
        raise RuntimeError("explosión controlada")

    runners = StageRunners(
        chapterizer=boom,
        charts=lambda argv: 0,
        visuals=lambda argv: 0,
        package=lambda argv: 0,
    )
    completed: list[str] = []
    report = run_pipeline(
        config,
        runners=runners,
        clock_fn=_FakeClock(),
        on_stage_complete=lambda result: completed.append(result.status),
    )
    assert report.succeeded is False
    assert report.stages[0].status == "failed"
    assert "explosión controlada" in (report.stages[0].error_message or "")
    assert "stderr previo" in (report.stages[0].error_message or "")
    assert completed == ["failed"]


def test_fail_sin_stderr_usa_codigo(tmp_path: Path) -> None:
    config = _config(tmp_path)
    runners = StageRunners(
        chapterizer=lambda argv: 7,
        charts=lambda argv: 0,
        visuals=lambda argv: 0,
        package=lambda argv: 0,
    )
    report = run_pipeline(config, runners=runners, clock_fn=_FakeClock())
    assert report.succeeded is False
    assert "código de salida 7" in (report.stages[0].error_message or "")


def test_default_stage_runners_exponen_cuatro_callables(tmp_path: Path) -> None:
    from tigani_broadcast.pipeline.runner import default_stage_runners

    runners = default_stage_runners()
    assert callable(runners.chapterizer)
    assert callable(runners.charts)
    assert callable(runners.visuals)
    assert callable(runners.package)
    code = runners.chapterizer(
        [
            "--input",
            str(tmp_path / "missing.txt"),
            "--output",
            str(tmp_path / "out.json"),
        ]
    )
    assert code != 0


def test_resume_sin_archivos_intermedios_ejecuta_todo(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        resume=True,
        video_url=None,
        no_llm_visuals=False,
        include_chapter_covers=True,
        include_errors=False,
        cache_dir=None,
        portrait_layout="sidebar",
    )
    recorder = _RecordingRunners()
    completed: list[str] = []
    report = run_pipeline(
        config,
        runners=recorder.as_stage_runners(config.output_dir),
        clock_fn=_FakeClock(),
        on_stage_complete=lambda result: completed.append(f"{result.stage}:{result.status}"),
    )
    assert report.succeeded is True
    assert recorder.order == ["chapterizer", "charts", "visuals", "package"]
    assert "--video-url" not in recorder.calls["package"]
    assert "--no-chapter-covers" not in recorder.calls["package"]
    assert "--include-errors" not in recorder.calls["package"]
    assert "--no-llm" not in recorder.calls["visuals"]
    assert "--cache-dir" not in recorder.calls["charts"]
    assert completed[0].endswith(":executed")


def test_resume_rechaza_html_path_vacio_en_charts(tmp_path: Path) -> None:
    config = _config(tmp_path, resume=True)
    work = Path(config.output_dir) / "work"
    _write_chapters(work)
    _write_charts(work)
    _write_visuals(work)
    payload = json.loads((work / "charts.json").read_text(encoding="utf-8"))
    payload["items"][0]["html_path"] = None
    (work / "charts.json").write_text(json.dumps(payload), encoding="utf-8")

    recorder = _RecordingRunners()
    report = run_pipeline(
        config,
        runners=recorder.as_stage_runners(config.output_dir),
        clock_fn=_FakeClock(),
    )
    assert report.succeeded is True
    assert "charts" in recorder.order

    (work / "charts.json").write_text('{"publish_date": "no-date", "items": []}', encoding="utf-8")
    recorder2 = _RecordingRunners()
    report2 = run_pipeline(
        config,
        runners=recorder2.as_stage_runners(config.output_dir),
        clock_fn=_FakeClock(),
    )
    assert report2.succeeded is True
    assert "charts" in recorder2.order


def test_resume_rechaza_assets_sin_html_o_imagen(tmp_path: Path) -> None:
    config = _config(tmp_path, resume=True)
    work = Path(config.output_dir) / "work"
    _write_chapters(work)
    _write_charts(work)
    _write_visuals(work)
    html = work / "assets" / "ch00_cue000_00.html"
    html.unlink()

    recorder = _RecordingRunners()
    report = run_pipeline(
        config,
        runners=recorder.as_stage_runners(config.output_dir),
        clock_fn=_FakeClock(),
    )
    assert report.succeeded is True
    assert "visuals" in recorder.order

    _write_visuals(work)
    payload = json.loads((work / "assets.json").read_text(encoding="utf-8"))
    payload["items"][0]["html_path"] = "   "
    (work / "assets.json").write_text(json.dumps(payload), encoding="utf-8")
    recorder2 = _RecordingRunners()
    report2 = run_pipeline(
        config,
        runners=recorder2.as_stage_runners(config.output_dir),
        clock_fn=_FakeClock(),
    )
    assert report2.succeeded is True
    assert "visuals" in recorder2.order


def test_resume_on_stage_complete_en_skip(tmp_path: Path) -> None:
    config = _config(tmp_path, resume=True)
    work = Path(config.output_dir) / "work"
    _write_chapters(work)
    _write_charts(work)
    _write_visuals(work)
    recorder = _RecordingRunners()
    skipped: list[str] = []
    run_pipeline(
        config,
        runners=recorder.as_stage_runners(config.output_dir),
        clock_fn=_FakeClock(),
        on_stage_complete=lambda result: skipped.append(result.status),
    )
    assert skipped.count("skipped") == 3
    assert skipped[-1] == "executed"
