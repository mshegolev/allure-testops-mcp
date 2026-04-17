"""Unit tests for :mod:`allure_testops_mcp.errors`.

We use :mod:`responses` to mock HTTP responses at the transport layer so
tests exercise the *real* request path (session, urllib3, raise_for_status)
instead of hand-crafted :class:`requests.Response` objects.
"""

from __future__ import annotations

import pytest
import requests
import responses

from allure_testops_mcp.errors import ConfigError, handle


@pytest.fixture
def mocked_get():
    """Yield a configured :mod:`responses` instance for a single GET call."""
    with responses.RequestsMock() as rsps:
        yield rsps


def _http_error_for(url: str, status: int, body: str = "") -> requests.HTTPError:
    """Hit ``url`` through a real requests.Session, return the HTTPError raised."""
    try:
        r = requests.Session().get(url, timeout=5)
        r.raise_for_status()
    except requests.HTTPError as exc:
        return exc
    raise AssertionError(f"expected HTTPError (status={status}, body={body!r})")


@pytest.mark.parametrize(
    "status,fragment",
    [
        (401, "ALLURE_TOKEN"),
        (403, "permission"),
        (404, "allure_list_projects"),
        (429, "rate-limited"),
        (502, "transient"),
    ],
)
def test_http_error_messages(mocked_get, status: int, fragment: str):
    url = "https://allure.test.local/api/rs/ping"
    mocked_get.add(responses.GET, url, status=status, body="boom")
    exc = _http_error_for(url, status)

    msg = handle(exc, "listing projects")
    assert str(status) in msg
    assert fragment.lower() in msg.lower()


def test_config_error_surfaces_env_hint():
    msg = handle(ConfigError("ALLURE_URL is not set"), "listing projects")
    assert "configuration problem" in msg
    assert "ALLURE_URL" in msg


def test_connection_error_is_mapped():
    exc = requests.ConnectionError("nope")
    msg = handle(exc, "listing projects")
    assert "could not connect" in msg.lower()


def test_timeout_is_mapped():
    exc = requests.Timeout("slow")
    msg = handle(exc, "listing projects")
    assert "timed out" in msg.lower()


def test_unknown_exception_has_type_name():
    msg = handle(RuntimeError("boom"), "doing X")
    assert "RuntimeError" in msg
    assert "doing X" in msg
