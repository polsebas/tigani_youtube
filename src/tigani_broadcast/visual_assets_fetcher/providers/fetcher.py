"""Orquestador de búsqueda, filtro fail-closed, fallback y descarga binaria segura."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import httpx

from tigani_broadcast.visual_assets_fetcher.cache import DiskVisualSearchCache
from tigani_broadcast.visual_assets_fetcher.licenses import (
    is_allowed_mime_type,
    normalize_and_validate_license,
)
from tigani_broadcast.visual_assets_fetcher.models import (
    VisualAttribution,
    VisualProviderId,
    VisualQueryPlan,
)
from tigani_broadcast.visual_assets_fetcher.providers.base import (
    DEFAULT_TIMEOUT,
    VisualCandidate,
    VisualProvider,
    VisualProviderError,
    VisualProviderResponseError,
    build_http_client,
    request_bytes,
)

_MIME_TO_EXT = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}
_DEFAULT_SEARCH_LIMIT = 20


class VisualAssetFetcher:
    """
    Resuelve un VisualQueryPlan a imagen local + atribución.

    - Busca en preferred_provider (con caché si hay).
    - Filtra licencia/MIME/ancho mínimo fail-closed.
    - Fallback automático openverse → wikimedia.
    - Descarga binaria con tope de tamaño y Content-Type permitido.
    """

    def __init__(
        self,
        providers: Mapping[VisualProviderId, VisualProvider],
        *,
        cache: DiskVisualSearchCache | None = None,
        client: httpx.Client | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: httpx.Timeout | float = DEFAULT_TIMEOUT,
        min_width: int = 640,
        max_bytes: int = 10 * 1024 * 1024,
        search_limit: int = _DEFAULT_SEARCH_LIMIT,
    ) -> None:
        if min_width < 1:
            raise ValueError("min_width debe ser >= 1")
        if max_bytes < 1:
            raise ValueError("max_bytes debe ser >= 1")
        if search_limit < 1:
            raise ValueError("search_limit debe ser >= 1")
        self._providers = dict(providers)
        self._cache = cache
        self._client, self._owns_client = build_http_client(
            client=client,
            transport=transport,
            timeout=timeout,
        )
        self._min_width = min_width
        self._max_bytes = max_bytes
        self._search_limit = search_limit

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def fetch_for_plan(
        self,
        plan: VisualQueryPlan,
        *,
        images_dir: Path,
        filename_stem: str,
    ) -> tuple[VisualAttribution, Path] | None:
        preferred = plan.preferred_provider
        try:
            candidates = self._search(preferred, plan.search_query)
        except VisualProviderError:
            if preferred != "openverse":
                raise
            candidates = None

        chosen = self._pick_best(candidates) if candidates is not None else None
        if chosen is None and preferred == "openverse":
            fallback = self._search("wikimedia", plan.search_query)
            chosen = self._pick_best(fallback)

        if chosen is None:
            return None

        return self._download(chosen, images_dir=images_dir, filename_stem=filename_stem)

    def _search(self, provider_id: VisualProviderId, query: str) -> list[VisualCandidate]:
        cached = self._cache_get(provider_id, query)
        if cached is not None:
            return cached

        try:
            provider = self._providers[provider_id]
        except KeyError as exc:
            raise VisualProviderError(f"fetcher: proveedor no registrado: {provider_id}") from exc

        candidates = provider.search(query, limit=self._search_limit)
        self._cache_put(provider_id, query, candidates)
        return candidates

    def _pick_best(self, candidates: list[VisualCandidate]) -> VisualCandidate | None:
        valid = [c for c in candidates if self._is_candidate_eligible(c)]
        if not valid:
            return None
        valid.sort(key=self._rank_key)
        return valid[0]

    def _is_candidate_eligible(self, candidate: VisualCandidate) -> bool:
        if normalize_and_validate_license(candidate.raw_license) is None:
            return False
        # Dimensiones desconocidas: no aplicar min_width; la descarga valida MIME/bytes.
        if candidate.width is not None and candidate.width < self._min_width:
            return False
        if candidate.mime_type is None:
            return True
        return is_allowed_mime_type(candidate.mime_type)

    @staticmethod
    def _rank_key(candidate: VisualCandidate) -> tuple[int, int]:
        # Horizontal (0), vertical (1), dims desconocidas (2); luego mayor ancho.
        width = candidate.width
        height = candidate.height
        if width is None or height is None:
            return (2, 0)
        orientation = 0 if width >= height else 1
        return (orientation, -width)

    def _download(
        self,
        candidate: VisualCandidate,
        *,
        images_dir: Path,
        filename_stem: str,
    ) -> tuple[VisualAttribution, Path]:
        response = request_bytes(
            self._client,
            "GET",
            candidate.image_url,
            provider="fetcher",
        )
        if response.status_code != 200:
            raise VisualProviderResponseError(
                f"fetcher: descarga HTTP {response.status_code} inesperada"
            )

        content_type = response.headers.get("content-type")
        if not is_allowed_mime_type(content_type):
            raise VisualProviderResponseError(
                f"fetcher: Content-Type no permitido: {content_type!r}"
            )
        mime = content_type.split(";", 1)[0].strip().casefold()

        body = response.content
        if not body:
            raise VisualProviderResponseError("fetcher: cuerpo de imagen vacío")
        if len(body) > self._max_bytes:
            raise VisualProviderResponseError(
                f"fetcher: imagen excede max_bytes ({len(body)} > {self._max_bytes})"
            )

        license_code = normalize_and_validate_license(candidate.raw_license)
        if license_code is None:
            raise VisualProviderResponseError("fetcher: licencia inválida en descarga")

        ext = _MIME_TO_EXT[mime]
        images_dir.mkdir(parents=True, exist_ok=True)
        local_path = images_dir / f"{filename_stem}.{ext}"
        local_path.write_bytes(body)

        attribution = VisualAttribution(
            provider=candidate.provider,
            author=candidate.author,
            license_name=candidate.raw_license,
            license_code=license_code,
            license_url=candidate.license_url,
            source_page_url=candidate.source_page_url,
            image_url=candidate.image_url,
            width=candidate.width,
            height=candidate.height,
            mime_type=mime,
        )
        return attribution, local_path

    def _cache_get(self, provider_id: VisualProviderId, query: str) -> list[VisualCandidate] | None:
        if self._cache is None:
            return None
        return self._cache.get(provider_id, query, self._search_limit)

    def _cache_put(
        self,
        provider_id: VisualProviderId,
        query: str,
        candidates: list[VisualCandidate],
    ) -> None:
        if self._cache is None:
            return
        self._cache.put(provider_id, query, self._search_limit, candidates)
