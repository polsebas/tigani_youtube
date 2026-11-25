"""Lista blanca fail-closed de licencias y MIME types seguros para YouTube."""

from __future__ import annotations

import re

ALLOWED_MIME_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})

_CANONICAL_CODES = frozenset({"PD", "CC0", "CC-BY", "CC-BY-SA"})

# Restricciones explícitas: cualquier match implica rechazo inmediato.
_REJECT_PATTERN = re.compile(
    r"(?:"
    r"\bnc\b|non[\s\-]?commercial|"
    r"\bnd\b|no[\s\-]?deriv|"
    r"fair[\s\-]?use|"
    r"all[\s\-]?rights[\s\-]?reserved|"
    r"copyrighted"
    r")",
    re.IGNORECASE,
)

# Normaliza separadores para comparar variantes Wikimedia / Openverse.
_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_CC_BY_VERSION = re.compile(r"^(?:cc)?by\d+$")
_CC_BY_SA_VERSION = re.compile(r"^(?:cc)?bysa\d+$")


def is_allowed_mime_type(mime_type: str | None) -> bool:
    """True si el Content-Type (sin parámetros) está en la lista blanca de imagen."""
    if mime_type is None:
        return False
    base = mime_type.split(";", 1)[0].strip().casefold()
    return base in ALLOWED_MIME_TYPES


def normalize_and_validate_license(raw_license: str | None) -> str | None:
    """Devuelve el código canónico si la licencia está en la lista blanca; si no, None."""
    if raw_license is None:
        return None
    stripped = raw_license.strip()
    if stripped == "":
        return None

    if _REJECT_PATTERN.search(stripped):
        return None

    compact = _NON_ALNUM.sub("", stripped.casefold())

    # Dominio público / Public Domain Mark (Openverse `pdm`) y variantes PD-* de Commons.
    if compact in {"pd", "pdm", "publicdomain"} or (
        compact.startswith("pd") and compact[2:].isalnum()
    ):
        return "PD"

    if compact in {"cc0", "cczero"}:
        return "CC0"

    # Openverse corto (`by`) + CC BY con o sin versión.
    if compact in {"by", "ccby"} or _CC_BY_VERSION.fullmatch(compact):
        return "CC-BY"

    # Openverse corto (`by-sa`) + CC BY-SA con o sin versión.
    if compact in {"bysa", "ccbysa"} or _CC_BY_SA_VERSION.fullmatch(compact):
        return "CC-BY-SA"

    return None


def is_license_allowed(raw_license: str | None) -> bool:
    """True si `normalize_and_validate_license` produce un código canónico permitido."""
    code = normalize_and_validate_license(raw_license)
    return code in _CANONICAL_CODES
