"""Conectores HTTP deterministas y orquestador con caché/fallback."""

from tigani_broadcast.visual_assets_fetcher.cache import DiskVisualSearchCache
from tigani_broadcast.visual_assets_fetcher.providers.base import (
    VisualCandidate,
    VisualProvider,
    VisualProviderError,
    VisualProviderRateLimitError,
    VisualProviderResponseError,
)
from tigani_broadcast.visual_assets_fetcher.providers.fetcher import VisualAssetFetcher
from tigani_broadcast.visual_assets_fetcher.providers.openverse import OpenverseProvider
from tigani_broadcast.visual_assets_fetcher.providers.wikimedia import WikimediaCommonsProvider

__all__ = [
    "DiskVisualSearchCache",
    "OpenverseProvider",
    "VisualAssetFetcher",
    "VisualCandidate",
    "VisualProvider",
    "VisualProviderError",
    "VisualProviderRateLimitError",
    "VisualProviderResponseError",
    "WikimediaCommonsProvider",
]
