"""HTTP client for Allure TestOps REST API.

Thin wrapper around :mod:`requests` — reads configuration from environment
variables, adds the ``Api-Token`` header, handles SSL-verify toggling, and
propagates :class:`requests.HTTPError` (mapped later to actionable messages
by :mod:`allure_testops_mcp.errors`).

**Threading model.** The client uses ``requests`` (synchronous) rather than
``httpx.AsyncClient``. FastMCP runs every synchronous ``@mcp.tool`` in a
worker thread via ``anyio.to_thread.run_sync`` — so synchronous HTTP calls
do not block the asyncio event loop. This keeps the code simple and matches
how other Python MCP servers (e.g. ``gitlab-ci-mcp``) handle the tradeoff
between convenience and concurrency. If true async is needed later, swap
``requests`` for ``httpx.AsyncClient`` and change the tool signatures to
``async def``.
"""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

import requests
import urllib3

from allure_testops_mcp.errors import ConfigError


def _parse_bool(value: str | bool | None, *, default: bool) -> bool:
    """Parse an env-var boolean (``true`` / ``false`` / ``1`` / ``0`` / ``yes`` / ``no``).

    Returns ``default`` when ``value`` is ``None`` or empty.
    """
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in ("false", "0", "no", "off")


def _validate_url(url: str) -> str:
    """Validate that ``url`` is a well-formed HTTP/HTTPS URL and return it
    stripped of any trailing slash.

    Raises :class:`ConfigError` if the URL is missing scheme/netloc or uses
    an unsupported scheme.
    """
    if not url:
        raise ConfigError("ALLURE_URL is not set — configure the env var")

    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        raise ConfigError(
            f"ALLURE_URL must start with http:// or https:// (got: {url!r})"
        )
    if not parsed.netloc:
        raise ConfigError(f"ALLURE_URL is missing host (got: {url!r})")
    return url.rstrip("/")


class AllureClient:
    """Minimal Allure TestOps REST client.

    The client reads ``ALLURE_URL``, ``ALLURE_TOKEN`` and ``ALLURE_SSL_VERIFY``
    from the process environment on first access. Instances are safe to reuse
    — a single :class:`requests.Session` is kept for connection pooling.

    Args:
        url: Override ``ALLURE_URL`` env var. If ``None``, read from env.
        token: Override ``ALLURE_TOKEN``. If ``None``, read from env.
        ssl_verify: Override ``ALLURE_SSL_VERIFY``. If ``None``, read from env
            (accepts ``true``/``false``/``1``/``0``/``yes``/``no``, default ``True``).

    Raises:
        ConfigError: If required env vars are missing or URL is malformed.
    """

    def __init__(
        self,
        url: str | None = None,
        token: str | None = None,
        ssl_verify: bool | None = None,
    ) -> None:
        raw_url = url if url is not None else os.environ.get("ALLURE_URL", "")
        self.url = _validate_url(raw_url)

        self.token = token if token is not None else os.environ.get("ALLURE_TOKEN", "")
        if not self.token:
            raise ConfigError("ALLURE_TOKEN is not set — configure the env var")

        if ssl_verify is None:
            ssl_verify = _parse_bool(os.environ.get("ALLURE_SSL_VERIFY"), default=True)
        self.ssl_verify = ssl_verify

        self.base = f"{self.url}/api/rs"
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Api-Token {self.token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        )
        self.session.verify = self.ssl_verify
        # Corporate MCP use-case: Allure is typically reachable only directly,
        # not through the workstation HTTP(S)_PROXY. Disable env-based proxy
        # discovery so the session doesn't hit 127.0.0.1:NNNN.
        self.session.trust_env = False

        if not self.ssl_verify:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """Perform ``GET {base}/{path}`` and return parsed JSON.

        Raises :class:`requests.HTTPError` on 4xx/5xx (caller maps it to a
        user-facing message via :mod:`allure_testops_mcp.errors`).
        """
        response = self.session.get(
            f"{self.base}/{path.lstrip('/')}",
            params=params,
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    def close(self) -> None:
        """Close the underlying HTTP session (called from lifespan on shutdown)."""
        self.session.close()
