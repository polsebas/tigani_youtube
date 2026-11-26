"""Lista blanca fail-closed de licencias y MIME types."""

import pytest

from tigani_broadcast.visual_assets_fetcher.licenses import (
    ALLOWED_MIME_TYPES,
    is_allowed_mime_type,
    is_license_allowed,
    normalize_and_validate_license,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Public domain", "PD"),
        ("PD-USGov", "PD"),
        ("PD-self", "PD"),
        ("PD-AR-Photo", "PD"),
        ("PD-Argentina", "PD"),
        ("pdm", "PD"),
        ("CC0", "CC0"),
        ("cc0", "CC0"),
        ("CC BY 4.0", "CC-BY"),
        ("CC-BY", "CC-BY"),
        ("by", "CC-BY"),
        ("by 4.0", "CC-BY"),
        ("CC BY 2.5 ar", "CC-BY"),
        ("CC BY 2.0 ar", "CC-BY"),
        ("CC BY 3.0 unported", "CC-BY"),
        ("CC BY 2.0 generic", "CC-BY"),
        ("CC BY-SA 3.0", "CC-BY-SA"),
        ("CC-BY-SA-3.0", "CC-BY-SA"),
        ("CC-BY-SA-2.5-ar", "CC-BY-SA"),
        ("cc by-sa 4.0", "CC-BY-SA"),
        ("by-sa", "CC-BY-SA"),
        ("by-sa 4.0", "CC-BY-SA"),
    ],
)
def test_normalize_acepta_licencias_en_lista_blanca(raw: str, expected: str) -> None:
    assert normalize_and_validate_license(raw) == expected
    assert is_license_allowed(raw) is True


@pytest.mark.parametrize(
    "raw",
    [
        "CC BY-NC 4.0",
        "CC BY-NC 2.5 ar",
        "CC BY-ND 4.0",
        "CC BY-NC-SA 4.0",
        "CC-BY-NC-SA-3.0",
        "Fair use",
        "All rights reserved",
        "copyrighted",
        "",
        None,
        "MIT",
        "GPL-3.0",
        "unknown",
    ],
)
def test_normalize_rechaza_licencias_inseguras_o_desconocidas(raw: str | None) -> None:
    assert normalize_and_validate_license(raw) is None
    assert is_license_allowed(raw) is False


def test_allowed_mime_types_frozenset() -> None:
    assert frozenset({"image/jpeg", "image/png", "image/webp"}) == ALLOWED_MIME_TYPES


@pytest.mark.parametrize(
    "mime_type",
    [
        "image/jpeg",
        "image/png",
        "image/webp",
        "image/jpeg; charset=binary",
        "IMAGE/PNG",
    ],
)
def test_mime_permitidos(mime_type: str) -> None:
    assert is_allowed_mime_type(mime_type) is True


@pytest.mark.parametrize(
    "mime_type",
    [
        "image/svg+xml",
        "text/html",
        "application/octet-stream",
        "",
        None,
    ],
)
def test_mime_rechazados(mime_type: str | None) -> None:
    assert is_allowed_mime_type(mime_type) is False
