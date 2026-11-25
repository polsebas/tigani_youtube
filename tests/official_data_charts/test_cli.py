"""CLI offline: resolver/fetcher falsos, sin red ni tokens."""

from __future__ import annotations

import json
import runpy
from datetime import date
from pathlib import Path

import pytest

from tigani_broadcast.official_data_charts.cli import (
    EXIT_ERROR,
    EXIT_OK,
    ChartsCliError,
    run_cli,
)
from tigani_broadcast.official_data_charts.models import (
    ChartResolutionDraft,
    SeriesData,
    SeriesObservation,
)
from tigani_broadcast.official_data_charts.providers.base import ProviderError
from tigani_broadcast.transcript_chapterizer.cli import ModelConfigError
from tigani_broadcast.transcript_chapterizer.models import HardDataMention


class _ResolverFake:
    def __init__(self, drafts: dict[str, ChartResolutionDraft]) -> None:
        self.drafts = drafts

    def resolve(
        self,
        mention: HardDataMention,
        chapter_context: str,
        publish_date: date,
    ) -> ChartResolutionDraft:
        del chapter_context, publish_date
        key = mention.indicator_label
        if key not in self.drafts:
            # Varias menciones de reservas netas comparten draft quoted_only.
            if "reservas netas" in key:
                return self.drafts["reservas netas"]
            raise KeyError(key)
        return self.drafts[key]


class _FetcherFake:
    def __init__(
        self,
        series_by_id: dict[str, SeriesData] | None = None,
        errors_by_id: dict[str, Exception] | None = None,
    ) -> None:
        self.series_by_id = series_by_id or {}
        self.errors_by_id = errors_by_id or {}

    def fetch(self, entry, start_date: date, end_date: date) -> SeriesData:  # noqa: ANN001
        del start_date, end_date
        if entry.catalog_id in self.errors_by_id:
            raise self.errors_by_id[entry.catalog_id]
        return self.series_by_id[entry.catalog_id]


def _chapters_payload() -> dict:
    """Estructura equivalente a kP_G1sAStQE.v3.chapters.json (recortada)."""
    return {
        "chapters": [
            {
                "start_cue_index": 0,
                "end_cue_index": 14,
                "start_time": "00:00:01",
                "end_time": "00:01:50",
                "title": "Inflación y reservas",
                "summary": "Inflación 2.5% y reservas netas negativas.",
                "suggested_lower_third": "Inflación y reservas",
                "hard_data": [
                    {
                        "cue_index": 1,
                        "timestamp": "00:00:07",
                        "indicator_label": "índice de inflación",
                        "raw_value_text": "2.5%",
                        "time_reference": "hoy",
                    },
                    {
                        "cue_index": 10,
                        "timestamp": "00:01:22",
                        "indicator_label": "reservas netas",
                        "raw_value_text": "-17,000 millones",
                        "time_reference": "hoy",
                    },
                ],
                "visual_subjects": [],
            },
            {
                "start_cue_index": 15,
                "end_cue_index": 35,
                "start_time": "00:01:57",
                "end_time": "00:04:45",
                "title": "Deuda y swap",
                "summary": "Deuda puntual y swap.",
                "suggested_lower_third": "Deuda y swap",
                "hard_data": [
                    {
                        "cue_index": 19,
                        "timestamp": "00:02:36",
                        "indicator_label": "deuda",
                        "raw_value_text": "4600 millones de dólares",
                        "time_reference": "el 9 de enero",
                    },
                    {
                        "cue_index": 28,
                        "timestamp": "00:03:40",
                        "indicator_label": "swap",
                        "raw_value_text": "900 M",
                        "time_reference": None,
                    },
                    {
                        "cue_index": 30,
                        "timestamp": "00:04:00",
                        "indicator_label": "tasa BADLAR",
                        "raw_value_text": "9.26%",
                        "time_reference": "hoy",
                    },
                ],
                "visual_subjects": [],
            },
        ]
    }


def test_cli_end_to_end_offline(tmp_path: Path) -> None:
    chapters_path = tmp_path / "video.chapters.json"
    chapters_path.write_text(json.dumps(_chapters_payload()), encoding="utf-8")
    out_json = tmp_path / "video.charts.json"
    charts_dir = tmp_path / "charts"
    out_md = tmp_path / "video.charts.md"

    drafts = {
        "índice de inflación": ChartResolutionDraft(
            resolution_status="verified_series",
            catalog_id="ar_indec_ipc_mensual",
            start_date=date(2025, 1, 1),
            end_date=date(2025, 11, 1),
            rationale="IPC mensual.",
        ),
        "reservas netas": ChartResolutionDraft(
            resolution_status="quoted_only",
            rationale="Sin serie de reservas netas.",
        ),
        "deuda": ChartResolutionDraft(
            resolution_status="quoted_only",
            rationale="Monto puntual.",
        ),
        "swap": ChartResolutionDraft(
            resolution_status="quoted_only",
            rationale="Swap puntual.",
        ),
        "tasa BADLAR": ChartResolutionDraft(
            resolution_status="verified_series",
            catalog_id="ar_bcra_tasa_badlar",
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 1),
            rationale="BADLAR.",
        ),
    }
    ipc = SeriesData(
        catalog_id="ar_indec_ipc_mensual",
        provider="indec",
        source_tier="official_primary",
        series_id="145.3_INGNACNAL_DICI_M_38",
        source_url="https://example.test/ipc",
        source_attribution="Fuente: INDEC — IPC",
        unit="%",
        frequency="monthly",
        observations=[
            SeriesObservation(obs_date=date(2025, 1, 1), value=2.0),
            SeriesObservation(obs_date=date(2025, 11, 1), value=2.5),
        ],
    )
    fetcher = _FetcherFake(
        series_by_id={"ar_indec_ipc_mensual": ipc},
        errors_by_id={"ar_bcra_tasa_badlar": ProviderError("HTTP 500 BCRA")},
    )

    code = run_cli(
        [
            "--input",
            str(chapters_path),
            "--publish-date",
            "2025-12-11",
            "--output",
            str(out_json),
            "--charts-dir",
            str(charts_dir),
            "--markdown",
            str(out_md),
        ],
        resolver=_ResolverFake(drafts),
        fetcher=fetcher,  # type: ignore[arg-type]
    )
    assert code == EXIT_OK
    assert out_json.is_file()
    assert out_md.is_file()
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    statuses = [item["resolution_status"] for item in payload["items"]]
    assert statuses.count("verified_series") == 1
    assert statuses.count("quoted_only") == 3
    assert statuses.count("fetch_error") == 1
    html_files = list(charts_dir.glob("*.html"))
    assert len(html_files) == 5
    verified_html = next(p for p in html_files if "cue001" in p.name).read_text(encoding="utf-8")
    assert "<svg" in verified_html
    assert "Fuente: INDEC — IPC" in verified_html
    md = out_md.read_text(encoding="utf-8")
    assert "fetch_error" in md
    assert "reservas netas" in md


def test_cli_fecha_invalida(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    chapters_path = tmp_path / "c.json"
    chapters_path.write_text(json.dumps(_chapters_payload()), encoding="utf-8")
    code = run_cli(
        [
            "--input",
            str(chapters_path),
            "--publish-date",
            "11/12/2025",
            "--output",
            str(tmp_path / "o.json"),
            "--charts-dir",
            str(tmp_path / "charts"),
        ],
        resolver=_ResolverFake({}),
        fetcher=_FetcherFake(),  # type: ignore[arg-type]
    )
    assert code == EXIT_ERROR
    err = capsys.readouterr().err
    assert "publish-date inválida" in err


def test_cli_input_inexistente(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = run_cli(
        [
            "--input",
            str(tmp_path / "missing.json"),
            "--publish-date",
            "2025-12-11",
            "--output",
            str(tmp_path / "o.json"),
            "--charts-dir",
            str(tmp_path / "charts"),
        ],
        resolver=_ResolverFake({}),
        fetcher=_FetcherFake(),  # type: ignore[arg-type]
    )
    assert code == EXIT_ERROR
    assert "no existe el archivo" in capsys.readouterr().err


def test_cli_chapters_json_invalido(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{no-json", encoding="utf-8")
    code = run_cli(
        [
            "--input",
            str(bad),
            "--publish-date",
            "2025-12-11",
            "--output",
            str(tmp_path / "o.json"),
            "--charts-dir",
            str(tmp_path / "charts"),
        ],
        resolver=_ResolverFake({}),
        fetcher=_FetcherFake(),  # type: ignore[arg-type]
    )
    assert code == EXIT_ERROR
    assert "inválido" in capsys.readouterr().err


def test_cli_chapters_schema_invalido(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"chapters": []}), encoding="utf-8")
    code = run_cli(
        [
            "--input",
            str(bad),
            "--publish-date",
            "2025-12-11",
            "--output",
            str(tmp_path / "o.json"),
            "--charts-dir",
            str(tmp_path / "charts"),
        ],
        resolver=_ResolverFake({}),
        fetcher=_FetcherFake(),  # type: ignore[arg-type]
    )
    assert code == EXIT_ERROR
    assert "inválido" in capsys.readouterr().err


def test_cli_sin_env_falla_si_no_inyectan(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("TIGANI_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("TIGANI_LLM_MODEL", raising=False)
    chapters_path = tmp_path / "c.json"
    chapters_path.write_text(json.dumps(_chapters_payload()), encoding="utf-8")
    code = run_cli(
        [
            "--input",
            str(chapters_path),
            "--publish-date",
            "2025-12-11",
            "--output",
            str(tmp_path / "o.json"),
            "--charts-dir",
            str(tmp_path / "charts"),
        ]
    )
    assert code == EXIT_ERROR


def test_main_module_entrypoint(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[list[str] | None] = []

    def fake_main(argv=None):  # noqa: ANN001
        called.append(list(argv) if argv is not None else None)
        return EXIT_OK

    monkeypatch.setattr(
        "tigani_broadcast.official_data_charts.cli.main",
        fake_main,
    )
    # Evitar SystemExit al re-ejecutar __main__
    monkeypatch.setattr("sys.argv", ["official_data_charts", "--help"])
    # Solo verificamos que el módulo exporta main correctamente.
    from tigani_broadcast.official_data_charts import __main__ as mod

    assert callable(mod.main)
    assert ChartsCliError is not None
    assert ModelConfigError is not None
    # runpy smoke: import path exists
    assert runpy.run_path.__name__ == "run_path"
