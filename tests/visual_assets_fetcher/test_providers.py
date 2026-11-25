"""Proveedores Wikimedia y Openverse con httpx.MockTransport (100 % offline)."""

import httpx
import pytest

from tigani_broadcast.visual_assets_fetcher.providers.base import (
    DEFAULT_USER_AGENT,
    VisualProviderRateLimitError,
    VisualProviderResponseError,
    parse_retry_after_seconds,
)
from tigani_broadcast.visual_assets_fetcher.providers.openverse import (
    OPENVERSE_LICENSE_FILTER,
    OpenverseProvider,
)
from tigani_broadcast.visual_assets_fetcher.providers.wikimedia import WikimediaCommonsProvider


def _wikimedia_payload() -> dict:
    return {
        "query": {
            "pages": {
                "1": {
                    "title": "File:Casa Rosada.jpg",
                    "imageinfo": [
                        {
                            "url": "https://upload.wikimedia.org/wikipedia/commons/casa.jpg",
                            "descriptionurl": (
                                "https://commons.wikimedia.org/wiki/File:Casa_Rosada.jpg"
                            ),
                            "width": 1600,
                            "height": 900,
                            "mime": "image/jpeg",
                            "extmetadata": {
                                "Artist": {
                                    "value": (
                                        '<a href="https://commons.wikimedia.org/wiki/'
                                        'User:Example">María Pérez</a>'
                                    )
                                },
                                "LicenseShortName": {"value": "CC BY-SA 4.0"},
                                "LicenseUrl": {
                                    "value": "https://creativecommons.org/licenses/by-sa/4.0/"
                                },
                            },
                        }
                    ],
                },
                "2": {
                    "title": "File:SinInfo.jpg",
                    "imageinfo": [],
                },
                "3": {
                    "title": "File:SinDimensiones.jpg",
                    "imageinfo": [
                        {
                            "url": "https://upload.wikimedia.org/wikipedia/commons/bad.jpg",
                            "descriptionurl": "https://commons.wikimedia.org/wiki/File:bad.jpg",
                            "width": 0,
                            "height": 100,
                            "mime": "image/jpeg",
                            "extmetadata": {
                                "LicenseShortName": {"value": "CC0"},
                            },
                        }
                    ],
                },
                "4": {
                    "title": "File:SinAutor.jpg",
                    "imageinfo": [
                        {
                            "url": "https://upload.wikimedia.org/wikipedia/commons/pd.jpg",
                            "descriptionurl": "https://commons.wikimedia.org/wiki/File:pd.jpg",
                            "width": 800,
                            "height": 600,
                            "mime": "image/png",
                            "extmetadata": {
                                "Artist": {"value": "   "},
                                "LicenseShortName": {"value": "Public domain"},
                            },
                        }
                    ],
                },
            }
        }
    }


def _openverse_payload() -> dict:
    return {
        "results": [
            {
                "title": "Inflation chart concept",
                "creator": "Alex Creator",
                "license": "by",
                "license_version": "4.0",
                "license_url": "https://creativecommons.org/licenses/by/4.0/",
                "foreign_landing_url": "https://example.com/photo/1",
                "url": "https://cdn.openverse.org/photo1.jpg",
                "width": 1200,
                "height": 800,
                "filetype": "jpg",
            },
            {
                "title": "Empty creator",
                "creator": "",
                "license": "cc0",
                "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
                "foreign_landing_url": "https://example.com/photo/2",
                "url": "https://cdn.openverse.org/photo2.png",
                "width": 900,
                "height": 900,
                "filetype": "png",
            },
            {
                "title": "Bad dims",
                "creator": "X",
                "license": "pdm",
                "foreign_landing_url": "https://example.com/photo/3",
                "url": "https://cdn.openverse.org/photo3.jpg",
                "width": 0,
                "height": 500,
                "filetype": "jpg",
            },
        ]
    }


def test_wikimedia_parsea_imageinfo_y_limpia_html_artist() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "commons.wikimedia.org" in str(request.url)
        assert request.url.params["gsrnamespace"] == "6"
        assert request.url.params["gsrsearch"] == "casa rosada"
        assert request.headers["User-Agent"] == DEFAULT_USER_AGENT
        assert "TiganiBroadcast/0.1" in request.headers["User-Agent"]
        return httpx.Response(200, json=_wikimedia_payload())

    provider = WikimediaCommonsProvider(
        transport=httpx.MockTransport(handler),
        sleep_fn=lambda _s: None,
        min_interval_seconds=0.0,
    )
    try:
        results = provider.search("casa rosada", limit=5)
    finally:
        provider.close()

    assert len(results) == 2
    first = results[0]
    assert first.provider == "wikimedia"
    assert first.author == "María Pérez"
    assert first.raw_license == "CC BY-SA 4.0"
    assert first.width == 1600
    assert results[1].author == "Wikimedia Commons contributor"
    assert results[1].raw_license == "Public domain"


def test_wikimedia_429_reintenta_con_retry_after() -> None:
    calls = {"n": 0}
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, text="slow down", headers={"Retry-After": "3"})
        return httpx.Response(200, json=_wikimedia_payload())

    provider = WikimediaCommonsProvider(
        transport=httpx.MockTransport(handler),
        sleep_fn=sleeps.append,
        min_interval_seconds=0.0,
        max_retries=2,
    )
    try:
        results = provider.search("gobierno")
    finally:
        provider.close()

    assert calls["n"] == 2
    assert sleeps == [3.0]
    assert len(results) == 2


def test_wikimedia_429_agota_retries() -> None:
    sleeps: list[float] = []
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429, text="slow down")

    provider = WikimediaCommonsProvider(
        transport=httpx.MockTransport(handler),
        sleep_fn=sleeps.append,
        min_interval_seconds=0.0,
        max_retries=2,
    )
    try:
        with pytest.raises(VisualProviderRateLimitError, match="429"):
            provider.search("gobierno")
    finally:
        provider.close()

    assert calls["n"] == 3
    # sin Retry-After: backoff 2*(attempt+1) → 2.0, 4.0
    assert sleeps == [2.0, 4.0]


def test_wikimedia_respeta_min_interval_entre_busquedas() -> None:
    clock = {"t": 100.0}
    sleeps: list[float] = []

    def monotonic() -> float:
        return clock["t"]

    def sleep_fn(seconds: float) -> None:
        sleeps.append(seconds)
        clock["t"] += seconds

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_wikimedia_payload())

    provider = WikimediaCommonsProvider(
        transport=httpx.MockTransport(handler),
        sleep_fn=sleep_fn,
        monotonic_fn=monotonic,
        min_interval_seconds=1.0,
        max_retries=0,
    )
    try:
        provider.search("uno")
        clock["t"] += 0.25
        provider.search("dos")
    finally:
        provider.close()

    assert sleeps == [0.75]


def test_parse_retry_after_acota_a_maximo() -> None:
    response = httpx.Response(429, headers={"Retry-After": "60"})
    assert parse_retry_after_seconds(response, attempt=0, max_seconds=10.0) == 10.0
    response_bad = httpx.Response(429, headers={"Retry-After": "soon"})
    assert parse_retry_after_seconds(response_bad, attempt=1) == 4.0


def test_wikimedia_http_500_incluye_detalle() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "backend boom"})

    provider = WikimediaCommonsProvider(
        transport=httpx.MockTransport(handler),
        sleep_fn=lambda _s: None,
        min_interval_seconds=0.0,
    )
    try:
        with pytest.raises(VisualProviderResponseError, match="500") as exc_info:
            provider.search("gobierno")
    finally:
        provider.close()
    assert "backend boom" in str(exc_info.value)


def test_wikimedia_json_invalido() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not-json", headers={"content-type": "application/json"})

    provider = WikimediaCommonsProvider(
        transport=httpx.MockTransport(handler),
        sleep_fn=lambda _s: None,
        min_interval_seconds=0.0,
    )
    try:
        with pytest.raises(VisualProviderResponseError, match="JSON inválido"):
            provider.search("gobierno")
    finally:
        provider.close()


def test_openverse_parsea_results_y_filtra_licencias_en_query() -> None:
    seen_params: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_params.update(request.url.params)
        assert "api.openverse.org" in str(request.url)
        return httpx.Response(200, json=_openverse_payload())

    provider = OpenverseProvider(transport=httpx.MockTransport(handler))
    try:
        results = provider.search("inflation", limit=8)
    finally:
        provider.close()

    assert seen_params["q"] == "inflation"
    assert seen_params["license"] == OPENVERSE_LICENSE_FILTER
    assert seen_params["page_size"] == "8"
    assert OPENVERSE_LICENSE_FILTER == "cc0,pdm,by,by-sa"

    assert len(results) == 2
    assert results[0].raw_license == "by 4.0"
    assert results[0].mime_type == "image/jpeg"
    assert results[0].author == "Alex Creator"
    assert results[1].author == "Openverse contributor"
    assert results[1].raw_license == "cc0"
    assert results[1].mime_type == "image/png"


def test_openverse_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="unavailable")

    provider = OpenverseProvider(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(VisualProviderResponseError, match="503"):
            provider.search("concept")
    finally:
        provider.close()


def test_openverse_payload_results_no_lista() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": {"nope": True}})

    provider = OpenverseProvider(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(VisualProviderResponseError, match="results"):
            provider.search("concept")
    finally:
        provider.close()


def test_wikimedia_query_vacia_rechazada() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(200))
    provider = WikimediaCommonsProvider(
        transport=transport,
        sleep_fn=lambda _s: None,
        min_interval_seconds=0.0,
    )
    try:
        with pytest.raises(VisualProviderResponseError, match="query"):
            provider.search("   ")
    finally:
        provider.close()
