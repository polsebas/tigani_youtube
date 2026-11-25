"""CLI E2E offline: paquete completo, flags y errores."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from tigani_broadcast.broadcast_package_builder.cli import EXIT_ERROR, EXIT_OK, run_cli
from tigani_broadcast.official_data_charts.models import ChartsPackage
from tigani_broadcast.visual_assets_fetcher.models import VisualAssetsPackage

from .conftest import make_chapters, make_chart, make_visual


def _write_inputs(
    tmp_path: Path,
    *,
    include_error_items: bool = False,
) -> tuple[Path, Path, Path]:
    chapters = make_chapters()
    chart_items = [make_chart(tmp_path)]
    visual_items = [make_visual(tmp_path)]
    if include_error_items:
        chart_items.append(
            make_chart(
                tmp_path,
                cue_index=15,
                timestamp="00:02:00",
                indicator_label="Reservas",
                resolution_status="fetch_error",
                filename="ch00_cue015_err.html",
                error_message="BCRA 503",
            )
        )
        visual_items.append(
            make_visual(
                tmp_path,
                cue_index=16,
                timestamp="00:02:10",
                subject_label="mercado",
                status="fetch_error",
                filename="ch00_cue016_err.html",
                error_message="sin licencia",
            )
        )

    charts = ChartsPackage(publish_date=date(2025, 11, 25), items=chart_items)
    assets = VisualAssetsPackage(items=visual_items)

    chapters_path = tmp_path / "chapters.json"
    charts_path = tmp_path / "charts.json"
    assets_path = tmp_path / "assets.json"
    chapters_path.write_text(
        chapters.model_dump_json(indent=2),
        encoding="utf-8",
    )
    charts_path.write_text(charts.model_dump_json(indent=2), encoding="utf-8")
    assets_path.write_text(assets.model_dump_json(indent=2), encoding="utf-8")
    return chapters_path, charts_path, assets_path


def test_cli_e2e_paquete_completo(tmp_path: Path) -> None:
    chapters_path, charts_path, assets_path = _write_inputs(tmp_path)
    output_dir = tmp_path / "package"

    code = run_cli(
        [
            "--chapters",
            str(chapters_path),
            "--charts",
            str(charts_path),
            "--assets",
            str(assets_path),
            "--output-dir",
            str(output_dir),
            "--video-title",
            "Inflación, reservas y deuda",
            "--video-url",
            "https://youtu.be/kP_G1sAStQE",
        ]
    )

    assert code == EXIT_OK
    assert (output_dir / "deck.html").is_file()
    assert (output_dir / "package.json").is_file()
    assert (output_dir / "rundown.md").is_file()
    assert (output_dir / "youtube_description.txt").is_file()
    assert (output_dir / "social_post.txt").is_file()
    assert (output_dir / "slides" / "chapters" / "ch00_cover.html").is_file()
    assert (output_dir / "slides" / "chapters" / "ch01_cover.html").is_file()
    assert (output_dir / "slides" / "charts" / "ch00_cue014_00.html").is_file()
    assert (output_dir / "slides" / "visuals" / "ch00_cue014_00.html").is_file()
    assert (output_dir / "slides" / "visuals" / "images" / "gobierno.jpg").is_file()

    package = json.loads((output_dir / "package.json").read_text(encoding="utf-8"))
    assert package["video_title"] == "Inflación, reservas y deuda"
    assert package["video_url"] == "https://youtu.be/kP_G1sAStQE"
    assert package["include_chapter_covers"] is True
    assert package["include_errors"] is False

    yt = (output_dir / "youtube_description.txt").read_text(encoding="utf-8")
    assert yt.splitlines()[0] == "Inflación, reservas y deuda"
    assert "00:00" in yt
    social = (output_dir / "social_post.txt").read_text(encoding="utf-8")
    assert "https://youtu.be/kP_G1sAStQE" in social
    deck = (output_dir / "deck.html").read_text(encoding="utf-8")
    assert "slides/" in deck
    assert "cdn." not in deck.lower()


def test_cli_no_chapter_covers(tmp_path: Path) -> None:
    chapters_path, charts_path, assets_path = _write_inputs(tmp_path)
    output_dir = tmp_path / "package"

    code = run_cli(
        [
            "--chapters",
            str(chapters_path),
            "--charts",
            str(charts_path),
            "--assets",
            str(assets_path),
            "--output-dir",
            str(output_dir),
            "--video-title",
            "Sin covers",
            "--no-chapter-covers",
        ]
    )

    assert code == EXIT_OK
    package = json.loads((output_dir / "package.json").read_text(encoding="utf-8"))
    assert package["include_chapter_covers"] is False
    assert all(slide["kind"] != "chapter_cover" for slide in package["slides"])
    assert not (output_dir / "slides" / "chapters" / "ch00_cover.html").exists()


def test_cli_include_errors(tmp_path: Path) -> None:
    chapters_path, charts_path, assets_path = _write_inputs(tmp_path, include_error_items=True)
    output_dir = tmp_path / "package"

    code = run_cli(
        [
            "--chapters",
            str(chapters_path),
            "--charts",
            str(charts_path),
            "--assets",
            str(assets_path),
            "--output-dir",
            str(output_dir),
            "--video-title",
            "Con errores",
            "--include-errors",
        ]
    )

    assert code == EXIT_OK
    package = json.loads((output_dir / "package.json").read_text(encoding="utf-8"))
    assert package["include_errors"] is True
    assert package["excluded_errors"] == []
    statuses = {slide["status"] for slide in package["slides"]}
    assert "fetch_error" in statuses
    assert (output_dir / "slides" / "charts" / "ch00_cue015_err.html").is_file()


def test_cli_archivo_faltante(tmp_path: Path, capsys) -> None:
    code = run_cli(
        [
            "--chapters",
            str(tmp_path / "missing.json"),
            "--charts",
            str(tmp_path / "missing_charts.json"),
            "--assets",
            str(tmp_path / "missing_assets.json"),
            "--output-dir",
            str(tmp_path / "out"),
            "--video-title",
            "X",
        ]
    )
    assert code == EXIT_ERROR
    err = capsys.readouterr().err
    assert "no existe" in err


def test_cli_json_invalido(tmp_path: Path, capsys) -> None:
    chapters_path = tmp_path / "chapters.json"
    charts_path = tmp_path / "charts.json"
    assets_path = tmp_path / "assets.json"
    chapters_path.write_text("{no-json", encoding="utf-8")
    charts_path.write_text("{}", encoding="utf-8")
    assets_path.write_text("{}", encoding="utf-8")

    code = run_cli(
        [
            "--chapters",
            str(chapters_path),
            "--charts",
            str(charts_path),
            "--assets",
            str(assets_path),
            "--output-dir",
            str(tmp_path / "out"),
            "--video-title",
            "X",
        ]
    )
    assert code == EXIT_ERROR
    assert "inválido" in capsys.readouterr().err


def test_cli_schema_invalido_chapters(tmp_path: Path, capsys) -> None:
    chapters_path = tmp_path / "chapters.json"
    charts_path = tmp_path / "charts.json"
    assets_path = tmp_path / "assets.json"
    chapters_path.write_text('{"chapters": []}', encoding="utf-8")
    charts_path.write_text(
        '{"publish_date": "2025-11-25", "items": []}',
        encoding="utf-8",
    )
    assets_path.write_text('{"items": []}', encoding="utf-8")

    code = run_cli(
        [
            "--chapters",
            str(chapters_path),
            "--charts",
            str(charts_path),
            "--assets",
            str(assets_path),
            "--output-dir",
            str(tmp_path / "out"),
            "--video-title",
            "X",
        ]
    )
    assert code == EXIT_ERROR
    assert "chapters.json inválido" in capsys.readouterr().err


def test_cli_schema_invalido_charts_y_assets(tmp_path: Path, capsys) -> None:
    chapters_path, _charts_ok, _assets_ok = _write_inputs(tmp_path)
    charts_path = tmp_path / "bad_charts.json"
    assets_path = tmp_path / "bad_assets.json"
    charts_path.write_text('{"publish_date": "no-es-fecha", "items": []}', encoding="utf-8")
    assets_path.write_text('{"items": "no-lista"}', encoding="utf-8")

    code = run_cli(
        [
            "--chapters",
            str(chapters_path),
            "--charts",
            str(charts_path),
            "--assets",
            str(assets_path),
            "--output-dir",
            str(tmp_path / "out"),
            "--video-title",
            "X",
        ]
    )
    assert code == EXIT_ERROR
    assert "charts.json inválido" in capsys.readouterr().err

    charts_ok = tmp_path / "charts.json"
    code_assets = run_cli(
        [
            "--chapters",
            str(chapters_path),
            "--charts",
            str(charts_ok),
            "--assets",
            str(assets_path),
            "--output-dir",
            str(tmp_path / "out2"),
            "--video-title",
            "X",
        ]
    )
    assert code_assets == EXIT_ERROR
    assert "assets.json inválido" in capsys.readouterr().err


def test_main_y_dunder_main_exportan(tmp_path: Path) -> None:
    from tigani_broadcast.broadcast_package_builder import __main__ as mod
    from tigani_broadcast.broadcast_package_builder.cli import main

    assert callable(main)
    assert callable(mod.main)
    assert main is mod.main
    assert (
        main(
            [
                "--chapters",
                str(tmp_path / "missing.json"),
                "--charts",
                str(tmp_path / "missing.json"),
                "--assets",
                str(tmp_path / "missing.json"),
                "--output-dir",
                str(tmp_path / "out"),
                "--video-title",
                "X",
            ]
        )
        == EXIT_ERROR
    )


def test_cli_validation_error_html_faltante(tmp_path: Path, capsys) -> None:
    chapters_path, charts_path, assets_path = _write_inputs(tmp_path)
    charts_payload = json.loads(charts_path.read_text(encoding="utf-8"))
    html_path = Path(charts_payload["items"][0]["html_path"])
    html_path.unlink()

    code = run_cli(
        [
            "--chapters",
            str(chapters_path),
            "--charts",
            str(charts_path),
            "--assets",
            str(assets_path),
            "--output-dir",
            str(tmp_path / "out"),
            "--video-title",
            "X",
        ]
    )
    assert code == EXIT_ERROR
    assert "falta el HTML" in capsys.readouterr().err
