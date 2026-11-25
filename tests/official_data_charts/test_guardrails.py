"""Guardrails del resolvedor: catálogo, anti-sustitución y rangos de fechas."""

from datetime import date
from types import SimpleNamespace

import pytest
from agno.exceptions import OutputCheckError

from tigani_broadcast.official_data_charts.guardrails import (
    AntiSubstitutionGuardrail,
    CatalogMembershipGuardrail,
    DateRangeGuardrail,
    normalize_label,
)
from tigani_broadcast.official_data_charts.models import ChartResolutionDraft


def _run(draft: ChartResolutionDraft) -> SimpleNamespace:
    return SimpleNamespace(content=draft)


def test_normalize_label_quita_acentos_y_espacios() -> None:
    assert normalize_label("  Resérvas   NETAS ") == "reservas netas"


def test_catalog_membership_acepta_id_valido() -> None:
    guard = CatalogMembershipGuardrail()
    draft = ChartResolutionDraft(
        resolution_status="verified_series",
        catalog_id="ar_indec_ipc_mensual",
        start_date=date(2025, 1, 1),
        end_date=date(2025, 3, 1),
        rationale="IPC mensual del INDEC.",
    )
    guard.check(_run(draft))  # type: ignore[arg-type]
    assert guard.failure is None


def test_catalog_membership_rechaza_id_inexistente() -> None:
    guard = CatalogMembershipGuardrail()
    draft = ChartResolutionDraft(
        resolution_status="verified_series",
        catalog_id="serie_inventada",
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 2),
        rationale="inventado",
    )
    with pytest.raises(OutputCheckError, match="fuera del catálogo"):
        guard.check(_run(draft))  # type: ignore[arg-type]


def test_catalog_membership_ignora_quoted_only() -> None:
    guard = CatalogMembershipGuardrail()
    draft = ChartResolutionDraft(
        resolution_status="quoted_only",
        rationale="Monto puntual de swap.",
    )
    guard.check(_run(draft))  # type: ignore[arg-type]
    assert guard.failure is None


def test_anti_substitution_bloquea_reservas_netas_a_brutas() -> None:
    guard = AntiSubstitutionGuardrail()
    guard.bind("Reservas Netás  del BCRA")
    draft = ChartResolutionDraft(
        resolution_status="verified_series",
        catalog_id="ar_bcra_reservas_brutas",
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 31),
        rationale="mal mapeo",
    )
    with pytest.raises(OutputCheckError, match="anti-sustitución"):
        guard.check(_run(draft))  # type: ignore[arg-type]


def test_anti_substitution_permite_quoted_only_reservas_netas() -> None:
    guard = AntiSubstitutionGuardrail()
    guard.bind("reservas netas")
    draft = ChartResolutionDraft(
        resolution_status="quoted_only",
        rationale="Sin serie de reservas netas en catálogo.",
    )
    guard.check(_run(draft))  # type: ignore[arg-type]
    assert guard.failure is None


def test_anti_substitution_permite_reservas_brutas_cuando_el_label_es_brutas() -> None:
    guard = AntiSubstitutionGuardrail()
    guard.bind("reservas brutas")
    draft = ChartResolutionDraft(
        resolution_status="verified_series",
        catalog_id="ar_bcra_reservas_brutas",
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 31),
        rationale="Serie brutas OK.",
    )
    guard.check(_run(draft))  # type: ignore[arg-type]
    assert guard.failure is None


def test_date_range_exige_fechas_en_verified_series() -> None:
    guard = DateRangeGuardrail()
    guard.bind(date(2025, 12, 11))
    draft = ChartResolutionDraft(
        resolution_status="verified_series",
        catalog_id="ar_indec_ipc_mensual",
        rationale="sin fechas",
    )
    with pytest.raises(OutputCheckError, match="start_date y end_date"):
        guard.check(_run(draft))  # type: ignore[arg-type]


def test_date_range_rechaza_start_mayor_que_end() -> None:
    guard = DateRangeGuardrail()
    guard.bind(date(2025, 12, 11))
    # Bypass el validador del modelo para ejercitar el guardrail.
    draft = ChartResolutionDraft.model_construct(
        resolution_status="verified_series",
        catalog_id="ar_indec_ipc_mensual",
        start_date=date(2025, 6, 1),
        end_date=date(2025, 1, 1),
        rationale="rango invertido",
    )
    with pytest.raises(OutputCheckError, match="start_date no puede ser mayor"):
        guard.check(_run(draft))  # type: ignore[arg-type]


def test_date_range_rechaza_end_posterior_a_publish_date() -> None:
    guard = DateRangeGuardrail()
    guard.bind(date(2025, 6, 1))
    draft = ChartResolutionDraft(
        resolution_status="verified_series",
        catalog_id="ar_indec_ipc_mensual",
        start_date=date(2025, 1, 1),
        end_date=date(2025, 7, 1),
        rationale="futuro",
    )
    with pytest.raises(OutputCheckError, match="no puede ser posterior"):
        guard.check(_run(draft))  # type: ignore[arg-type]


def test_date_range_quoted_only_pasa_limpio() -> None:
    guard = DateRangeGuardrail()
    guard.bind(date(2025, 12, 11))
    draft = ChartResolutionDraft(
        resolution_status="quoted_only",
        rationale="dato puntual",
    )
    guard.check(_run(draft))  # type: ignore[arg-type]
    assert guard.failure is None


def test_date_range_exige_publish_date_vinculado() -> None:
    guard = DateRangeGuardrail()
    draft = ChartResolutionDraft(
        resolution_status="verified_series",
        catalog_id="ar_bcra_cer",
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 2),
        rationale="sin bind",
    )
    with pytest.raises(OutputCheckError, match="publish_date"):
        guard.check(_run(draft))  # type: ignore[arg-type]


def test_async_check_delega_a_check() -> None:
    import asyncio

    guard = CatalogMembershipGuardrail()
    draft = ChartResolutionDraft(
        resolution_status="quoted_only",
        rationale="ok",
    )
    asyncio.run(guard.async_check(_run(draft)))  # type: ignore[arg-type]
    assert guard.failure is None


def test_date_range_acepta_rango_valido() -> None:
    guard = DateRangeGuardrail()
    guard.bind(date(2025, 12, 11))
    draft = ChartResolutionDraft(
        resolution_status="verified_series",
        catalog_id="ar_bcra_cer",
        start_date=date(2025, 1, 1),
        end_date=date(2025, 12, 11),
        rationale="CER hasta publish_date",
    )
    guard.check(_run(draft))  # type: ignore[arg-type]
    assert guard.failure is None
