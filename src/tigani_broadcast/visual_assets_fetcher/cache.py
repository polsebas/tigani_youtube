"""Caché local determinista de búsquedas VisualCandidate en disco (JSON UTF-8)."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import TypeAdapter, ValidationError

from tigani_broadcast.visual_assets_fetcher.models import VisualProviderId

if TYPE_CHECKING:
    from tigani_broadcast.visual_assets_fetcher.providers.base import VisualCandidate

DEFAULT_CACHE_DIR = Path(".cache/tigani_broadcast/visual_assets_fetcher")
DEFAULT_TTL_SECONDS = 86_400  # 24 h

_WHITESPACE = re.compile(r"\s+")
_candidates_adapter: TypeAdapter[list[VisualCandidate]] | None = None


def _adapter() -> TypeAdapter[list[VisualCandidate]]:
    global _candidates_adapter
    if _candidates_adapter is None:
        from tigani_broadcast.visual_assets_fetcher.providers.base import VisualCandidate

        _candidates_adapter = TypeAdapter(list[VisualCandidate])
    return _candidates_adapter


def default_cache_dir() -> Path:
    """Directorio de caché: `TIGANI_CACHE_DIR` o `.cache/tigani_broadcast/visual_assets_fetcher`."""
    override = os.environ.get("TIGANI_CACHE_DIR")
    if override is not None and override.strip() != "":
        return Path(override)
    return DEFAULT_CACHE_DIR


def normalize_query(query: str) -> str:
    """Normaliza la query para la clave de caché (casefold + espacios colapsados)."""
    return _WHITESPACE.sub(" ", query.casefold()).strip()


def cache_key(provider: VisualProviderId | str, query: str, limit: int) -> str:
    """Clave determinista a partir de (provider, normalized_query, limit)."""
    raw = f"{provider}|{normalize_query(query)}|{limit}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class DiskVisualSearchCache:
    """Guarda y recupera listas de VisualCandidate con TTL. Reloj inyectable para tests."""

    def __init__(
        self,
        cache_dir: Path | str | None = None,
        *,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        if ttl_seconds < 0:
            raise ValueError("ttl_seconds no puede ser negativo")
        self._cache_dir = Path(cache_dir) if cache_dir is not None else default_cache_dir()
        self._ttl_seconds = ttl_seconds
        self._now_fn = now_fn or (lambda: datetime.now(UTC))

    @property
    def cache_dir(self) -> Path:
        return self._cache_dir

    @property
    def ttl_seconds(self) -> int:
        return self._ttl_seconds

    def _path_for(self, key: str) -> Path:
        return self._cache_dir / f"{key}.json"

    def get(
        self,
        provider: VisualProviderId | str,
        query: str,
        limit: int,
    ) -> list[VisualCandidate] | None:
        """Hit si el archivo existe, valida y no expiró; miss seguro ante corrupción."""
        path = self._path_for(cache_key(provider, query, limit))
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            cached_at = datetime.fromisoformat(payload["cached_at"])
            if cached_at.tzinfo is None:
                cached_at = cached_at.replace(tzinfo=UTC)
            candidates = _adapter().validate_python(payload["data"], strict=False)
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError, ValidationError):
            return None

        if self._now_fn() - cached_at > timedelta(seconds=self._ttl_seconds):
            return None
        return list(candidates)

    def put(
        self,
        provider: VisualProviderId | str,
        query: str,
        limit: int,
        candidates: list[VisualCandidate],
    ) -> Path:
        """Persiste candidatos con marca de tiempo UTC. Crea el directorio si hace falta."""
        key = cache_key(provider, query, limit)
        path = self._path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        envelope = {
            "cached_at": self._now_fn().astimezone(UTC).isoformat(),
            "provider": str(provider),
            "query": normalize_query(query),
            "limit": limit,
            "data": _adapter().dump_python(candidates, mode="json"),
        }
        path.write_text(json.dumps(envelope, ensure_ascii=False, indent=2), encoding="utf-8")
        return path
