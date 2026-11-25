"""Contratos Pydantic del orquestador: casos felices y rechazos fail-closed."""

from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from tigani_broadcast.pipeline.models import PipelineConfig, PipelineReport, StageResult


def _config(**overrides: object) -> PipelineConfig:
    payload: dict[str, object] = {
        "transcript_path": Path("data/video.txt"),
        "publish_date": date(2025, 11, 25),
        "video_title": "Episodio piloto",
        "output_dir": Path("out/run"),
    }
    payload.update(overrides)
    return PipelineConfig.model_validate(payload)


def _stage(**overrides: object) -> StageResult:
    payload: dict[str, object] = {
        "stage": "chapterizer",
        "status": "executed",
        "duration_seconds": 1.5,
        "output_path": "work/chapters.json",
    }
    payload.update(overrides)
    return StageResult.model_validate(payload)


def _report(**overrides: object) -> PipelineReport:
    payload: dict[str, object] = {
        "transcript_path": "data/video.txt",
        "publish_date": date(2025, 11, 25),
        "video_title": "Episodio piloto",
        "output_dir": "out/run",
        "resume": False,
        "succeeded": True,
        "total_duration_seconds": 3.0,
        "stages": [_stage()],
    }
    payload.update(overrides)
    return PipelineReport.model_validate(payload)


def test_pipeline_config_acepta_defaults() -> None:
    config = _config()
    assert config.resume is False
    assert config.no_llm_visuals is False
    assert config.portrait_layout == "sidebar"
    assert config.include_chapter_covers is True
    assert config.include_errors is False
    assert config.cache_dir is None
    assert config.video_url is None


def test_pipeline_config_rechaza_titulo_vacio() -> None:
    with pytest.raises(ValidationError):
        _config(video_title="")


def test_pipeline_config_rechaza_extra() -> None:
    with pytest.raises(ValidationError):
        PipelineConfig.model_validate({**_config().model_dump(), "extra": True})


def test_pipeline_config_rechaza_portrait_layout_invalido() -> None:
    with pytest.raises(ValidationError):
        _config(portrait_layout="zoom")


@pytest.mark.parametrize(
    "status,error_message",
    [
        ("failed", None),
        ("failed", ""),
        ("failed", "   "),
        ("executed", "boom"),
        ("skipped", "boom"),
    ],
)
def test_stage_result_fail_closed(status: str, error_message: str | None) -> None:
    with pytest.raises(ValidationError):
        _stage(status=status, error_message=error_message)


def test_stage_result_failed_ok() -> None:
    result = _stage(status="failed", error_message="timeout", output_path=None)
    assert result.status == "failed"
    assert result.error_message == "timeout"


def test_stage_result_rechaza_duration_negativa() -> None:
    with pytest.raises(ValidationError):
        _stage(duration_seconds=-0.1)


def test_pipeline_report_acepta_rutas_finales() -> None:
    report = _report(
        deck_html_path="package/deck.html",
        youtube_description_path="package/youtube_description.txt",
        social_post_path="package/social_post.txt",
    )
    assert report.succeeded is True
    assert report.deck_html_path is not None


def test_pipeline_report_rechaza_duration_negativa() -> None:
    with pytest.raises(ValidationError):
        _report(total_duration_seconds=-1.0)


def test_pipeline_report_rechaza_extra() -> None:
    with pytest.raises(ValidationError):
        PipelineReport.model_validate({**_report().model_dump(), "extra": 1})
