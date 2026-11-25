"""Conector Openverse API de imágenes (sin auth; filtra licencias seguras en query)."""

from __future__ import annotations

import httpx

from tigani_broadcast.visual_assets_fetcher.providers.base import (
    DEFAULT_TIMEOUT,
    VisualCandidate,
    VisualProviderResponseError,
    build_http_client,
    request_json,
)

OPENVERSE_IMAGES_URL = "https://api.openverse.org/v1/images/"
OPENVERSE_LICENSE_FILTER = "cc0,pdm,by,by-sa"
_FALLBACK_AUTHOR = "Openverse contributor"

_FILETYPE_TO_MIME = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "svg": "image/svg+xml",
    "gif": "image/gif",
}


class OpenverseProvider:
    """Busca imágenes en Openverse con filtro de licencias comerciales seguras."""

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: httpx.Timeout | float = DEFAULT_TIMEOUT,
        base_url: str = OPENVERSE_IMAGES_URL,
    ) -> None:
        self._client, self._owns_client = build_http_client(
            client=client,
            transport=transport,
            timeout=timeout,
        )
        self._base_url = base_url if base_url.endswith("/") else f"{base_url}/"

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def search(self, query: str, *, limit: int = 10) -> list[VisualCandidate]:
        if limit < 1:
            raise VisualProviderResponseError("openverse: limit debe ser >= 1")
        cleaned = query.strip()
        if cleaned == "":
            raise VisualProviderResponseError("openverse: query no puede ser vacía")

        params = {
            "q": cleaned,
            "license": OPENVERSE_LICENSE_FILTER,
            "page_size": str(limit),
        }
        payload = request_json(
            self._client,
            "GET",
            self._base_url,
            provider="openverse",
            params=params,
        )
        return _parse_openverse_payload(payload)


def _parse_openverse_payload(payload: object) -> list[VisualCandidate]:
    if not isinstance(payload, dict):
        raise VisualProviderResponseError("openverse: payload raíz no es un objeto JSON")
    results = payload.get("results")
    if results is None:
        return []
    if not isinstance(results, list):
        raise VisualProviderResponseError("openverse: results no es una lista JSON")

    candidates: list[VisualCandidate] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        candidate = _candidate_from_result(item)
        if candidate is not None:
            candidates.append(candidate)
    return candidates


def _candidate_from_result(item: dict[str, object]) -> VisualCandidate | None:
    width = _as_positive_int(item.get("width"))
    height = _as_positive_int(item.get("height"))
    if width is None or height is None:
        return None

    image_url = _as_nonempty_str(item.get("url"))
    source_page_url = _as_nonempty_str(item.get("foreign_landing_url"))
    raw_license_base = _as_nonempty_str(item.get("license"))
    if image_url is None or source_page_url is None or raw_license_base is None:
        return None

    license_version = _as_nonempty_str(item.get("license_version"))
    raw_license = (
        f"{raw_license_base} {license_version}" if license_version is not None else raw_license_base
    )
    license_url = _as_nonempty_str(item.get("license_url"))
    author = _as_nonempty_str(item.get("creator")) or _FALLBACK_AUTHOR
    title = _as_nonempty_str(item.get("title")) or "Untitled"
    mime_type = _mime_from_filetype(_as_nonempty_str(item.get("filetype")))

    return VisualCandidate(
        provider="openverse",
        title=title,
        author=author,
        raw_license=raw_license,
        license_url=license_url,
        source_page_url=source_page_url,
        image_url=image_url,
        width=width,
        height=height,
        mime_type=mime_type,
    )


def _mime_from_filetype(filetype: str | None) -> str | None:
    if filetype is None:
        return None
    return _FILETYPE_TO_MIME.get(filetype.casefold())


def _as_nonempty_str(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped if stripped else None


def _as_positive_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, float) and value.is_integer():
        as_int = int(value)
        return as_int if as_int > 0 else None
    return None
