"""Unit tests for :mod:`allure_testops_mcp.client`.

Pure-Python tests with no network access — exercise input validation,
env-var parsing, and bool coercion.
"""

from __future__ import annotations

import pytest
from allure_testops_mcp.client import _parse_bool, _validate_url
from allure_testops_mcp.errors import ConfigError

# ── _parse_bool ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "value,default,expected",
    [
        (None, True, True),
        (None, False, False),
        ("", True, True),
        ("", False, False),
        ("true", False, True),
        ("True", False, True),
        ("TRUE", False, True),
        ("1", False, True),
        ("yes", False, True),
        ("YES", False, True),
        ("on", False, True),
        ("false", True, False),
        ("False", True, False),
        ("0", True, False),
        ("no", True, False),
        ("NO", True, False),
        ("off", True, False),
        (True, False, True),
        (False, True, False),
    ],
)
def test_parse_bool(value, default, expected):
    assert _parse_bool(value, default=default) is expected


# ── _validate_url ───────────────────────────────────────────────────────────


def test_validate_url_accepts_https():
    assert _validate_url("https://allure.example.com") == "https://allure.example.com"


def test_validate_url_accepts_http():
    assert _validate_url("http://localhost:8080") == "http://localhost:8080"


def test_validate_url_strips_trailing_slash():
    assert _validate_url("https://allure.example.com/") == "https://allure.example.com"


def test_validate_url_strips_whitespace():
    assert _validate_url("  https://allure.example.com  ") == "https://allure.example.com"


def test_validate_url_empty_raises():
    with pytest.raises(ConfigError, match="ALLURE_URL is not set"):
        _validate_url("")


def test_validate_url_missing_scheme_raises():
    with pytest.raises(ConfigError, match="must start with http"):
        _validate_url("allure.example.com")


def test_validate_url_unsupported_scheme_raises():
    with pytest.raises(ConfigError, match="must start with http"):
        _validate_url("ftp://allure.example.com")


def test_validate_url_missing_host_raises():
    with pytest.raises(ConfigError, match="missing host"):
        _validate_url("https://")
