"""Regression tests for settings/activity/upload hardening fixes."""

import pytest
from pydantic import ValidationError

from app.api.v1.routes.settings import _detect_image_extension
from app.core.csv_safe import sanitize_csv_cell
from app.core.metadata_sanitization import sanitize_metadata
from app.modules.settings.schemas import UpdateOrganizationSettingsRequest

_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
_JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 16
_WEBP = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 8


# --- #32 magic-byte image detection -----------------------------------------


def test_detect_image_extension_uses_magic_bytes() -> None:
    assert _detect_image_extension(_PNG) == ".png"
    assert _detect_image_extension(_JPEG) == ".jpg"
    assert _detect_image_extension(_WEBP) == ".webp"
    # An SVG / HTML polyglot claiming to be a PNG is rejected.
    assert _detect_image_extension(b"<svg xmlns=...>") is None
    assert _detect_image_extension(b"<!DOCTYPE html>") is None


# --- #34 logo_url scheme validation -----------------------------------------


def test_logo_url_allows_relative_and_https_but_rejects_dangerous_schemes() -> None:
    assert (
        UpdateOrganizationSettingsRequest(
            organization_logo_url="/assets/organizations/x/org_logo.png"
        ).organization_logo_url
        == "/assets/organizations/x/org_logo.png"
    )
    assert (
        UpdateOrganizationSettingsRequest(
            organization_logo_url="https://cdn.example.com/logo.png"
        ).organization_logo_url
        == "https://cdn.example.com/logo.png"
    )
    for bad in ("javascript:alert(1)", "data:text/html,<script>", "//evil.example/logo.png"):
        with pytest.raises(ValidationError):
            UpdateOrganizationSettingsRequest(organization_logo_url=bad)


# --- #33 metadata redaction --------------------------------------------------


def test_metadata_redaction_covers_more_keys_and_values() -> None:
    sanitized = sanitize_metadata(
        {
            "apikey": "live-value",
            "pwd": "hunter2",
            "bearer": "abc",
            "secret_id": "should-redact",
            "provider_id": "keep-me",
            "note": "bab-sk-deadbeef",  # value-based backstop
        }
    )
    assert sanitized["apikey"] == "[redacted]"
    assert sanitized["pwd"] == "[redacted]"
    assert sanitized["bearer"] == "[redacted]"
    assert sanitized["secret_id"] == "[redacted]"
    assert sanitized["provider_id"] == "keep-me"  # plain entity id stays queryable
    assert sanitized["note"] == "[redacted]"  # secret-looking value redacted


# --- #28 CSV formula-injection neutralization -------------------------------


def test_csv_cell_sanitizer_neutralizes_formula_triggers() -> None:
    assert sanitize_csv_cell("=cmd|'/c calc'!A1") == "'=cmd|'/c calc'!A1"
    assert sanitize_csv_cell("+1") == "'+1"
    assert sanitize_csv_cell("@SUM(A1)") == "'@SUM(A1)"
    assert sanitize_csv_cell("safe text") == "safe text"
    assert sanitize_csv_cell(42) == 42
