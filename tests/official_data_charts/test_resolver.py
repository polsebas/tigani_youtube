"""Resolvedor Agno y orquestación a ChartsPackage (100 % offline)."""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from agno.exceptions import CheckTrigger, OutputCheckError
from agno.run.base import RunStatus

from tigani_broadcast.official_data_charts.models import (
    ChartResolutionDraft,
    SeriesData,
    SeriesObservation,
)
from tigani_broadcast.official_data_charts.providers.base import ProviderError
from tigani_broadcast.official_data_charts.resolver import (
    RESOLVER_EXPECTED_OUTPUT,
    RESOLVER_INSTRUCTIONS,
    AgnoMentionResolver,
    ResolutionValidationError,
    _LLMResolutionPayload,
    draft_from_llm_payload,
    format_resolver_prompt,
    resolve_chapters_to_artifacts,
)
from tigani_broadcast.transcript_chapterizer.models import (
    Chapter,
    ChapterizedTranscript,
    HardDataMention,
)


class _Modelo:
    def __init__(self, temperature: float = 0.7) -> None:
        self.temperature = temperature


class _AgentDoble:
    creados: list[_AgentDoble] = []

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.prompts: list[str] = []
        self.content: object = None
        self.contents: list[object] | None = None
        self.status = RunStatus.completed
        self.raise_output_check: OutputCheckError | None = None
        self._call = 0
        _AgentDoble.creados.append(self)

    def run(self, prompt: str, **kwargs: object) -> SimpleNamespace:
        del kwargs
        self.prompts.append(prompt)
        if self.raise_output_check is not None:
            raise self.raise_output_check
        if self.contents is not None:
            content = self.contents[min(self._call, len(self.contents) - 1)]
            self._call += 1
            return SimpleNamespace(content=content, status=self.status)
        return SimpleNamespace(content=self.content, status=self.status)


class _ResolverFake:
    def __init__(
        self,
        drafts: dict[str, ChartResolutionDraft] | None = None,
        *,
        errors: dict[str, Exception] | None = None,
    ) -> None:
        self.drafts = drafts or {}
        self.errors = errors or {}

    def resolve(
        self,
        mention: HardDataMention,
        chapter_context: str,
        publish_date: date,
    ) -> ChartResolutionDraft:
        del chapter_context, publish_date
        if mention.indicator_label in self.errors:
            raise self.errors[mention.indicator_label]
        return self.drafts[mention.indicator_label]


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


def _mention(
    cue_index: int,
    label: str,
    raw: str,
    *,
    timestamp: str = "00:01:00",
    time_reference: str | None = "hoy",
) -> HardDataMention:
    return HardDataMention(
        cue_index=cue_index,
        timestamp=timestamp,
        indicator_label=label,
        raw_value_text=raw,
        time_reference=time_reference,
    )


def _chapter(
    *mentions: HardDataMention,
    title: str = "Coyuntura",
    summary: str = "Resumen del tramo.",
) -> Chapter:
    return Chapter(
        start_cue_index=0,
        end_cue_index=10,
        start_time="00:00:01",
        end_time="00:05:00",
        title=title,
        summary=summary,
        suggested_lower_third=title,
        hard_data=list(mentions),
    )


def test_format_resolver_prompt_incluye_catalogo_y_mencion() -> None:
    mention = _mention(1, "índice de inflación", "2.5%")
    prompt = format_resolver_prompt(mention, "Capítulo 1. Inflación.", date(2025, 12, 11))
    assert "publish_date: 2025-12-11" in prompt
    assert "índice de inflación" in prompt
    assert "ar_indec_ipc_mensual" in prompt
    assert "ar_bcra_reservas_brutas" in prompt


@pytest.mark.parametrize("catalog_id", [None, "", "null", "None", "NULL", "quoted_only"])
def test_payload_nullish_catalog_id_deriva_quoted_only(catalog_id: str | None) -> None:
    payload = _LLMResolutionPayload(
        catalog_id=catalog_id,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 6, 1),
        rationale="Dato puntual sin serie.",
    )
    draft = draft_from_llm_payload(payload, publish_date=date(2025, 12, 11))
    assert draft.resolution_status == "quoted_only"
    assert draft.catalog_id is None
    assert draft.start_date is None
    assert draft.end_date is None


def test_payload_sin_fechas_completa_rango_por_frecuencia() -> None:
    publish = date(2025, 12, 11)
    daily = draft_from_llm_payload(
        _LLMResolutionPayload(
            catalog_id="ar_bcra_reservas_brutas",
            rationale="Reservas brutas BCRA.",
        ),
        publish_date=publish,
    )
    assert daily.resolution_status == "verified_series"
    assert daily.end_date == publish
    assert daily.start_date == publish - timedelta(days=90)

    monthly = draft_from_llm_payload(
        _LLMResolutionPayload(
            catalog_id="ar_indec_ipc_mensual",
            rationale="IPC mensual.",
        ),
        publish_date=publish,
    )
    assert monthly.start_date == publish - timedelta(days=365)
    assert monthly.end_date == publish


def test_ventana_degenerada_monthly_hoy_se_expande_a_12_meses() -> None:
    """Caso time_reference='hoy': LLM manda start==end==publish_date en serie mensual."""
    publish = date(2025, 12, 11)
    draft = draft_from_llm_payload(
        _LLMResolutionPayload(
            catalog_id="ar_indec_ipc_mensual",
            start_date=publish,
            end_date=publish,
            rationale="IPC de hoy.",
        ),
        publish_date=publish,
    )
    assert draft.resolution_status == "verified_series"
    assert draft.end_date == publish
    assert draft.start_date == date(2024, 12, 11)
    assert (draft.end_date - draft.start_date).days == 365


def test_fechas_invertidas_siguen_fail_closed() -> None:
    with pytest.raises(ResolutionValidationError, match="start_date no puede ser mayor"):
        draft_from_llm_payload(
            _LLMResolutionPayload(
                catalog_id="ar_indec_ipc_mensual",
                start_date=date(2025, 6, 1),
                end_date=date(2025, 1, 1),
                rationale="Rango invertido.",
            ),
            publish_date=date(2025, 12, 11),
        )


def test_end_date_futura_sigue_rechazada_por_guardrail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _AgentDoble.creados.clear()
    monkeypatch.setattr(
        "tigani_broadcast.official_data_charts.resolver.Agent",
        _AgentDoble,
    )
    resolver = AgnoMentionResolver(_Modelo(), max_retries=0)
    agent = _AgentDoble.creados[0]
    agent.contents = [
        _LLMResolutionPayload(
            catalog_id="ar_indec_ipc_mensual",
            start_date=date(2025, 1, 1),
            end_date=date(2026, 1, 1),
            rationale="End futura.",
        )
    ]
    with pytest.raises(ResolutionValidationError, match="publish_date|posterior|futur"):
        resolver.resolve(_mention(1, "índice de inflación", "2.5%"), "ctx", date(2025, 12, 11))


def test_agno_resolver_fail_closed_tras_reintento(monkeypatch: pytest.MonkeyPatch) -> None:
    _AgentDoble.creados.clear()
    monkeypatch.setattr(
        "tigani_broadcast.official_data_charts.resolver.Agent",
        _AgentDoble,
    )
    resolver = AgnoMentionResolver(_Modelo(), max_retries=1)
    agent = _AgentDoble.creados[0]
    agent.raise_output_check = OutputCheckError(
        "salida basura",
        check_trigger=CheckTrigger.VALIDATION_FAILED,
    )
    with pytest.raises(ResolutionValidationError, match="salida basura"):
        resolver.resolve(
            _mention(1, "inflación", "2.5%"),
            "contexto",
            date(2025, 12, 11),
        )
    assert len(agent.prompts) == 2
    assert "rechazada porque" in agent.prompts[1]


def test_agno_resolver_fail_closed_run_status_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _AgentDoble.creados.clear()
    monkeypatch.setattr(
        "tigani_broadcast.official_data_charts.resolver.Agent",
        _AgentDoble,
    )
    resolver = AgnoMentionResolver(_Modelo(), max_retries=0)
    agent = _AgentDoble.creados[0]
    agent.status = RunStatus.error
    agent.content = "el guardrail rechazó la salida"
    with pytest.raises(ResolutionValidationError, match="guardrail rechazó"):
        resolver.resolve(
            _mention(1, "inflación", "2.5%"),
            "contexto",
            date(2025, 12, 11),
        )


def test_agno_resolver_reintento_exitoso_tras_anti_sustitucion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _AgentDoble.creados.clear()
    monkeypatch.setattr(
        "tigani_broadcast.official_data_charts.resolver.Agent",
        _AgentDoble,
    )
    resolver = AgnoMentionResolver(_Modelo(), max_retries=1)
    agent = _AgentDoble.creados[0]
    assert agent.kwargs["output_schema"] is _LLMResolutionPayload
    assert agent.kwargs["instructions"] == RESOLVER_INSTRUCTIONS
    assert agent.kwargs["expected_output"] == RESOLVER_EXPECTED_OUTPUT
    agent.contents = [
        _LLMResolutionPayload(
            catalog_id="ar_bcra_reservas_brutas",
            rationale="Mal mapeo a brutas.",
        ),
        _LLMResolutionPayload(
            catalog_id=None,
            rationale="Reservas netas: quoted_only.",
        ),
    ]
    draft = resolver.resolve(
        _mention(2, "reservas netas", "-17,000"),
        "Capítulo. Reservas.",
        date(2025, 12, 11),
    )
    assert draft.resolution_status == "quoted_only"
    assert draft.catalog_id is None
    assert len(agent.prompts) == 2
    assert "anti-sustitución" in agent.prompts[1]


def test_agno_resolver_ok_quoted_y_fija_temperature(monkeypatch: pytest.MonkeyPatch) -> None:
    _AgentDoble.creados.clear()
    monkeypatch.setattr(
        "tigani_broadcast.official_data_charts.resolver.Agent",
        _AgentDoble,
    )
    model = _Modelo(temperature=0.9)
    resolver = AgnoMentionResolver(model)
    assert model.temperature == 0.0
    agent = _AgentDoble.creados[0]
    agent.content = _LLMResolutionPayload(
        catalog_id="null",
        rationale="Monto puntual.",
    )
    draft = resolver.resolve(
        _mention(2, "swap", "900 M"),
        "Capítulo. Swap con China.",
        date(2025, 12, 11),
    )
    assert draft.resolution_status == "quoted_only"
    assert "swap" in agent.prompts[0].lower() or "900 M" in agent.prompts[0]


def test_resolve_chapters_mezcla_verified_quoted_y_fetch_error() -> None:
    publish = date(2025, 12, 11)
    inflation = _mention(1, "índice de inflación", "2.5%")
    netas = _mention(2, "reservas netas", "negativas")
    swap = _mention(3, "swap", "900 M")
    badlar = _mention(4, "tasa BADLAR", "9.26%")

    drafts = {
        "índice de inflación": ChartResolutionDraft(
            resolution_status="verified_series",
            catalog_id="ar_indec_ipc_mensual",
            start_date=date(2025, 1, 1),
            end_date=date(2025, 11, 1),
            rationale="IPC mensual INDEC.",
        ),
        "reservas netas": ChartResolutionDraft(
            resolution_status="quoted_only",
            rationale="Sin serie de reservas netas.",
        ),
        "swap": ChartResolutionDraft(
            resolution_status="quoted_only",
            rationale="Monto puntual de swap.",
        ),
        "tasa BADLAR": ChartResolutionDraft(
            resolution_status="verified_series",
            catalog_id="ar_bcra_tasa_badlar",
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 1),
            rationale="BADLAR BCRA.",
        ),
    }
    series_ipc = SeriesData(
        catalog_id="ar_indec_ipc_mensual",
        provider="indec",
        source_tier="official_primary",
        series_id="145.3_INGNACNAL_DICI_M_38",
        source_url="https://example.test/ipc",
        source_attribution="Fuente: INDEC",
        unit="%",
        frequency="monthly",
        observations=[
            SeriesObservation(obs_date=date(2025, 1, 1), value=2.5),
            SeriesObservation(obs_date=date(2025, 11, 1), value=2.5),
        ],
    )
    fetcher = _FetcherFake(
        series_by_id={"ar_indec_ipc_mensual": series_ipc},
        errors_by_id={"ar_bcra_tasa_badlar": ProviderError("HTTP 500 BCRA")},
    )
    package = resolve_chapters_to_artifacts(
        ChapterizedTranscript(chapters=[_chapter(inflation, netas, swap, badlar)]),
        publish,
        _ResolverFake(drafts),
        fetcher,  # type: ignore[arg-type]
        source_chapters_path="out/video.chapters.json",
    )

    assert package.publish_date == publish
    assert len(package.items) == 4
    assert package.items[0].resolution_status == "verified_series"
    assert package.items[0].metrics is not None
    assert package.items[0].series is not None
    assert package.items[1].resolution_status == "quoted_only"
    assert package.items[1].indicator_label == "reservas netas"
    assert package.items[2].resolution_status == "quoted_only"
    assert package.items[3].resolution_status == "fetch_error"
    assert package.items[3].error_message == "HTTP 500 BCRA"
    assert package.items[3].series is None


def test_resolve_chapters_degrada_resolution_validation_y_sigue() -> None:
    publish = date(2025, 12, 11)
    broken = _mention(1, "índice de inflación", "2.5%")
    ok = _mention(2, "swap", "900 M")
    package = resolve_chapters_to_artifacts(
        ChapterizedTranscript(chapters=[_chapter(broken, ok)]),
        publish,
        _ResolverFake(
            drafts={
                "swap": ChartResolutionDraft(
                    resolution_status="quoted_only",
                    rationale="Swap puntual.",
                )
            },
            errors={
                "índice de inflación": ResolutionValidationError(
                    "catalog_id fuera del catálogo cerrado: 'serie_falsa'"
                )
            },
        ),
        _FetcherFake(),  # type: ignore[arg-type]
    )
    assert len(package.items) == 2
    assert package.items[0].resolution_status == "fetch_error"
    assert package.items[0].rationale == "Error de validación al resolver indicador."
    assert "fuera del catálogo" in (package.items[0].error_message or "")
    assert package.items[1].resolution_status == "quoted_only"
    assert package.items[1].indicator_label == "swap"
