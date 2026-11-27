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
    SERIES_CATALOG,
    AgnoMentionResolver,
    ResolutionValidationError,
    _LLMResolutionPayload,
    draft_from_llm_payload,
    fallback_match_series_key,
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
    assert daily.narrative_mode == "trend_with_callout"
    assert daily.start_date == publish - timedelta(days=400)

    monthly = draft_from_llm_payload(
        _LLMResolutionPayload(
            catalog_id="ar_indec_ipc_mensual",
            rationale="IPC mensual.",
        ),
        publish_date=publish,
    )
    assert monthly.start_date == publish - timedelta(days=400)
    assert monthly.end_date == publish


@pytest.mark.parametrize(
    "mode,expected_days",
    [
        ("trend_with_callout", 400),
        ("ytd_focus", 400),
        ("term_comparison", 1461),
    ],
)
def test_ventana_ampliada_segun_narrative_mode(mode: str, expected_days: int) -> None:
    publish = date(2025, 12, 11)
    draft = draft_from_llm_payload(
        _LLMResolutionPayload(
            catalog_id="ar_indec_ipc_mensual",
            narrative_mode=mode,  # type: ignore[arg-type]
            rationale=f"Modo {mode}.",
        ),
        publish_date=publish,
    )
    assert draft.narrative_mode == mode
    assert draft.end_date == publish
    assert draft.start_date == publish - timedelta(days=expected_days)
    assert (draft.end_date - draft.start_date).days == expected_days


def test_ventana_degenerada_monthly_hoy_se_expande_a_13_meses() -> None:
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
    assert draft.start_date == publish - timedelta(days=400)
    assert (draft.end_date - draft.start_date).days == 400


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
    assert package.items[0].narrative is not None
    assert package.items[0].narrative.mode == "trend_with_callout"
    assert package.items[0].narrative.anchor_date == "2025-11-01"
    assert package.items[1].resolution_status == "quoted_only"
    assert package.items[1].indicator_label == "reservas netas"
    assert package.items[1].narrative is None
    assert package.items[2].resolution_status == "quoted_only"
    assert package.items[2].narrative is None
    assert package.items[3].resolution_status == "fetch_error"
    assert package.items[3].error_message == "HTTP 500 BCRA"
    assert package.items[3].series is None
    assert package.items[3].narrative is None


def test_resolve_chapters_narrative_term_comparison_pobla_bandas() -> None:
    publish = date(2025, 6, 1)
    mention = _mention(1, "índice de inflación", "2.5%")
    observations = [
        SeriesObservation(obs_date=date(2022, 1, 1), value=3.0),
        SeriesObservation(obs_date=date(2023, 6, 1), value=6.0),
        SeriesObservation(obs_date=date(2024, 6, 1), value=4.0),
        SeriesObservation(obs_date=date(2025, 5, 1), value=2.5),
    ]
    package = resolve_chapters_to_artifacts(
        ChapterizedTranscript(chapters=[_chapter(mention)]),
        publish,
        _ResolverFake(
            {
                "índice de inflación": ChartResolutionDraft(
                    resolution_status="verified_series",
                    catalog_id="ar_indec_ipc_mensual",
                    start_date=date(2022, 1, 1),
                    end_date=publish,
                    rationale="Comparación de gestiones.",
                    narrative_mode="term_comparison",
                )
            }
        ),
        _FetcherFake(
            {
                "ar_indec_ipc_mensual": SeriesData(
                    catalog_id="ar_indec_ipc_mensual",
                    provider="indec",
                    source_tier="official_primary",
                    series_id="145.3_INGNACNAL_DICI_M_38",
                    source_url="https://example.test/ipc",
                    source_attribution="Fuente: INDEC",
                    unit="%",
                    frequency="monthly",
                    observations=observations,
                )
            }
        ),  # type: ignore[arg-type]
    )
    assert len(package.items) == 1
    artifact = package.items[0]
    assert artifact.resolution_status == "verified_series"
    assert artifact.narrative is not None
    assert artifact.narrative.mode == "term_comparison"
    assert len(artifact.narrative.regime_bands) >= 2
    assert artifact.narrative.headline_badge is not None


@pytest.mark.parametrize(
    "indicator,context,expected",
    [
        ("índice de inflación", "Coyuntura local", "ar_indec_ipc_mensual"),
        (
            "índice de inflación",
            "Las reservas netas son negativas; inflación local 2.5%",
            "ar_indec_ipc_mensual",
        ),
        ("IPC", "mes pasado", "ar_indec_ipc_mensual"),
        ("IPC interanual", "INDEC", "ar_indec_ipc_interanual"),
        ("inflación interanual", "", "ar_indec_ipc_interanual"),
        ("inflación EEUU", "CPI", None),
        ("inflación", "Estados Unidos", None),
        ("riesgo país", "", "ar_mkt_riesgo_pais"),
        ("EMBI", "Argentina", "ar_mkt_riesgo_pais"),
        ("dólar blue", "", "ar_mkt_dolar_blue"),
        ("dólar oficial", "BCRA", "ar_bcra_dolar_mayorista"),
        ("tipo de cambio oficial", "", "ar_bcra_dolar_mayorista"),
        ("EMAE", "actividad", "ar_indec_emae_mensual"),
        ("actividad económica", "mensual", "ar_indec_emae_mensual"),
        ("reservas netas", "BCRA", None),
        ("reservas brutas", "BCRA", None),
    ],
)
def test_fallback_match_series_key_alias_inequivocos(
    indicator: str,
    context: str,
    expected: str | None,
) -> None:
    matched = fallback_match_series_key(indicator, context)
    assert matched == expected
    if expected is not None:
        assert expected in SERIES_CATALOG


def test_fallback_no_arrastra_inflacion_desde_contexto_del_capitulo() -> None:
    """Título/summary con 'inflación' no debe mapear menciones ajenas (falsos positivos)."""
    matched = fallback_match_series_key(
        "productos y servicios en dólares",
        "El contexto de la inflación",
    )
    assert matched is None


def _ipc_series() -> SeriesData:
    return SeriesData(
        catalog_id="ar_indec_ipc_mensual",
        provider="indec",
        source_tier="official_primary",
        series_id="145.3_INGNACNAL_DICI_M_38",
        source_url="https://example.test/ipc",
        source_attribution="Fuente: INDEC",
        unit="%",
        frequency="monthly",
        observations=[
            SeriesObservation(obs_date=date(2025, 10, 1), value=1.9),
            SeriesObservation(obs_date=date(2025, 11, 1), value=2.2),
        ],
    )


def test_fallback_catalog_cuando_llm_devuelve_catalog_id_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLM con series_key/catalog_id=None: inflación → verified+narrative."""
    _AgentDoble.creados.clear()
    monkeypatch.setattr(
        "tigani_broadcast.official_data_charts.resolver.Agent",
        _AgentDoble,
    )
    resolver = AgnoMentionResolver(_Modelo(), max_retries=0)
    agent = _AgentDoble.creados[0]
    agent.content = _LLMResolutionPayload(
        catalog_id=None,
        narrative_mode="trend_with_callout",
        rationale="No identifiqué serie.",
    )

    package = resolve_chapters_to_artifacts(
        ChapterizedTranscript(chapters=[_chapter(_mention(1, "índice de inflación", "2,2%"))]),
        date(2025, 12, 11),
        resolver,
        _FetcherFake({"ar_indec_ipc_mensual": _ipc_series()}),  # type: ignore[arg-type]
    )

    assert len(package.items) == 1
    verified = package.items[0]
    assert verified.resolution_status == "verified_series"
    assert verified.series is not None
    assert verified.series.catalog_id == "ar_indec_ipc_mensual"
    assert verified.narrative is not None
    assert verified.narrative.mode == "trend_with_callout"
    assert verified.narrative.anchor_date == "2025-11-01"


def test_fallback_catalog_cuando_llm_devuelve_quoted_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLM con catalog_id='quoted_only': inflación inequívoca → verified+narrative."""
    _AgentDoble.creados.clear()
    monkeypatch.setattr(
        "tigani_broadcast.official_data_charts.resolver.Agent",
        _AgentDoble,
    )
    resolver = AgnoMentionResolver(_Modelo(), max_retries=0)
    agent = _AgentDoble.creados[0]
    agent.content = _LLMResolutionPayload(
        catalog_id="quoted_only",
        narrative_mode="ytd_focus",
        rationale="Decisión quoted_only del modelo local.",
    )

    package = resolve_chapters_to_artifacts(
        ChapterizedTranscript(chapters=[_chapter(_mention(1, "índice de inflación", "2,2%"))]),
        date(2025, 12, 11),
        resolver,
        _FetcherFake({"ar_indec_ipc_mensual": _ipc_series()}),  # type: ignore[arg-type]
    )

    assert len(package.items) == 1
    verified = package.items[0]
    assert verified.resolution_status == "verified_series"
    assert verified.narrative is not None
    assert verified.narrative.mode == "ytd_focus"
    assert verified.series is not None
    assert verified.series.catalog_id == "ar_indec_ipc_mensual"


def test_fallback_catalog_cuando_llm_lanza_o_json_invalido(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Parseo/validación rota: inflación inequívoca → verified+narrative vía fallback."""
    _AgentDoble.creados.clear()
    monkeypatch.setattr(
        "tigani_broadcast.official_data_charts.resolver.Agent",
        _AgentDoble,
    )
    resolver = AgnoMentionResolver(_Modelo(), max_retries=0)
    agent = _AgentDoble.creados[0]
    agent.content = {"not": "a payload"}  # fuerza fallo de tipo / parseo estructurado

    package = resolve_chapters_to_artifacts(
        ChapterizedTranscript(chapters=[_chapter(_mention(1, "índice de inflación", "2,2%"))]),
        date(2025, 12, 11),
        resolver,
        _FetcherFake({"ar_indec_ipc_mensual": _ipc_series()}),  # type: ignore[arg-type]
    )

    assert len(package.items) == 1
    verified = package.items[0]
    assert verified.resolution_status == "verified_series"
    assert verified.narrative is not None
    assert verified.series is not None
    assert verified.series.catalog_id == "ar_indec_ipc_mensual"


def test_fallback_no_rescata_reservas_netas(monkeypatch: pytest.MonkeyPatch) -> None:
    """reservas netas debe seguir en quoted_only aunque el LLM no elija serie."""
    _AgentDoble.creados.clear()
    monkeypatch.setattr(
        "tigani_broadcast.official_data_charts.resolver.Agent",
        _AgentDoble,
    )
    resolver = AgnoMentionResolver(_Modelo(), max_retries=0)
    agent = _AgentDoble.creados[0]
    agent.content = _LLMResolutionPayload(
        catalog_id=None,
        narrative_mode="trend_with_callout",
        rationale="Reservas netas sin serie oficial.",
    )

    package = resolve_chapters_to_artifacts(
        ChapterizedTranscript(chapters=[_chapter(_mention(2, "reservas netas", "negativas"))]),
        date(2025, 12, 11),
        resolver,
        _FetcherFake(),  # type: ignore[arg-type]
    )

    assert len(package.items) == 1
    quoted = package.items[0]
    assert quoted.resolution_status == "quoted_only"
    assert quoted.indicator_label == "reservas netas"
    assert quoted.narrative is None
    assert quoted.series is None


def test_resolve_chapters_degrada_resolution_validation_y_sigue() -> None:
    """Sin alias inequívoco, el error de resolución sigue degradando a fetch_error."""
    publish = date(2025, 12, 11)
    broken = _mention(1, "colocación puntual de bono", "4600 M")
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
                "colocación puntual de bono": ResolutionValidationError(
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


def test_resolve_chapters_rescata_inflacion_si_resolver_falla() -> None:
    """Aunque el resolver fake falle, índice de inflación se rescata con fallback."""
    publish = date(2025, 12, 11)
    inflation = _mention(1, "índice de inflación", "2.5%")
    package = resolve_chapters_to_artifacts(
        ChapterizedTranscript(chapters=[_chapter(inflation)]),
        publish,
        _ResolverFake(
            errors={
                "índice de inflación": ResolutionValidationError(
                    "catalog_id fuera del catálogo cerrado: 'serie_falsa'"
                )
            },
        ),
        _FetcherFake({"ar_indec_ipc_mensual": _ipc_series()}),  # type: ignore[arg-type]
    )
    assert len(package.items) == 1
    assert package.items[0].resolution_status == "verified_series"
    assert package.items[0].narrative is not None
    assert package.items[0].series is not None
    assert package.items[0].series.catalog_id == "ar_indec_ipc_mensual"


def test_regresion_inflacion_quoted_only_con_contexto_reservas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Caso real kP_G1sAStQE: LLM devuelve quoted_only citando ar_indec_ipc_interanual
    y el summary del capítulo menciona reservas netas. Debe rescatar IPC mensual.
    """
    _AgentDoble.creados.clear()
    monkeypatch.setattr(
        "tigani_broadcast.official_data_charts.resolver.Agent",
        _AgentDoble,
    )
    resolver = AgnoMentionResolver(_Modelo(), max_retries=0)
    agent = _AgentDoble.creados[0]
    agent.content = _LLMResolutionPayload(
        catalog_id="quoted_only",
        narrative_mode="trend_with_callout",
        rationale=(
            "La mención se refiere al 'índice de inflación' con valor '2.5%' y "
            "tiempo de referencia 'hoy', lo cual corresponde al indicador "
            "'ar_indec_ipc_interanual' del catálogo."
        ),
    )
    chapter = _chapter(
        _mention(1, "índice de inflación", "2.5%", time_reference="hoy"),
        title="El contexto de la inflación y su comparación histórica",
        summary=(
            "El índice de inflación alcanzó 2.5% hoy. Las reservas netas son "
            "negativas en 17,000 millones, mientras que en 2015 tenían 8,000 millones."
        ),
    )
    package = resolve_chapters_to_artifacts(
        ChapterizedTranscript(chapters=[chapter]),
        date(2025, 12, 11),
        resolver,
        _FetcherFake({"ar_indec_ipc_mensual": _ipc_series()}),  # type: ignore[arg-type]
    )
    assert len(package.items) == 1
    artifact = package.items[0]
    assert artifact.resolution_status == "verified_series"
    assert artifact.series is not None
    assert artifact.series.catalog_id == "ar_indec_ipc_mensual"
    assert artifact.narrative is not None


def test_regresion_inflacion_llm_elige_ipc_interanual(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLM elige ar_indec_ipc_interanual ante 'índice de inflación' → forzar mensual."""
    _AgentDoble.creados.clear()
    monkeypatch.setattr(
        "tigani_broadcast.official_data_charts.resolver.Agent",
        _AgentDoble,
    )
    resolver = AgnoMentionResolver(_Modelo(), max_retries=0)
    agent = _AgentDoble.creados[0]
    agent.content = _LLMResolutionPayload(
        catalog_id="ar_indec_ipc_interanual",
        narrative_mode="trend_with_callout",
        rationale="Mapear a IPC interanual.",
    )
    package = resolve_chapters_to_artifacts(
        ChapterizedTranscript(
            chapters=[
                _chapter(
                    _mention(1, "índice de inflación", "2.5%", time_reference="hoy"),
                    summary="Las reservas netas son negativas; inflación 2.5% hoy.",
                )
            ]
        ),
        date(2025, 12, 11),
        resolver,
        _FetcherFake({"ar_indec_ipc_mensual": _ipc_series()}),  # type: ignore[arg-type]
    )
    assert len(package.items) == 1
    artifact = package.items[0]
    assert artifact.resolution_status == "verified_series"
    assert artifact.series is not None
    assert artifact.series.catalog_id == "ar_indec_ipc_mensual"
    assert artifact.narrative is not None
