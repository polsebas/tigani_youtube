"""Parser determinista de archivos UTF-8 con líneas `[HH:MM:SS] texto`."""

import re
from pathlib import Path

from tigani_broadcast.transcript_chapterizer.models import Cue, canonical_timestamp

_LINE = re.compile(r"^\[(?P<hours>\d+):(?P<minutes>\d{2}):(?P<seconds>\d{2})\](?P<text>.*)$")


class TranscriptFormatError(ValueError):
    """El archivo no se puede interpretar sin inventar ni descartar una línea."""

    def __init__(self, message: str, *, line_number: int | None = None) -> None:
        self.line_number = line_number
        if line_number is None:
            super().__init__(message)
            return
        super().__init__(f"línea {line_number}: {message}")


class FileTranscriptSource:
    """Adaptador v0. Lee un UTF-8 del disco y lo entrega como cues."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def load(self) -> list[Cue]:
        try:
            text = self.path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError as exc:
            raise TranscriptFormatError(
                f"no se pudo leer el archivo, no es UTF-8 válido: {self.path}"
            ) from exc
        except OSError as exc:
            raise TranscriptFormatError(f"no se pudo leer el archivo: {self.path}") from exc
        return parse_transcript(text)


def parse_transcript(text: str) -> list[Cue]:
    """Convierte el texto completo. Si una línea no cierra, no hay resultado parcial."""
    if text.startswith("\ufeff"):
        text = text.removeprefix("\ufeff")

    cues: list[Cue] = []
    previous: tuple[int, int, int] | None = None
    for line_number, line in enumerate(text.splitlines(), start=1):
        if line.strip() == "":
            continue
        timestamp, cue_text, clock = _parse_line(line, line_number)
        if previous is not None and clock < previous:
            previous_timestamp = canonical_timestamp(*previous)
            raise TranscriptFormatError(
                f"el timestamp {timestamp} retrocede respecto de {previous_timestamp}",
                line_number=line_number,
            )
        cues.append(Cue(cue_index=len(cues), timestamp=timestamp, text=cue_text))
        previous = clock

    if not cues:
        raise TranscriptFormatError("la transcripción no contiene ninguna cue")
    return cues


def _parse_line(line: str, line_number: int) -> tuple[str, str, tuple[int, int, int]]:
    match = _LINE.fullmatch(line)
    if match is None:
        raise TranscriptFormatError(
            f"formato inválido, se espera [HH:MM:SS] texto: {line!r}",
            line_number=line_number,
        )

    hours = int(match.group("hours"))
    minutes = int(match.group("minutes"))
    seconds = int(match.group("seconds"))
    try:
        timestamp = canonical_timestamp(hours, minutes, seconds)
    except ValueError as exc:
        raw = f"{match.group('hours')}:{match.group('minutes')}:{match.group('seconds')}"
        raise TranscriptFormatError(
            f"timestamp fuera de rango: {raw}",
            line_number=line_number,
        ) from exc

    cue_text = match.group("text").strip()
    if cue_text == "":
        raise TranscriptFormatError("el texto de la cue está vacío", line_number=line_number)
    return timestamp, cue_text, (hours, minutes, seconds)
