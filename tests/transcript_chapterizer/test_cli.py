"""CLI offline: el motor fake evita red, tokens y variables de entorno."""

import json
import runpy
from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace

import pytest

from tigani_broadcast.transcript_chapterizer.cli import (
    EXIT_ERROR,
    EXIT_OK,
    ModelConfigError,
    build_agno_model_from_env,
    main,
)
from tigani_broadcast.transcript_chapterizer.models import (
    Chapter,
    ChapterizedTranscript,
    Cue,
    HardDataMention,
    VisualSubjectMention,
)
from tigani_broadcast.transcript_chapterizer.render import render_json, render_markdown

FIXTURE = Path(__file__).parents[1] / "fixtures" / "transcripcion_breve.txt"


class _Recorder:
    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.id = kwargs["id"]
        self.options = kwargs.get("options")
        if "temperature" in kwargs:
            self.temperature = kwargs["temperature"]


def _chapter(
    cues: Sequence[Cue],
    start: int,
    end: int,
    *,
    title: str,
    lower: str,
    summary: str,
    hard_data: list[HardDataMention] | None = None,
    visual_subjects: list[VisualSubjectMention] | None = None,
) -> Chapter:
    return Chapter(
        start_cue_index=start,
        end_cue_index=end,
        start_time=cues[start].timestamp,
        end_time=cues[end].timestamp,
        title=title,
        summary=summary,
        suggested_lower_third=lower,
        hard_data=hard_data or [],
        visual_subjects=visual_subjects or [],
    )


def _paquete(cues: Sequence[Cue]) -> ChapterizedTranscript:
    return ChapterizedTranscript(
        chapters=[
            _chapter(
                cues,
                0,
                1,
                title="Intro",
                lower="Arranca el análisis de la coyuntura.",
                summary="Apertura del día.",
            ),
            _chapter(
                cues,
                2,
                4,
                title="La inflación de marzo",
                lower="El índice fue del 4,2 por ciento.",
                summary="El Banco Central publicó el dato.",
                hard_data=[
                    HardDataMention(
                        cue_index=2,
                        timestamp=cues[2].timestamp,
                        indicator_label="inflación",
                        raw_value_text="4,2 por ciento",
                        time_reference="marzo",
                    )
                ],
                visual_subjects=[
                    VisualSubjectMention(
                        cue_index=4,
                        timestamp=cues[4].timestamp,
                        subject_label="Banco Central",
                        asset_kind="conceptual_illustration",
                        context_text="publicó el dato",
                    )
                ],
            ),
            _chapter(
                cues,
                5,
                5,
                title="Cierre",
                lower="En el próximo tramo, las reservas.",
                summary="El tramo siguiente mira las reservas.",
            ),
        ]
    )


class _Motor:
    def __init__(self, broken: ChapterizedTranscript | None = None) -> None:
        self.broken = broken
        self.cues: list[Cue] = []

    def chapterize(self, cues: Sequence[Cue]) -> ChapterizedTranscript:
        self.cues = list(cues)
        if self.broken is not None:
            return self.broken
        return _paquete(self.cues)


def _argv(tmp_path: Path, *, markdown: Path | None = None, input_path: Path = FIXTURE) -> list[str]:
    args = ["--input", str(input_path), "--output", str(tmp_path / "chapters.json")]
    if markdown is not None:
        args.extend(["--markdown", str(markdown)])
    return args


def test_escribe_json_y_markdown_con_motor_fake(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def _no_env(environ: object = None) -> None:
        raise AssertionError(environ)

    monkeypatch.setattr(
        "tigani_broadcast.transcript_chapterizer.cli.build_agno_model_from_env",
        _no_env,
    )
    markdown = tmp_path / "chapters.md"
    motor = _Motor()

    code = main(_argv(tmp_path, markdown=markdown), engine=motor)

    captured = capsys.readouterr()
    written = (tmp_path / "chapters.json").read_text(encoding="utf-8")
    assert code == EXIT_OK
    assert captured.err == ""
    assert captured.out == ""
    assert len(motor.cues) == 6
    assert motor.cues[0].timestamp == "00:00:01"
    assert written == render_json(_paquete(motor.cues))
    assert "día" in written
    assert json.loads(written)["chapters"][1]["hard_data"][0]["raw_value_text"] == "4,2 por ciento"
    assert markdown.read_text(encoding="utf-8") == render_markdown(_paquete(motor.cues))
    escaleta = markdown.read_text(encoding="utf-8")
    assert "[00:00:14 - 00:00:21]" in escaleta
    assert "[00:00:14] cue 2: inflación: 4,2 por ciento (marzo)" in escaleta


def test_archivo_inexistente(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    missing = tmp_path / "no-esta.txt"

    code = main(_argv(tmp_path, input_path=missing), engine=_Motor())

    assert code == EXIT_ERROR
    assert "no se pudo leer el archivo" in capsys.readouterr().err
    assert not (tmp_path / "chapters.json").exists()


def test_archivo_mal_formateado(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bad = tmp_path / "roto.txt"
    bad.write_text("sin corchetes\n", encoding="utf-8")

    code = main(_argv(tmp_path, input_path=bad), engine=_Motor())

    err = capsys.readouterr().err
    assert code == EXIT_ERROR
    assert "línea 1" in err
    assert "formato inválido" in err


def test_fallo_de_validacion(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cues = [
        Cue(cue_index=0, timestamp="00:00:01", text="solo una línea para armar el objeto"),
    ]
    broken = ChapterizedTranscript(
        chapters=[
            _chapter(
                cues,
                0,
                0,
                title="Incompleto",
                lower="No alcanza.",
                summary="No cubre la transcripción.",
            )
        ]
    )

    code = main(_argv(tmp_path), engine=_Motor(broken))

    assert code == EXIT_ERROR
    assert "tiene que terminar en la cue" in capsys.readouterr().err


def test_configuracion_faltante(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("TIGANI_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("TIGANI_LLM_MODEL", raising=False)

    code = main(_argv(tmp_path))

    assert code == EXIT_ERROR
    assert "TIGANI_LLM_PROVIDER" in capsys.readouterr().err


def test_proveedor_invalido(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("TIGANI_LLM_PROVIDER", "groq")
    monkeypatch.setenv("TIGANI_LLM_MODEL", "otro")

    code = main(_argv(tmp_path))

    err = capsys.readouterr().err
    assert code == EXIT_ERROR
    assert "proveedor no soportado: groq" in err
    assert "ollama" in err


def test_wrapper_que_no_carga(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(name: str) -> object:
        raise ImportError(f"no está instalado {name}")

    monkeypatch.setattr(
        "tigani_broadcast.transcript_chapterizer.cli.importlib.import_module",
        _boom,
    )

    with pytest.raises(ModelConfigError, match="no se pudo cargar el wrapper de Agno para ollama"):
        build_agno_model_from_env({"TIGANI_LLM_PROVIDER": "ollama", "TIGANI_LLM_MODEL": "llama3.1"})


@pytest.mark.parametrize(
    ("provider", "module_name", "class_name", "uses_options"),
    [
        ("openai", "agno.models.openai", "OpenAIChat", False),
        ("OpenAI", "agno.models.openai", "OpenAIChat", False),
        ("anthropic", "agno.models.anthropic", "Claude", False),
        ("google", "agno.models.google", "Gemini", False),
        ("ollama", "agno.models.ollama", "Ollama", True),
    ],
)
def test_fabrica_fija_temperatura_cero(
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    module_name: str,
    class_name: str,
    uses_options: bool,
) -> None:
    seen: list[str] = []

    def _load(name: str) -> SimpleNamespace:
        seen.append(name)
        return SimpleNamespace(**{class_name: _Recorder})

    monkeypatch.setattr(
        "tigani_broadcast.transcript_chapterizer.cli.importlib.import_module",
        _load,
    )

    model = build_agno_model_from_env(
        {"TIGANI_LLM_PROVIDER": provider, "TIGANI_LLM_MODEL": " modelo-x "}
    )

    assert seen == [module_name]
    assert model.id == "modelo-x"
    assert model.temperature == 0.0
    if uses_options:
        assert model.options == {"temperature": 0.0}
    else:
        assert model.kwargs["temperature"] == 0.0


def test_el_modulo_delega_en_main(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("tigani_broadcast.transcript_chapterizer.cli.main", lambda: 7)

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_module("tigani_broadcast.transcript_chapterizer", run_name="__main__")

    assert exc_info.value.code == 7


def test_falta_solo_el_id_del_modelo() -> None:
    with pytest.raises(ModelConfigError, match="TIGANI_LLM_MODEL"):
        build_agno_model_from_env({"TIGANI_LLM_PROVIDER": "openai", "TIGANI_LLM_MODEL": "  "})
