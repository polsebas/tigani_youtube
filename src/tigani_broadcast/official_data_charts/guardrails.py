"""Post-hooks deterministas del resolvedor. Cero llamadas al LLM."""

from __future__ import annotations

import re
import unicodedata
from abc import abstractmethod
from datetime import date

from agno.exceptions import CheckTrigger, OutputCheckError
from agno.guardrails.base import BaseGuardrail
from agno.run.agent import RunOutput

from tigani_broadcast.official_data_charts.catalog import is_valid_catalog_id
from tigani_broadcast.official_data_charts.models import ChartResolutionDraft

_WHITESPACE = re.compile(r"\s+")


def normalize_label(text: str) -> str:
    """Minúsculas, sin acentos y con espacios colapsados (comparación fail-closed)."""
    decomposed = unicodedata.normalize("NFKD", text)
    without_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return _WHITESPACE.sub(" ", without_marks.casefold()).strip()


class _OutputGuardrail(BaseGuardrail):
    """`check` recibe `run_output` porque así filtra los kwargs el post-hook de Agno 3.2.1."""

    def __init__(self) -> None:
        self.failure: str | None = None

    def check(self, run_output: RunOutput) -> None:
        self.failure = None
        self._check(run_output)

    async def async_check(self, run_output: RunOutput) -> None:
        self.check(run_output)

    @abstractmethod
    def _check(self, run_output: RunOutput) -> None:
        """Revisa el borrador. Cada guardrail define la regla."""

    def _fail(self, message: str) -> None:
        self.failure = message
        raise OutputCheckError(message, check_trigger=CheckTrigger.VALIDATION_FAILED)

    def _draft(self, run_output: RunOutput) -> ChartResolutionDraft | None:
        content = run_output.content
        if isinstance(content, ChartResolutionDraft):
            return content
        return None


class CatalogMembershipGuardrail(_OutputGuardrail):
    """verified_series solo con catalog_id del catálogo cerrado."""

    def _check(self, run_output: RunOutput) -> None:
        draft = self._draft(run_output)
        if draft is None or draft.resolution_status != "verified_series":
            return
        catalog_id = draft.catalog_id
        if catalog_id is None or not is_valid_catalog_id(catalog_id):
            self._fail(f"catalog_id fuera del catálogo cerrado: {catalog_id!r}")


class AntiSubstitutionGuardrail(_OutputGuardrail):
    """
    Bloquea mapear 'reservas netas' a la serie de reservas brutas del BCRA.
    En v0 esa mención tiene que salir como quoted_only.
    """

    def __init__(self) -> None:
        super().__init__()
        self.indicator_label: str = ""

    def bind(self, indicator_label: str) -> None:
        self.indicator_label = indicator_label

    def _check(self, run_output: RunOutput) -> None:
        draft = self._draft(run_output)
        if draft is None:
            return
        label = normalize_label(self.indicator_label)
        if "reservas netas" not in label:
            return
        if (
            draft.resolution_status == "verified_series"
            and draft.catalog_id == "ar_bcra_reservas_brutas"
        ):
            self._fail(
                "anti-sustitución: 'reservas netas' no puede mapearse a "
                "ar_bcra_reservas_brutas; debe ser quoted_only"
            )


class DateRangeGuardrail(_OutputGuardrail):
    """verified_series exige rango presente, ordenado y no posterior a publish_date."""

    def __init__(self) -> None:
        super().__init__()
        self.publish_date: date | None = None

    def bind(self, publish_date: date) -> None:
        self.publish_date = publish_date

    def _check(self, run_output: RunOutput) -> None:
        draft = self._draft(run_output)
        if draft is None or draft.resolution_status != "verified_series":
            return
        if self.publish_date is None:
            self._fail("DateRangeGuardrail: falta publish_date vinculado")
            return
        if draft.start_date is None or draft.end_date is None:
            self._fail("verified_series exige start_date y end_date explícitos (YYYY-MM-DD)")
            return
        if draft.start_date > draft.end_date:
            self._fail("start_date no puede ser mayor que end_date")
            return
        if draft.end_date > self.publish_date:
            self._fail(
                f"end_date {draft.end_date.isoformat()} no puede ser posterior a "
                f"publish_date {self.publish_date.isoformat()}"
            )
