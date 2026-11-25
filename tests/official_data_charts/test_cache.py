"""DiskSeriesCache: hit, miss, TTL y corrupción segura."""

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from tigani_broadcast.official_data_charts.cache import (
    ARGENTINADATOS_MIN_TTL_SECONDS,
    DiskSeriesCache,
    cache_key,
    default_cache_dir,
)
from tigani_broadcast.official_data_charts.models import SeriesData, SeriesObservation


def _series() -> SeriesData:
    return SeriesData(
        catalog_id="ar_bcra_reservas_brutas",
        provider="bcra",
        source_tier="official_primary",
        series_id="1",
        source_url="https://api.bcra.gob.ar/estadisticas/v4.0/Monetarias/1",
        source_attribution="Fuente: BCRA",
        unit="millones de USD",
        frequency="daily",
        observations=[
            SeriesObservation(obs_date=date(2025, 1, 2), value=20_000.0),
            SeriesObservation(obs_date=date(2025, 1, 3), value=21_000.0),
        ],
    )


def test_cache_key_es_determinista() -> None:
    a = cache_key("bcra", "1", date(2025, 1, 1), date(2025, 1, 31))
    b = cache_key("bcra", "1", date(2025, 1, 1), date(2025, 1, 31))
    c = cache_key("bcra", "2", date(2025, 1, 1), date(2025, 1, 31))
    assert a == b
    assert a != c


def test_default_cache_dir_respeta_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("TIGANI_CACHE_DIR", raising=False)
    assert default_cache_dir() == Path(".cache/tigani_broadcast/official_data_charts")
    monkeypatch.setenv("TIGANI_CACHE_DIR", str(tmp_path / "custom"))
    assert default_cache_dir() == tmp_path / "custom"


def test_hit_y_miss(tmp_path: Path) -> None:
    clock = {"now": datetime(2025, 6, 1, 12, 0, tzinfo=UTC)}

    def now_fn() -> datetime:
        return clock["now"]

    cache = DiskSeriesCache(tmp_path, now_fn=now_fn)
    start, end = date(2025, 1, 1), date(2025, 1, 31)
    assert cache.get("bcra", "1", start, end) is None

    cache.put("bcra", "1", start, end, _series())
    hit = cache.get("bcra", "1", start, end)
    assert hit is not None
    assert hit.observations[0].value == 20_000.0


def test_ttl_expira_con_reloj_inyectado(tmp_path: Path) -> None:
    clock = {"now": datetime(2025, 6, 1, 0, 0, tzinfo=UTC)}

    def now_fn() -> datetime:
        return clock["now"]

    cache = DiskSeriesCache(tmp_path, default_ttl_seconds=3_600, now_fn=now_fn)
    start, end = date(2025, 1, 1), date(2025, 1, 31)
    cache.put("bcra", "1", start, end, _series())
    assert cache.get("bcra", "1", start, end) is not None

    clock["now"] = clock["now"] + timedelta(hours=2)
    assert cache.get("bcra", "1", start, end) is None


def test_argentinadatos_ttl_minimo_3h(tmp_path: Path) -> None:
    cache = DiskSeriesCache(
        tmp_path,
        default_ttl_seconds=60,
        provider_ttl_seconds={"argentinadatos": 60},
    )
    assert cache.ttl_for("argentinadatos") == ARGENTINADATOS_MIN_TTL_SECONDS
    assert cache.ttl_for("bcra") == 60

    clock = {"now": datetime(2025, 6, 1, 0, 0, tzinfo=UTC)}

    def now_fn() -> datetime:
        return clock["now"]

    cache = DiskSeriesCache(
        tmp_path,
        provider_ttl_seconds={"argentinadatos": 60},
        now_fn=now_fn,
    )
    start, end = date(2025, 1, 1), date(2025, 1, 2)
    series = _series().model_copy(update={"provider": "argentinadatos", "series_id": "riesgo-pais"})
    cache.put("argentinadatos", "riesgo-pais", start, end, series)
    clock["now"] = clock["now"] + timedelta(hours=2)
    assert cache.get("argentinadatos", "riesgo-pais", start, end) is not None
    clock["now"] = clock["now"] + timedelta(hours=2)
    assert cache.get("argentinadatos", "riesgo-pais", start, end) is None


def test_ttl_negativo_y_naive_cached_at(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="negativo"):
        DiskSeriesCache(tmp_path, default_ttl_seconds=-1)

    cache = DiskSeriesCache(tmp_path, now_fn=lambda: datetime(2025, 6, 1, tzinfo=UTC))
    assert cache.cache_dir == tmp_path
    start, end = date(2025, 1, 1), date(2025, 1, 2)
    key = cache_key("bcra", "1", start, end)
    path = tmp_path / f"{key}.json"
    path.write_text(
        json.dumps(
            {
                "cached_at": "2025-06-01T00:00:00",
                "data": _series().model_dump(mode="json"),
            }
        ),
        encoding="utf-8",
    )
    assert cache.get("bcra", "1", start, end) is not None


def test_json_corrupto_es_miss_seguro(tmp_path: Path) -> None:
    cache = DiskSeriesCache(tmp_path)
    start, end = date(2025, 1, 1), date(2025, 1, 31)
    key = cache_key("bcra", "1", start, end)
    path = tmp_path / f"{key}.json"
    path.write_text("{no es json", encoding="utf-8")
    assert cache.get("bcra", "1", start, end) is None

    path.write_text('{"cached_at": "2025-01-01T00:00:00+00:00", "data": {}}', encoding="utf-8")
    assert cache.get("bcra", "1", start, end) is None
