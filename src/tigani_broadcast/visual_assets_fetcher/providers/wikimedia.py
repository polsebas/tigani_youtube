"""Conector Wikimedia Commons API (sin auth; User-Agent obligatorio + rate limit)."""

from __future__ import annotations

import html
import re
import time
from collections.abc import Callable

import httpx

from tigani_broadcast.visual_assets_fetcher.licenses import is_allowed_mime_type
from tigani_broadcast.visual_assets_fetcher.providers.base import (
    DEFAULT_TIMEOUT,
    DEFAULT_USER_AGENT,
    VisualCandidate,
    VisualProviderRateLimitError,
    VisualProviderResponseError,
    build_http_client,
    get_json,
    parse_retry_after_seconds,
    raise_for_http_status,
    request_response,
    wait_min_interval,
)

WIKIMEDIA_API_URL = "https://commons.wikimedia.org/w/api.php"
_HTML_TAG = re.compile(r"<[^>]+>")
_FALLBACK_AUTHOR = "Wikimedia Commons contributor"


class WikimediaCommonsProvider:
    """Busca archivos en Wikimedia Commons vía `generator=search` + `imageinfo`."""

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: httpx.Timeout | float = DEFAULT_TIMEOUT,
        base_url: str = WIKIMEDIA_API_URL,
        min_interval_seconds: float = 1.0,
        max_retries: int = 2,
        sleep_fn: Callable[[float], None] = time.sleep,
        monotonic_fn: Callable[[], float] = time.monotonic,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        if min_interval_seconds < 0:
            raise ValueError("min_interval_seconds no puede ser negativo")
        if max_retries < 0:
            raise ValueError("max_retries no puede ser negativo")
        self._client, self._owns_client = build_http_client(
            client=client,
            transport=transport,
            timeout=timeout,
            headers={"User-Agent": user_agent},
        )
        self._base_url = base_url.rstrip("/")
        self._min_interval_seconds = min_interval_seconds
        self._max_retries = max_retries
        self._sleep_fn = sleep_fn
        self._monotonic_fn = monotonic_fn
        self._user_agent = user_agent
        self._last_request_at: float | None = None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def search(self, query: str, *, limit: int = 20) -> list[VisualCandidate]:
        if limit < 1:
            raise VisualProviderResponseError("wikimedia: limit debe ser >= 1")
        cleaned = query.strip()
        if cleaned == "":
            raise VisualProviderResponseError("wikimedia: query no puede ser vacía")

        params = {
            "action": "query",
            "generator": "search",
            "gsrnamespace": "6",
            "gsrsearch": _gsrsearch_with_bitmap(cleaned),
            "gsrlimit": str(limit),
            "prop": "imageinfo",
            "iiprop": "url|size|mime|extmetadata",
            "format": "json",
        }
        payload = self._request_json(params)
        return _parse_wikimedia_payload(payload)

    def _request_json(self, params: dict[str, str]) -> object:
        headers = {"User-Agent": self._user_agent}

        for attempt in range(self._max_retries + 1):
            self._last_request_at = wait_min_interval(
                last_request_at=self._last_request_at,
                min_interval_seconds=self._min_interval_seconds,
                monotonic_fn=self._monotonic_fn,
                sleep_fn=self._sleep_fn,
            )
            response = request_response(
                self._client,
                "GET",
                self._base_url,
                provider="wikimedia",
                params=params,
                headers=headers,
            )
            self._last_request_at = self._monotonic_fn()

            if response.status_code == 429:
                if attempt >= self._max_retries:
                    break
                delay = parse_retry_after_seconds(response, attempt=attempt)
                self._sleep_fn(delay)
                continue

            raise_for_http_status(response, provider="wikimedia")
            return get_json(response, provider="wikimedia")

        raise VisualProviderRateLimitError("wikimedia: HTTP 429 rate limit")


def _parse_wikimedia_payload(payload: object) -> list[VisualCandidate]:
    if not isinstance(payload, dict):
        raise VisualProviderResponseError("wikimedia: payload raíz no es un objeto JSON")
    query = payload.get("query")
    if query is None:
        return []
    if not isinstance(query, dict):
        raise VisualProviderResponseError("wikimedia: query no es un objeto JSON")
    pages = query.get("pages")
    if pages is None:
        return []
    if not isinstance(pages, dict):
        raise VisualProviderResponseError("wikimedia: pages no es un objeto JSON")

    candidates: list[VisualCandidate] = []
    for page in pages.values():
        if not isinstance(page, dict):
            continue
        candidate = _candidate_from_page(page)
        if candidate is not None:
            candidates.append(candidate)
    return candidates


def _gsrsearch_with_bitmap(query: str) -> str:
    """Prioriza bitmaps (jpeg/png/…) para no gastar slots en PDF/SVG."""
    if "filetype:" in query.casefold():
        return query
    return f"{query} filetype:bitmap"


def _candidate_from_page(page: dict[str, object]) -> VisualCandidate | None:
    imageinfo = page.get("imageinfo")
    if not isinstance(imageinfo, list) or not imageinfo:
        return None
    info = imageinfo[0]
    if not isinstance(info, dict):
        return None

    mime_type = _as_nonempty_str(info.get("mime"))
    if mime_type is not None and not is_allowed_mime_type(mime_type):
        return None

    width = _as_positive_int(info.get("width"))
    height = _as_positive_int(info.get("height"))
    if width is None or height is None:
        return None

    image_url = _as_nonempty_str(info.get("url"))
    source_page_url = _as_nonempty_str(info.get("descriptionurl"))
    if image_url is None or source_page_url is None:
        return None

    extmetadata = info.get("extmetadata")
    meta = extmetadata if isinstance(extmetadata, dict) else {}
    raw_license = _meta_value(meta, "LicenseShortName")
    if raw_license is None:
        return None
    license_url = _meta_value(meta, "LicenseUrl")
    author = _clean_author(_meta_value(meta, "Artist"))

    title = _as_nonempty_str(page.get("title")) or "Untitled"

    return VisualCandidate(
        provider="wikimedia",
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


def _meta_value(meta: dict[str, object], key: str) -> str | None:
    entry = meta.get(key)
    if not isinstance(entry, dict):
        return None
    return _as_nonempty_str(entry.get("value"))


def _clean_author(raw: str | None) -> str:
    if raw is None:
        return _FALLBACK_AUTHOR
    text = html.unescape(_HTML_TAG.sub("", raw))
    text = " ".join(text.split()).strip()
    return text if text else _FALLBACK_AUTHOR


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
