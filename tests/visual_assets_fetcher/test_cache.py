"""DiskVisualSearchCache: hit, miss, TTL y corrupción segura."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tigani_broadcast.visual_assets_fetcher.cache import (
    DEFAULT_TTL_SECONDS,
    DiskVisualSearchCache,
    cache_key,
    default_cache_dir,
    normalize_query,
)
from tigani_broadcast.visual_assets_fetcher.providers.base import VisualCandidate


def _candidate(**overrides: object) -> VisualCandidate:
    payload: dict[str, object] = {
        "provider": "wikimedia",
        "title": "File:Example.jpg",
        "author": "Jane Doe",
        "raw_license": "CC BY 4.0",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "source_page_url": "https://commons.wikimedia.org/wiki/File:Example.jpg",
        "image_url": "https://upload.wikimedia.org/wikipedia/commons/example.jpg",
        "width": 1280,
        "height": 720,
        "mime_type": "image/jpeg",
    }
    payload.update(overrides)
    return VisualCandidate.model_validate(payload)


def test_cache_key_es_determinista() -> None:
    a = cache_key("wikimedia", "  Gobierno  ", 10)
    b = cache_key("wikimedia", "gobierno", 10)
    c = cache_key("wikimedia", "gobierno", 5)
    d = cache_key("openverse", "gobierno", 10)
    assert a == b
    assert a != c
    assert a != d
    assert normalize_query("  Foo   BAR ") == "foo bar"


def test_default_cache_dir_respeta_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("TIGANI_CACHE_DIR", raising=False)
    assert default_cache_dir() == Path(".cache/tigani_broadcast/visual_assets_fetcher")
    monkeypatch.setenv("TIGANI_CACHE_DIR", str(tmp_path / "custom"))
    assert default_cache_dir() == tmp_path / "custom"
    assert DEFAULT_TTL_SECONDS == 86_400


def test_hit_y_miss(tmp_path: Path) -> None:
    clock = {"now": datetime(2025, 6, 1, 12, 0, tzinfo=UTC)}

    def now_fn() -> datetime:
        return clock["now"]

    cache = DiskVisualSearchCache(tmp_path, now_fn=now_fn)
    assert cache.get("wikimedia", "gobierno", 10) is None

    cache.put("wikimedia", "gobierno", 10, [_candidate()])
    hit = cache.get("wikimedia", "  Gobierno ", 10)
    assert hit is not None
    assert len(hit) == 1
    assert hit[0].author == "Jane Doe"


def test_ttl_expira_con_reloj_inyectado(tmp_path: Path) -> None:
    clock = {"now": datetime(2025, 6, 1, 0, 0, tzinfo=UTC)}

    def now_fn() -> datetime:
        return clock["now"]

    cache = DiskVisualSearchCache(tmp_path, ttl_seconds=3_600, now_fn=now_fn)
    cache.put("openverse", "inflacion", 5, [_candidate(provider="openverse")])
    assert cache.get("openverse", "inflacion", 5) is not None

    clock["now"] = clock["now"] + timedelta(hours=2)
    assert cache.get("openverse", "inflacion", 5) is None


def test_json_corrupto_es_cache_miss(tmp_path: Path) -> None:
    cache = DiskVisualSearchCache(tmp_path)
    key = cache_key("wikimedia", "gobierno", 10)
    path = tmp_path / f"{key}.json"
    path.write_text("{not-json", encoding="utf-8")
    assert cache.get("wikimedia", "gobierno", 10) is None

    path.write_text(
        json.dumps({"cached_at": "2025-01-01T00:00:00+00:00", "data": [{"bad": True}]}),
        encoding="utf-8",
    )
    assert cache.get("wikimedia", "gobierno", 10) is None


def test_ttl_negativo_rechazado(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="ttl_seconds"):
        DiskVisualSearchCache(tmp_path, ttl_seconds=-1)
