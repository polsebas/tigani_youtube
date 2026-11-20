"""Puerto de ingesta. El cliente de YouTube no entra en este módulo."""

from typing import Protocol, runtime_checkable

from tigani_broadcast.transcript_chapterizer.models import Cue


@runtime_checkable
class TranscriptSource(Protocol):
    """Origen de cues ya normalizadas. No descarga video ni subtítulos."""

    def load(self) -> list[Cue]:
        """Devuelve las cues en el orden de lectura."""
        ...
