"""CLI raíz: E2E offline con runners fake, flags y errores de entrada."""

from __future__ import annotations

from pathlib import Path

import pytest

from tigani_broadcast.pipeline.cli import EXIT_ERROR, EXIT_OK, main, run_cli

from .test_runner import _RecordingRunners


def _argv(tmp_path: Path, *, transcript: Path | None = None, **flags: object) -> list[str]:
    if transcript is None:
        transcript = tmp_path / "transcript.txt"
        transcript.write_text("[00:00:01] Hola\n", encoding="utf-8")
    argv = [
        "run",
        "--transcript",
        str(transcript),
        "--publish-date",
        "2025-11-25",
        "--video-title",
        "Episodio piloto",
        "--output-dir",
        str(tmp_path / "run"),
    ]
    if flags.get("video_url"):
        argv.extend(["--video-url", str(flags["video_url"])])
    if flags.get("resume"):
        argv.append("--resume")
    if flags.get("rerender_only"):
        argv.append("--rerender-only")
    if flags.get("no_llm_visuals"):
        argv.append("--no-llm-visuals")
    if flags.get("portrait_layout"):
        argv.extend(["--portrait-layout", str(flags["portrait_layout"])])
    if flags.get("no_chapter_covers"):
        argv.append("--no-chapter-covers")
    if flags.get("include_errors"):
        argv.append("--include-errors")
    if flags.get("cache_dir"):
        argv.extend(["--cache-dir", str(flags["cache_dir"])])
    return argv


def test_run_cli_e2e_ok_propaga_flags_e_imprime_rutas(tmp_path: Path, capsys) -> None:
    output_dir = tmp_path / "run"
    recorder = _RecordingRunners()
    argv = _argv(
        tmp_path,
        video_url="https://youtu.be/abc",
        resume=False,
        no_llm_visuals=True,
        portrait_layout="contain",
        no_chapter_covers=True,
        include_errors=True,
        cache_dir=tmp_path / "cache",
    )

    code = run_cli(argv, runners=recorder.as_stage_runners(output_dir))
    captured = capsys.readouterr()

    assert code == EXIT_OK
    assert recorder.order == ["chapterizer", "charts", "visuals", "package"]
    assert "[1/4] chapterizer: executed" in captured.out
    assert "[2/4] charts: executed" in captured.out
    assert "[3/4] visuals: executed" in captured.out
    assert "[4/4] package: executed" in captured.out
    assert "Pipeline OK" in captured.out
    assert "deck.html:" in captured.out
    assert "youtube_description.txt:" in captured.out
    assert "social_post.txt:" in captured.out
    assert "pipeline_report.json:" in captured.out
    assert (output_dir / "pipeline_report.json").is_file()

    visuals_argv = recorder.calls["visuals"]
    assert "--no-llm" in visuals_argv
    assert visuals_argv[visuals_argv.index("--portrait-layout") + 1] == "contain"
    assert "--cache-dir" in visuals_argv

    package_argv = recorder.calls["package"]
    assert "--video-url" in package_argv
    assert "https://youtu.be/abc" in package_argv
    assert "--no-chapter-covers" in package_argv
    assert "--include-errors" in package_argv

    charts_argv = recorder.calls["charts"]
    cache_charts = charts_argv[charts_argv.index("--cache-dir") + 1]
    assert cache_charts.endswith("cache/charts") or cache_charts.endswith("cache\\charts")


def test_run_cli_resume_imprime_skipped(tmp_path: Path, capsys) -> None:
    from .test_runner import _write_chapters, _write_charts, _write_visuals

    output_dir = tmp_path / "run"
    work = output_dir / "work"
    _write_chapters(work)
    _write_charts(work)
    _write_visuals(work)

    recorder = _RecordingRunners()
    code = run_cli(
        _argv(tmp_path, resume=True, portrait_layout="contain"),
        runners=recorder.as_stage_runners(output_dir),
    )
    out = capsys.readouterr().out

    assert code == EXIT_OK
    assert recorder.order == ["package"]
    assert "[1/4] chapterizer: skipped (resume)" in out
    assert "[2/4] charts: skipped (resume)" in out
    assert "[3/4] visuals: skipped (resume)" in out
    assert "[4/4] package: executed" in out


def test_run_cli_rerender_only_imprime_skip_y_regenera(tmp_path: Path, capsys) -> None:
    from .test_runner import _write_chapters, _write_charts, _write_visuals

    output_dir = tmp_path / "run"
    work = output_dir / "work"
    _write_chapters(work)
    _write_charts(work)
    _write_visuals(work)

    code = run_cli(
        _argv(tmp_path, rerender_only=True, portrait_layout="contain", no_chapter_covers=True)
    )
    out = capsys.readouterr().out

    assert code == EXIT_OK
    assert "[1/4] chapterizer: skipped (rerender-only)" in out
    assert "[2/4] charts: executed" in out
    assert "[3/4] visuals: executed" in out
    assert "[4/4] package: executed" in out
    assert (output_dir / "package" / "deck.html").is_file()


def test_run_cli_falla_etapa_exit_1(tmp_path: Path, capsys) -> None:
    output_dir = tmp_path / "run"
    recorder = _RecordingRunners(fail_at="charts")
    code = run_cli(_argv(tmp_path), runners=recorder.as_stage_runners(output_dir))
    captured = capsys.readouterr()

    assert code == EXIT_ERROR
    assert recorder.order == ["chapterizer", "charts"]
    assert "[2/4] charts: failed" in captured.out
    assert "Pipeline falló en etapa charts" in captured.err
    assert "pipeline_report.json" in captured.err
    assert (output_dir / "pipeline_report.json").is_file()


def test_run_cli_transcript_inexistente(tmp_path: Path, capsys) -> None:
    recorder = _RecordingRunners()
    code = run_cli(
        _argv(tmp_path, transcript=tmp_path / "no-existe.txt"),
        runners=recorder.as_stage_runners(tmp_path / "run"),
    )
    err = capsys.readouterr().err
    assert code == EXIT_ERROR
    assert "no existe el archivo de transcripción" in err
    assert recorder.order == []


def test_run_cli_publish_date_invalida(tmp_path: Path, capsys) -> None:
    transcript = tmp_path / "transcript.txt"
    transcript.write_text("[00:00:01] Hola\n", encoding="utf-8")
    recorder = _RecordingRunners()
    code = run_cli(
        [
            "run",
            "--transcript",
            str(transcript),
            "--publish-date",
            "25-11-2025",
            "--video-title",
            "X",
            "--output-dir",
            str(tmp_path / "run"),
        ],
        runners=recorder.as_stage_runners(tmp_path / "run"),
    )
    err = capsys.readouterr().err
    assert code == EXIT_ERROR
    assert "publish-date inválida" in err
    assert recorder.order == []


def test_main_levanta_systemexit(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc:
        main(
            [
                "run",
                "--transcript",
                str(tmp_path / "missing.txt"),
                "--publish-date",
                "2025-11-25",
                "--video-title",
                "X",
                "--output-dir",
                str(tmp_path / "run"),
            ]
        )
    assert exc.value.code == EXIT_ERROR


def test_dunder_main_exporta_main() -> None:
    from tigani_broadcast import __main__ as mod

    assert callable(mod.main)
