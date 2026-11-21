"""Post-hooks deterministas. Agno 3.2.1 los ejecuta con `run_output`, sin otra llamada al modelo."""

import re
from abc import abstractmethod
from collections.abc import Sequence
from decimal import Decimal

from agno.exceptions import CheckTrigger, OutputCheckError
from agno.guardrails.base import BaseGuardrail
from agno.run.agent import RunOutput

from tigani_broadcast.transcript_chapterizer.models import (
    Cue,
    DraftChapterDetails,
    DraftChapterizedTranscript,
    DraftHardDataMention,
)

MAX_LOWER_THIRD_LENGTH = 100

_NUMBER = re.compile(r"(?<!\d)(?:\d{1,3}(?:[.,]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)(?!\d)")
_NUMERIC_CUE = re.compile(r"\d|%")
_YEAR_IN_LABEL = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")


def normalized_numbers(text: str) -> frozenset[Decimal]:
    """Cifras comparables. `8,000`, `8.000` y `8000` coinciden; `2.5` y `2,5` también."""
    found: set[Decimal] = set()
    for match in _NUMBER.finditer(text):
        found.add(_parse_number(match.group(0)))
    return frozenset(found)


def numeric_cue_indexes(cues: Sequence[Cue]) -> list[int]:
    """Índices cuya cue trae un dígito o un porcentaje."""
    return [cue.cue_index for cue in cues if _NUMERIC_CUE.search(cue.text)]


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


class CueGroundingGuardrail(_OutputGuardrail):
    """Reancla `cue_index` dentro del capítulo: exacto, después ±1, después el tramo."""

    def __init__(self) -> None:
        super().__init__()
        self.cues: tuple[Cue, ...] = ()
        self._by_index: dict[int, Cue] = {}
        self.start = 0
        self.end = -1

    def bind(
        self,
        cues: Sequence[Cue],
        *,
        start: int | None = None,
        end: int | None = None,
    ) -> None:
        self.cues = tuple(cues)
        self._by_index = {cue.cue_index: cue for cue in cues}
        indexes = [cue.cue_index for cue in cues]
        if start is None:
            self.start = min(indexes) if indexes else 0
        else:
            self.start = start
        if end is None:
            self.end = max(indexes) if indexes else -1
        else:
            self.end = end

    def _check(self, run_output: RunOutput) -> None:
        content = run_output.content
        mentions = _hard_data_of(content)
        if mentions is None or not isinstance(content, _DraftWithMentions):
            return
        updated: list[DraftHardDataMention] = []
        changed = False
        for mention in mentions:
            anchored = self._anchor(mention)
            updated.append(anchored)
            changed = changed or anchored is not mention
        if changed:
            run_output.content = content.model_copy(update={"hard_data": updated})

    def _anchor(self, mention: DraftHardDataMention) -> DraftHardDataMention:
        wanted = normalized_numbers(mention.raw_value_text)
        if not wanted:
            self._fail(
                f"raw_value_text no contiene una cifra verificable: {mention.raw_value_text!r}"
            )
        if self._has_numbers(mention.cue_index, wanted):
            return mention
        neighbors = [
            index
            for index in (mention.cue_index - 1, mention.cue_index + 1)
            if self._has_numbers(index, wanted)
        ]
        if len(neighbors) == 1:
            return mention.model_copy(update={"cue_index": neighbors[0]})
        if len(neighbors) > 1:
            self._fail(
                f"la cifra {mention.raw_value_text!r} aparece en más de una cue "
                f"adyacente a {mention.cue_index}"
            )
        matches = self._chapter_matches(wanted)
        if len(matches) == 1:
            return mention.model_copy(update={"cue_index": matches[0]})
        if len(matches) > 1:
            self._fail(
                f"la cifra {mention.raw_value_text!r} aparece en más de una cue del capítulo "
                f"{self.start}..{self.end}"
            )
        self._fail(
            f"la cifra {mention.raw_value_text!r} no aparece en la cue {mention.cue_index} "
            f"ni en el capítulo {self.start}..{self.end}"
        )

    def _chapter_matches(self, wanted: frozenset[Decimal]) -> list[int]:
        return [
            index for index in range(self.start, self.end + 1) if self._has_numbers(index, wanted)
        ]

    def _has_numbers(self, index: int, wanted: frozenset[Decimal]) -> bool:
        if index < self.start or index > self.end:
            return False
        cue = self._by_index.get(index)
        if cue is None:
            return False
        return wanted <= normalized_numbers(cue.text)


class TimeReferenceGuardrail(_OutputGuardrail):
    """Un año dentro de `indicator_label` exige `time_reference`."""

    def _check(self, run_output: RunOutput) -> None:
        mentions = _hard_data_of(run_output.content)
        if mentions is None:
            return
        for mention in mentions:
            if mention.time_reference is None and _YEAR_IN_LABEL.search(mention.indicator_label):
                self._fail(
                    "indicator_label contiene un año y time_reference es None: "
                    f"{mention.indicator_label!r}"
                )


class SummaryHardDataConsistencyGuardrail(_OutputGuardrail):
    """Un resumen con cifras no puede ir con hard_data vacío."""

    def _check(self, run_output: RunOutput) -> None:
        for label, summary, mentions in _summary_catalogs(run_output.content):
            if mentions:
                continue
            if _has_economic_metric(summary):
                self._fail(f"{label} menciona una cifra económica y hard_data está vacío")


class SpanishLanguageGuardrail(_OutputGuardrail):
    """Rechaza un resumen o zócalo en el que el inglés le gana al español."""

    def _check(self, run_output: RunOutput) -> None:
        for label, text in _prose_fields(run_output.content):
            if _english_dominates(text):
                self._fail(f"{label} está redactado en inglés")


class LowerThirdLengthGuardrail(_OutputGuardrail):
    """El zócalo de OBS no pasa de `MAX_LOWER_THIRD_LENGTH` caracteres."""

    def _check(self, run_output: RunOutput) -> None:
        for position, text in enumerate(_lower_thirds_of(run_output.content)):
            length = len(text)
            if length > MAX_LOWER_THIRD_LENGTH:
                self._fail(
                    f"capítulo {position}: suggested_lower_third tiene {length} caracteres; "
                    f"el máximo es {MAX_LOWER_THIRD_LENGTH}"
                )


_DraftWithMentions = DraftChapterizedTranscript | DraftChapterDetails


def _hard_data_of(content: object) -> list[DraftHardDataMention] | None:
    if isinstance(content, _DraftWithMentions):
        return list(content.hard_data)
    return None


_ENGLISH_MARKERS = frozenset(
    {
        "the",
        "and",
        "with",
        "including",
        "which",
        "current",
        "previously",
        "highlights",
        "were",
        "than",
        "past",
        "reserves",
        "indicators",
        "inflation",
        "economic",
        "higher",
        "additionally",
        "reported",
    }
)
_SPANISH_MARKERS = frozenset(
    {
        "el",
        "la",
        "los",
        "las",
        "un",
        "una",
        "de",
        "del",
        "al",
        "que",
        "y",
        "en",
        "con",
        "por",
        "para",
        "se",
        "es",
        "son",
        "fue",
        "hay",
        "no",
        "su",
        "sus",
        "como",
        "hoy",
        "este",
        "esta",
        "millones",
        "mil",
    }
)
_WORD = re.compile(r"[a-záéíóúüñ]+", re.IGNORECASE)
_ECONOMIC_METRIC = re.compile(
    r"(?:\d+(?:[.,]\d+)?\s*%)|(?:\d+(?:[.,]\d+)*\s*(?:millones|mil|dólares|dolares|pesos|usd)\b)",
    re.IGNORECASE,
)


def _has_economic_metric(text: str) -> bool:
    return _ECONOMIC_METRIC.search(text) is not None


def _english_dominates(text: str) -> bool:
    tokens = [token.lower() for token in _WORD.findall(text)]
    english = sum(token in _ENGLISH_MARKERS for token in tokens)
    spanish = sum(token in _SPANISH_MARKERS for token in tokens)
    return english >= 2 and english > spanish


def _summary_catalogs(content: object) -> list[tuple[str, str, list[DraftHardDataMention]]]:
    if isinstance(content, DraftChapterDetails):
        return [("summary", content.summary, list(content.hard_data))]
    if isinstance(content, DraftChapterizedTranscript):
        return [
            (f"capítulo {position} summary", chapter.summary, list(content.hard_data))
            for position, chapter in enumerate(content.chapters)
        ]
    return []


def _prose_fields(content: object) -> list[tuple[str, str]]:
    if isinstance(content, DraftChapterDetails):
        return [
            ("summary", content.summary),
            ("suggested_lower_third", content.suggested_lower_third),
        ]
    if isinstance(content, DraftChapterizedTranscript):
        fields: list[tuple[str, str]] = []
        for position, chapter in enumerate(content.chapters):
            fields.append((f"capítulo {position} summary", chapter.summary))
            fields.append(
                (f"capítulo {position} suggested_lower_third", chapter.suggested_lower_third)
            )
        return fields
    return []


def _lower_thirds_of(content: object) -> list[str]:
    if isinstance(content, DraftChapterDetails):
        return [content.suggested_lower_third]
    if isinstance(content, DraftChapterizedTranscript):
        return [chapter.suggested_lower_third for chapter in content.chapters]
    return []


def _parse_number(token: str) -> Decimal:
    if "," in token and "." in token:
        if token.rfind(",") > token.rfind("."):
            normalized = token.replace(".", "").replace(",", ".")
        else:
            normalized = token.replace(",", "")
    elif "," in token or "." in token:
        separator = "," if "," in token else "."
        parts = token.split(separator)
        if all(len(part) == 3 for part in parts[1:]):
            normalized = "".join(parts)
        elif len(parts) == 2:
            normalized = f"{parts[0]}.{parts[1]}"
        else:
            normalized = f"{''.join(parts[:-1])}.{parts[-1]}"
    else:
        normalized = token
    return Decimal(normalized)
