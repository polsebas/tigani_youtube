"""Protocolo VisualProvider, candidatos y errores de dominio de los conectores HTTP."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Protocol, runtime_checkable

import httpx
from pydantic import BaseModel, ConfigDict, Field

from tigani_broadcast.visual_assets_fetcher.models import VisualProviderId

DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
# Formato recomendado por Wikimedia: App/Version (url; contact) library
DEFAULT_USER_AGENT = (
    "TiganiBroadcast/0.1 (https://example.org/tigani-broadcast; visual-assets-fetcher) httpx"
)
DEFAULT_RETRY_AFTER_MAX_SECONDS = 10.0
_HTTP_BODY_MAX_CHARS = 200
_SECRETISH = re.compile(
    r"(?i)((?:authorization|api[_-]?key|access[_-]?token)\s*[:=]\s*(?:bearer\s+)?|"
    r"bearer\s+)\S+"
)


class VisualProviderError(Exception):
    """Error base de un conector de activos visuales."""


class VisualProviderRateLimitError(VisualProviderError):
    """HTTP 429: demasiadas solicitudes."""


class VisualProviderResponseError(VisualProviderError):
    """HTTP 4xx/5xx, timeout, JSON inválido o esquema inesperado."""


class VisualCandidate(BaseModel):
    """Candidato crudo de búsqueda, antes del filtro de licencia y descarga."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    provider: VisualProviderId
    title: str = Field(min_length=1)
    author: str = Field(min_length=1)
    raw_license: str = Field(min_length=1)
    license_url: str | None = None
    source_page_url: str = Field(min_length=1)
    image_url: str = Field(min_length=1)
    width: int
    height: int
    mime_type: str | None = None


@runtime_checkable
class VisualProvider(Protocol):
    """Contrato mínimo de un conector HTTP tipado de búsqueda de imágenes."""

    def search(self, query: str, *, limit: int = 10) -> list[VisualCandidate]:
        """Busca candidatos. Fail-closed ante basura HTTP/JSON."""
        ...


def build_http_client(
    *,
    client: httpx.Client | None = None,
    transport: httpx.BaseTransport | None = None,
    timeout: httpx.Timeout | float = DEFAULT_TIMEOUT,
    headers: dict[str, str] | None = None,
) -> tuple[httpx.Client, bool]:
    """
    Devuelve `(client, owns_client)`.
    Pasá `client` o `transport`, no ambos. Si no hay ninguno, crea un client propio.
    """
    if client is not None and transport is not None:
        raise ValueError("pasar client o transport, no ambos")
    if client is not None:
        return client, False
    merged = {"User-Agent": DEFAULT_USER_AGENT}
    if headers:
        merged.update(headers)
    return (
        httpx.Client(transport=transport, timeout=timeout, headers=merged),
        True,
    )


def _sanitize_http_error_detail(
    response: httpx.Response, *, max_chars: int = _HTTP_BODY_MAX_CHARS
) -> str:
    """Extrae un fragmento truncado del body/errors sin filtrar secretos."""
    detail: object | None = None
    try:
        payload = response.json()
    except (ValueError, httpx.DecodingError):
        payload = None
    if isinstance(payload, dict):
        for key in ("errors", "message", "error", "detail", "messages"):
            if payload.get(key) is not None:
                detail = payload[key]
                break
        if detail is None:
            detail = payload
    elif payload is not None:
        detail = payload
    else:
        detail = (response.text or "").strip() or None

    if detail is None:
        return ""
    if isinstance(detail, str):
        text = detail
    else:
        try:
            text = json.dumps(detail, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            text = str(detail)

    text = _SECRETISH.sub(r"\1=***", text)
    text = " ".join(text.split())
    if len(text) > max_chars:
        return text[: max_chars - 1] + "…"
    return text


def raise_for_http_status(response: httpx.Response, *, provider: str) -> None:
    """Mapea códigos HTTP a excepciones de dominio."""
    code = response.status_code
    if code == 429:
        raise VisualProviderRateLimitError(f"{provider}: HTTP 429 rate limit")
    if code >= 400:
        detail = _sanitize_http_error_detail(response)
        if detail:
            raise VisualProviderResponseError(f"{provider}: HTTP {code} — {detail}")
        raise VisualProviderResponseError(f"{provider}: HTTP {code}")


def get_json(response: httpx.Response, *, provider: str) -> object:
    """Parsea JSON o falla cerrado."""
    try:
        return response.json()
    except (ValueError, httpx.DecodingError) as exc:
        raise VisualProviderResponseError(f"{provider}: JSON inválido") from exc


def parse_retry_after_seconds(
    response: httpx.Response,
    *,
    attempt: int,
    max_seconds: float = DEFAULT_RETRY_AFTER_MAX_SECONDS,
) -> float:
    """
    Segundos a esperar ante HTTP 429.
    Usa `Retry-After` numérico acotado a `max_seconds`; si falta, backoff `2.0 * (attempt + 1)`.
    """
    raw = response.headers.get("Retry-After")
    if raw is not None:
        try:
            parsed = float(raw.strip())
        except ValueError:
            parsed = None
        if parsed is not None and parsed >= 0:
            return min(parsed, max_seconds)
    return 2.0 * (attempt + 1)


def wait_min_interval(
    *,
    last_request_at: float | None,
    min_interval_seconds: float,
    monotonic_fn: Callable[[], float],
    sleep_fn: Callable[[float], None],
) -> float:
    """Espera el remanente del intervalo mínimo y devuelve el timestamp actual."""
    now = monotonic_fn()
    if last_request_at is not None and min_interval_seconds > 0:
        elapsed = now - last_request_at
        remaining = min_interval_seconds - elapsed
        if remaining > 0:
            sleep_fn(remaining)
            now = monotonic_fn()
    return now


def request_response(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    provider: str,
    params: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    """GET/POST con mapeo de timeouts a errores de dominio (sin mapear status)."""
    try:
        return client.request(method, url, params=params, headers=headers)
    except httpx.TimeoutException as exc:
        raise VisualProviderResponseError(f"{provider}: timeout") from exc
    except httpx.HTTPError as exc:
        raise VisualProviderResponseError(f"{provider}: error de transporte: {exc}") from exc


def request_json(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    provider: str,
    params: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> object:
    """GET/POST tipado con mapeo de timeouts y status a errores de dominio."""
    response = request_response(
        client,
        method,
        url,
        provider=provider,
        params=params,
        headers=headers,
    )
    raise_for_http_status(response, provider=provider)
    return get_json(response, provider=provider)


def request_bytes(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    provider: str,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    """GET/POST binario con mapeo de timeouts y status a errores de dominio."""
    try:
        response = client.request(method, url, headers=headers)
    except httpx.TimeoutException as exc:
        raise VisualProviderResponseError(f"{provider}: timeout") from exc
    except httpx.HTTPError as exc:
        raise VisualProviderResponseError(f"{provider}: error de transporte: {exc}") from exc
    raise_for_http_status(response, provider=provider)
    return response
