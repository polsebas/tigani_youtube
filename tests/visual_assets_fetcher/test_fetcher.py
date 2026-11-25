"""VisualAssetFetcher: filtro, ranking, fallback y descarga segura (offline)."""

from pathlib import Path

import httpx
import pytest

from tigani_broadcast.visual_assets_fetcher.cache import DiskVisualSearchCache
from tigani_broadcast.visual_assets_fetcher.models import VisualProviderId, VisualQueryPlan
from tigani_broadcast.visual_assets_fetcher.providers.base import (
    VisualCandidate,
    VisualProviderError,
    VisualProviderResponseError,
)
from tigani_broadcast.visual_assets_fetcher.providers.fetcher import VisualAssetFetcher
from tigani_broadcast.visual_assets_fetcher.providers.openverse import OpenverseProvider
from tigani_broadcast.visual_assets_fetcher.providers.wikimedia import WikimediaCommonsProvider


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


class _FakeProvider:
    def __init__(
        self,
        candidates: list[VisualCandidate] | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.candidates = candidates or []
        self.error = error
        self.calls = 0

    def search(self, query: str, *, limit: int = 10) -> list[VisualCandidate]:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return list(self.candidates)


def _plan(
    query: str = "gobierno",
    provider: VisualProviderId = "wikimedia",
) -> VisualQueryPlan:
    return VisualQueryPlan(
        search_query=query,
        preferred_provider=provider,
        rationale="test",
    )


def _image_bytes(size: int = 64) -> bytes:
    return b"\xff\xd8\xff" + (b"\x00" * size)


def test_selecciona_mejor_candidato_horizontal_y_descarga(tmp_path: Path) -> None:
    image_url = "https://cdn.example/best.jpg"
    providers = {
        "wikimedia": _FakeProvider(
            [
                _candidate(
                    title="narrow",
                    image_url="https://cdn.example/narrow.jpg",
                    width=700,
                    height=400,
                ),
                _candidate(
                    title="best",
                    image_url=image_url,
                    width=1600,
                    height=900,
                    raw_license="CC BY-SA 3.0",
                ),
                _candidate(
                    title="portrait",
                    image_url="https://cdn.example/portrait.jpg",
                    width=900,
                    height=1400,
                ),
            ]
        ),
        "openverse": _FakeProvider([]),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == image_url
        return httpx.Response(
            200,
            content=_image_bytes(),
            headers={"content-type": "image/jpeg"},
        )

    fetcher = VisualAssetFetcher(providers, transport=httpx.MockTransport(handler))
    try:
        result = fetcher.fetch_for_plan(
            _plan(),
            images_dir=tmp_path / "images",
            filename_stem="ch0_gobierno",
        )
    finally:
        fetcher.close()

    assert result is not None
    attribution, path = result
    assert attribution.license_code == "CC-BY-SA"
    assert attribution.width == 1600
    assert path.name == "ch0_gobierno.jpg"
    assert path.is_file()


def test_rechaza_nc_svg_y_ancho_menor(tmp_path: Path) -> None:
    providers = {
        "wikimedia": _FakeProvider(
            [
                _candidate(raw_license="CC BY-NC 4.0", width=2000),
                _candidate(mime_type="image/svg+xml", width=2000),
                _candidate(width=320, height=200),
            ]
        ),
        "openverse": _FakeProvider([]),
    }
    fetcher = VisualAssetFetcher(
        providers,
        transport=httpx.MockTransport(lambda r: httpx.Response(500)),
    )
    try:
        assert (
            fetcher.fetch_for_plan(
                _plan(),
                images_dir=tmp_path / "images",
                filename_stem="x",
            )
            is None
        )
    finally:
        fetcher.close()


def test_acepta_retrato_vertical_si_es_unico_valido(tmp_path: Path) -> None:
    image_url = "https://cdn.example/portrait.jpg"
    providers = {
        "wikimedia": _FakeProvider(
            [
                _candidate(
                    image_url=image_url,
                    width=800,
                    height=1200,
                    raw_license="Public domain",
                )
            ]
        ),
        "openverse": _FakeProvider([]),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=_image_bytes(),
            headers={"content-type": "image/jpeg"},
        )

    fetcher = VisualAssetFetcher(providers, transport=httpx.MockTransport(handler))
    try:
        result = fetcher.fetch_for_plan(
            _plan(),
            images_dir=tmp_path / "images",
            filename_stem="retrato",
        )
    finally:
        fetcher.close()

    assert result is not None
    attribution, _path = result
    assert attribution.height > attribution.width
    assert attribution.license_code == "PD"


def test_fallback_openverse_a_wikimedia(tmp_path: Path) -> None:
    image_url = "https://upload.wikimedia.org/fallback.jpg"
    openverse = _FakeProvider(error=VisualProviderResponseError("openverse: HTTP 503"))
    wikimedia = _FakeProvider(
        [
            _candidate(
                image_url=image_url,
                width=1024,
                height=768,
                raw_license="CC0",
            )
        ]
    )
    providers = {"openverse": openverse, "wikimedia": wikimedia}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=_image_bytes(),
            headers={"content-type": "image/jpeg"},
        )

    fetcher = VisualAssetFetcher(providers, transport=httpx.MockTransport(handler))
    try:
        result = fetcher.fetch_for_plan(
            _plan(provider="openverse"),
            images_dir=tmp_path / "images",
            filename_stem="fallback",
        )
    finally:
        fetcher.close()

    assert openverse.calls == 1
    assert wikimedia.calls == 1
    assert result is not None
    assert result[0].provider == "wikimedia"


def test_fallback_cuando_openverse_sin_candidatos_validos(tmp_path: Path) -> None:
    image_url = "https://upload.wikimedia.org/ok.jpg"
    providers = {
        "openverse": _FakeProvider(
            [_candidate(provider="openverse", raw_license="CC BY-NC 4.0", width=2000)]
        ),
        "wikimedia": _FakeProvider(
            [_candidate(image_url=image_url, width=1280, height=720, raw_license="CC BY 4.0")]
        ),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=_image_bytes(),
            headers={"content-type": "image/png"},
        )

    fetcher = VisualAssetFetcher(providers, transport=httpx.MockTransport(handler))
    try:
        result = fetcher.fetch_for_plan(
            _plan(provider="openverse"),
            images_dir=tmp_path / "images",
            filename_stem="ov_fb",
        )
    finally:
        fetcher.close()

    assert result is not None
    assert result[0].mime_type == "image/png"
    assert result[1].suffix == ".png"


def test_wikimedia_preferred_propaga_error(tmp_path: Path) -> None:
    providers = {
        "wikimedia": _FakeProvider(error=VisualProviderResponseError("wikimedia: HTTP 500")),
        "openverse": _FakeProvider([]),
    }
    fetcher = VisualAssetFetcher(
        providers,
        transport=httpx.MockTransport(lambda r: httpx.Response(200)),
    )
    try:
        with pytest.raises(VisualProviderError, match="500"):
            fetcher.fetch_for_plan(
                _plan(provider="wikimedia"),
                images_dir=tmp_path / "images",
                filename_stem="err",
            )
    finally:
        fetcher.close()


def test_rechaza_descarga_content_type_html(tmp_path: Path) -> None:
    image_url = "https://cdn.example/not-image"
    providers = {
        "wikimedia": _FakeProvider([_candidate(image_url=image_url)]),
        "openverse": _FakeProvider([]),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"<html>nope</html>",
            headers={"content-type": "text/html"},
        )

    fetcher = VisualAssetFetcher(providers, transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(VisualProviderResponseError, match="Content-Type"):
            fetcher.fetch_for_plan(
                _plan(),
                images_dir=tmp_path / "images",
                filename_stem="html",
            )
    finally:
        fetcher.close()


def test_rechaza_descarga_mayor_a_max_bytes(tmp_path: Path) -> None:
    image_url = "https://cdn.example/big.jpg"
    providers = {
        "wikimedia": _FakeProvider([_candidate(image_url=image_url)]),
        "openverse": _FakeProvider([]),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=_image_bytes(size=200),
            headers={"content-type": "image/jpeg"},
        )

    fetcher = VisualAssetFetcher(
        providers,
        transport=httpx.MockTransport(handler),
        max_bytes=50,
    )
    try:
        with pytest.raises(VisualProviderResponseError, match="max_bytes"):
            fetcher.fetch_for_plan(
                _plan(),
                images_dir=tmp_path / "images",
                filename_stem="big",
            )
    finally:
        fetcher.close()


def test_usa_cache_en_busqueda(tmp_path: Path) -> None:
    cache = DiskVisualSearchCache(tmp_path / "cache")
    provider = _FakeProvider([_candidate(width=900, height=600)])
    providers = {"wikimedia": provider, "openverse": _FakeProvider([])}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=_image_bytes(),
            headers={"content-type": "image/jpeg"},
        )

    fetcher = VisualAssetFetcher(
        providers,
        cache=cache,
        transport=httpx.MockTransport(handler),
    )
    try:
        first = fetcher.fetch_for_plan(
            _plan(),
            images_dir=tmp_path / "images",
            filename_stem="c1",
        )
        second = fetcher.fetch_for_plan(
            _plan(),
            images_dir=tmp_path / "images",
            filename_stem="c2",
        )
    finally:
        fetcher.close()

    assert first is not None
    assert second is not None
    assert provider.calls == 1


def test_integracion_mock_transport_wikimedia_y_openverse(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "api.openverse.org" in url:
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "title": "nc only",
                            "creator": "X",
                            "license": "by-nc",
                            "foreign_landing_url": "https://example.com/nc",
                            "url": "https://cdn.openverse.org/nc.jpg",
                            "width": 2000,
                            "height": 1000,
                            "filetype": "jpg",
                        }
                    ]
                },
            )
        if "commons.wikimedia.org" in url:
            return httpx.Response(
                200,
                json={
                    "query": {
                        "pages": {
                            "1": {
                                "title": "File:Ok.jpg",
                                "imageinfo": [
                                    {
                                        "url": "https://upload.wikimedia.org/ok.jpg",
                                        "descriptionurl": (
                                            "https://commons.wikimedia.org/wiki/File:Ok.jpg"
                                        ),
                                        "width": 1280,
                                        "height": 720,
                                        "mime": "image/jpeg",
                                        "extmetadata": {
                                            "Artist": {"value": "Commons User"},
                                            "LicenseShortName": {"value": "CC BY 4.0"},
                                            "LicenseUrl": {
                                                "value": (
                                                    "https://creativecommons.org/licenses/by/4.0/"
                                                )
                                            },
                                        },
                                    }
                                ],
                            }
                        }
                    }
                },
            )
        if url.endswith("/ok.jpg"):
            return httpx.Response(
                200,
                content=_image_bytes(),
                headers={"content-type": "image/jpeg"},
            )
        return httpx.Response(404, text="missing")

    transport = httpx.MockTransport(handler)
    openverse = OpenverseProvider(transport=transport)
    wikimedia = WikimediaCommonsProvider(transport=transport)
    fetcher = VisualAssetFetcher(
        {"openverse": openverse, "wikimedia": wikimedia},
        transport=transport,
    )
    try:
        result = fetcher.fetch_for_plan(
            _plan(provider="openverse"),
            images_dir=tmp_path / "images",
            filename_stem="integ",
        )
    finally:
        fetcher.close()
        openverse.close()
        wikimedia.close()

    assert result is not None
    assert result[0].provider == "wikimedia"
    assert result[0].author == "Commons User"
