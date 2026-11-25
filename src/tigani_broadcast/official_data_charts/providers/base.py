"""Protocolo DataProvider y errores de dominio de los conectores HTTP."""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Protocol, runtime_checkable

import httpx

from tigani_broadcast.official_data_charts.models import CatalogEntry, SeriesData

DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
_HTTP_BODY_MAX_CHARS = 200
_SECRETISH = re.compile(
    r"(?i)((?:authorization|api[_-]?key|access[_-]?token)\s*[:=]\s*(?:bearer\s+)?|"
    r"bearer\s+)\S+"
)


class ProviderError(Exception):
    """Error base de un conector de datos oficiales/mercado."""


class ProviderAuthError(ProviderError):
    """Token faltante o HTTP 401/403."""


class ProviderRateLimitError(ProviderError):
    """HTTP 429: demasiadas solicitudes."""


class ProviderResponseError(ProviderError):
    """HTTP 4xx/5xx, timeout, JSON inválido o esquema inesperado."""


@runtime_checkable
class DataProvider(Protocol):
    """Contrato mínimo de un conector HTTP tipado."""

    def fetch_series(
        self,
        entry: CatalogEntry,
        start_date: date,
        end_date: date,
    ) -> SeriesData:
        """Baja y normaliza observaciones del rango inclusive. Fail-closed ante basura."""
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
    return (
        httpx.Client(transport=transport, timeout=timeout, headers=headers),
        True,
    )


def _sanitize_http_error_detail(
    response: httpx.Response, *, max_chars: int = _HTTP_BODY_MAX_CHARS
) -> str:
    """Extrae un fragmento truncado del body/errors sin filtrar secretos ni headers."""
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
    if code in {401, 403}:
        raise ProviderAuthError(f"{provider}: HTTP {code} no autorizado")
    if code == 429:
        raise ProviderRateLimitError(f"{provider}: HTTP 429 rate limit")
    if code >= 400:
        detail = _sanitize_http_error_detail(response)
        if detail:
            raise ProviderResponseError(f"{provider}: HTTP {code} — {detail}")
        raise ProviderResponseError(f"{provider}: HTTP {code}")


def get_json(response: httpx.Response, *, provider: str) -> object:
    """Parsea JSON o falla cerrado."""
    try:
        return response.json()
    except (ValueError, httpx.DecodingError) as exc:
        raise ProviderResponseError(f"{provider}: JSON inválido") from exc


def request_response(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    provider: str,
    params: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    """GET/POST con mapeo de timeouts y status a errores de dominio."""
    try:
        response = client.request(method, url, params=params, headers=headers)
    except httpx.TimeoutException as exc:
        raise ProviderResponseError(f"{provider}: timeout") from exc
    except httpx.HTTPError as exc:
        raise ProviderResponseError(f"{provider}: error de transporte: {exc}") from exc
    raise_for_http_status(response, provider=provider)
    return response


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
    return get_json(response, provider=provider)


def request_text(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    provider: str,
    params: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> str:
    """GET/POST de cuerpo texto (CSV SDMX, Stooq, etc.)."""
    response = request_response(
        client,
        method,
        url,
        provider=provider,
        params=params,
        headers=headers,
    )
    return response.text
