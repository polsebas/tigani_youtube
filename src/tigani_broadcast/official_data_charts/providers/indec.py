"""Conector API-INDEC v1 (PostgREST) con signos convencionales oficiales."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date

import httpx

from tigani_broadcast.official_data_charts.models import (
    CatalogEntry,
    SeriesData,
    SeriesObservation,
)
from tigani_broadcast.official_data_charts.providers.base import (
    ProviderAuthError,
    ProviderResponseError,
    build_http_client,
    request_json,
)

INDEC_BASE_URL = "https://api.indec.gob.ar/v1"

# Signos convencionales documentados por el INDEC (y afines).
INDEC_FLAGS: frozenset[str] = frozenset({"*", "**", "e", "i", "u", "-", ".", "...", "///", "s"})
_FLAG_SUFFIX = re.compile(
    r"^(?P<num>[-+]?(?:\d+(?:[.,]\d+)?|\d*[.,]\d+))"
    r"(?P<flag>\*\*|\*|e|i|u|\.\.\.|///|s)?\s*$"
)


@dataclass(frozen=True, slots=True)
class _IndecQuery:
    endpoint: str
    tipo_de_indicador: str
    alcance_nombre: str = "Nacional"


# Filtros tidy curados: evitan mezclar índice base con variaciones mensuales/interanuales.
_QUERIES: dict[str, _IndecQuery] = {
    "ar_indec_ipc_mensual": _IndecQuery(
        endpoint="ipc_nacional_tidy",
        tipo_de_indicador="Variación porcentual respecto del mes anterior",
    ),
    "ar_indec_ipc_interanual": _IndecQuery(
        endpoint="ipc_nacional_tidy",
        tipo_de_indicador="Variación porcentual respecto del mismo mes del año anterior",
    ),
    "ar_indec_emae_mensual": _IndecQuery(
        endpoint="emae_tidy",
        tipo_de_indicador="Variación porcentual respecto del mes anterior",
    ),
}


class INDECProvider:
    """Consulta tablas tidy del INDEC. Exige `INDEC_API_TOKEN` (o token inyectado)."""

    def __init__(
        self,
        *,
        token: str | None = None,
        client: httpx.Client | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: httpx.Timeout | float = 30.0,
        base_url: str = INDEC_BASE_URL,
    ) -> None:
        env_token = os.environ.get("INDEC_API_TOKEN")
        resolved = token if token is not None else env_token
        self._token = resolved.strip() if isinstance(resolved, str) else None
        if self._token == "":
            self._token = None
        self._client, self._owns_client = build_http_client(
            client=client,
            transport=transport,
            timeout=timeout,
        )
        self._base_url = base_url.rstrip("/")

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def fetch_series(
        self,
        entry: CatalogEntry,
        start_date: date,
        end_date: date,
    ) -> SeriesData:
        if entry.provider != "indec":
            raise ProviderResponseError(
                f"indec: catalog_id {entry.catalog_id} no corresponde a provider indec"
            )
        if start_date > end_date:
            raise ProviderResponseError("indec: start_date no puede ser mayor que end_date")
        if self._token is None:
            raise ProviderAuthError("indec: falta INDEC_API_TOKEN")

        query = _QUERIES.get(entry.catalog_id)
        if query is None:
            raise ProviderResponseError(f"indec: no hay query tidy curada para {entry.catalog_id}")

        url = f"{self._base_url}/{query.endpoint}"
        # Filtros PostgREST: tipo + alcance + piso de período; el techo se aplica en Python.
        params = {
            "tipo_de_indicador": f"eq.{query.tipo_de_indicador}",
            "alcance_nombre": f"eq.{query.alcance_nombre}",
            "periodo": f"gte.{start_date.strftime('%Y-%m')}",
            "order": "periodo.asc",
        }
        payload = request_json(
            self._client,
            "GET",
            url,
            provider="indec",
            params=params,
            headers={"Authorization": f"Bearer {self._token}"},
        )
        observations = _parse_indec_tidy(
            payload,
            expected_tipo=query.tipo_de_indicador,
            expected_alcance=query.alcance_nombre,
            start_date=start_date,
            end_date=end_date,
        )
        if not observations:
            raise ProviderResponseError(
                f"indec: respuesta sin observaciones válidas para el rango "
                f"{start_date.isoformat()}..{end_date.isoformat()}"
            )

        return SeriesData(
            catalog_id=entry.catalog_id,
            provider="indec",
            source_tier=entry.source_tier,
            series_id=entry.series_id,
            source_url=url,
            source_attribution=entry.source_attribution,
            unit=entry.unit,
            frequency=entry.frequency,
            observations=observations,
        )


def _parse_indec_tidy(
    payload: object,
    *,
    expected_tipo: str,
    expected_alcance: str,
    start_date: date,
    end_date: date,
) -> list[SeriesObservation]:
    if not isinstance(payload, list):
        raise ProviderResponseError("indec: se esperaba una lista tidy PostgREST")

    observations: list[SeriesObservation] = []
    for row in payload:
        if not isinstance(row, dict):
            raise ProviderResponseError("indec: fila tidy inválida")
        tipo = row.get("tipo_de_indicador")
        alcance = row.get("alcance_nombre")
        if tipo != expected_tipo or alcance != expected_alcance:
            # Descarta filas de otras series (índice base, regiones, etc.).
            continue
        obs_date = _row_date(row)
        if obs_date < start_date or obs_date > end_date:
            continue
        value, flag = _parse_indec_value(row.get("valor"), row.get("signo"))
        observations.append(SeriesObservation(obs_date=obs_date, value=value, flag=flag))

    observations.sort(key=lambda obs: obs.obs_date)
    return observations


def _row_date(row: dict[str, object]) -> date:
    periodo = row.get("periodo")
    if isinstance(periodo, str) and len(periodo) >= 7:
        try:
            year = int(periodo[0:4])
            month = int(periodo[5:7])
            return date(year, month, 1)
        except ValueError as exc:
            raise ProviderResponseError(f"indec: periodo inválido: {periodo}") from exc

    anio = row.get("anio")
    mes = row.get("mes")
    try:
        return date(int(anio), int(mes), 1)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ProviderResponseError("indec: falta periodo o anio/mes válidos") from exc


def _parse_indec_value(
    valor: object,
    signo: object,
) -> tuple[float | None, str | None]:
    flag: str | None = None
    if isinstance(signo, str) and signo.strip() != "":
        flag = signo.strip()

    if valor is None:
        return None, flag
    if isinstance(valor, bool):
        raise ProviderResponseError("indec: valor booleano inesperado")
    if isinstance(valor, (int, float)):
        return float(valor), flag if flag in INDEC_FLAGS or flag is None else flag

    if not isinstance(valor, str):
        raise ProviderResponseError(f"indec: tipo de valor no soportado: {type(valor).__name__}")

    text = valor.strip()
    if text == "" or text in INDEC_FLAGS:
        return None, text if text else flag

    match = _FLAG_SUFFIX.match(text.replace(" ", ""))
    if match is None:
        # Texto no numérico residual → no disponible.
        return None, text if text in INDEC_FLAGS else flag

    num_raw = match.group("num").replace(",", ".")
    suffix = match.group("flag")
    try:
        number = float(num_raw)
    except ValueError:
        return None, suffix or flag
    resolved_flag = suffix or flag
    if resolved_flag is not None and resolved_flag.strip() == "":
        resolved_flag = None
    return number, resolved_flag
