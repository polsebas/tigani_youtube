"""Caché local determinista de SeriesData en disco (JSON UTF-8)."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from pydantic import ValidationError

from tigani_broadcast.official_data_charts.models import ProviderId, SeriesData

DEFAULT_CACHE_DIR = Path(".cache/tigani_broadcast/official_data_charts")
DEFAULT_TTL_SECONDS = 21_600  # 6 h
ARGENTINADATOS_MIN_TTL_SECONDS = 10_800  # 3 h obligatorio


def default_cache_dir() -> Path:
    """Directorio de caché: `TIGANI_CACHE_DIR` o `.cache/tigani_broadcast/official_data_charts`."""
    override = os.environ.get("TIGANI_CACHE_DIR")
    if override is not None and override.strip() != "":
        return Path(override)
    return DEFAULT_CACHE_DIR


def cache_key(provider: ProviderId | str, series_id: str, start_date: date, end_date: date) -> str:
    """Clave determinista a partir de (provider, series_id, start_date, end_date)."""
    raw = f"{provider}|{series_id}|{start_date.isoformat()}|{end_date.isoformat()}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return digest


class DiskSeriesCache:
    """Guarda y recupera SeriesData con TTL por proveedor. Reloj inyectable para tests."""

    def __init__(
        self,
        cache_dir: Path | str | None = None,
        *,
        default_ttl_seconds: int = DEFAULT_TTL_SECONDS,
        provider_ttl_seconds: dict[str, int] | None = None,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        if default_ttl_seconds < 0:
            raise ValueError("default_ttl_seconds no puede ser negativo")
        self._cache_dir = Path(cache_dir) if cache_dir is not None else default_cache_dir()
        self._default_ttl = default_ttl_seconds
        self._provider_ttl = dict(provider_ttl_seconds or {})
        self._now_fn = now_fn or (lambda: datetime.now(UTC))

    @property
    def cache_dir(self) -> Path:
        return self._cache_dir

    def ttl_for(self, provider: ProviderId | str) -> int:
        """TTL efectivo. `argentinadatos` nunca baja de 3 h."""
        ttl = self._provider_ttl.get(str(provider), self._default_ttl)
        if str(provider) == "argentinadatos":
            return max(ttl, ARGENTINADATOS_MIN_TTL_SECONDS)
        return ttl

    def _path_for(self, key: str) -> Path:
        return self._cache_dir / f"{key}.json"

    def get(
        self,
        provider: ProviderId | str,
        series_id: str,
        start_date: date,
        end_date: date,
    ) -> SeriesData | None:
        """Hit si el archivo existe, valida y no expiró; miss seguro ante corrupción."""
        key = cache_key(provider, series_id, start_date, end_date)
        path = self._path_for(key)
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            cached_at = datetime.fromisoformat(payload["cached_at"])
            if cached_at.tzinfo is None:
                cached_at = cached_at.replace(tzinfo=UTC)
            # JSON serializa fechas a str: validar sin strict para permitir coerción.
            series = SeriesData.model_validate(payload["data"], strict=False)
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError, ValidationError):
            return None

        age = self._now_fn() - cached_at
        if age > timedelta(seconds=self.ttl_for(provider)):
            return None
        return series

    def put(
        self,
        provider: ProviderId | str,
        series_id: str,
        start_date: date,
        end_date: date,
        series: SeriesData,
    ) -> Path:
        """Persiste SeriesData con marca de tiempo UTC. Crea el directorio si hace falta."""
        key = cache_key(provider, series_id, start_date, end_date)
        path = self._path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        envelope = {
            "cached_at": self._now_fn().astimezone(UTC).isoformat(),
            "provider": str(provider),
            "series_id": series_id,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "data": series.model_dump(mode="json"),
        }
        path.write_text(json.dumps(envelope, ensure_ascii=False, indent=2), encoding="utf-8")
        return path
