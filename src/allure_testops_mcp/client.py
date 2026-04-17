"""HTTP client for Allure TestOps REST API.

Thin wrapper around :mod:`requests` — reads configuration from environment
variables, adds auth header, handles SSL verify toggling, and propagates
HTTPError exceptions (mapped later to actionable messages by
:mod:`allure_testops_mcp.errors`).
"""

from __future__ import annotations

import os
from typing import Any

import requests
import urllib3


class AllureClient:
    """Minimal Allure TestOps REST client.

    The client reads ``ALLURE_URL``, ``ALLURE_TOKEN`` and ``ALLURE_SSL_VERIFY``
    from the process environment on first access. Instances are safe to reuse
    — a single :class:`requests.Session` is kept for connection pooling.
    """

    def __init__(
        self,
        url: str | None = None,
        token: str | None = None,
        ssl_verify: bool | None = None,
    ) -> None:
        self.url = (url or os.environ.get("ALLURE_URL", "")).rstrip("/")
        self.token = token or os.environ.get("ALLURE_TOKEN", "")
        if ssl_verify is None:
            env_val = os.environ.get("ALLURE_SSL_VERIFY", "true").lower()
            ssl_verify = env_val not in ("false", "0", "no")
        self.ssl_verify = ssl_verify

        if not self.url:
            raise ValueError("ALLURE_URL is not set — configure the env var")
        if not self.token:
            raise ValueError("ALLURE_TOKEN is not set — configure the env var")

        self.base = f"{self.url}/api/rs"
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Api-Token {self.token}",
                "Content-Type": "application/json",
            }
        )
        self.session.verify = self.ssl_verify
        # Ignore HTTP(S)_PROXY from env — Allure is often a corp service only
        # reachable directly.
        self.session.trust_env = False

        if not self.ssl_verify:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """Perform ``GET {base}/{path}`` and return parsed JSON.

        Raises :class:`requests.HTTPError` on 4xx/5xx — caller maps it to a
        user-facing message via :mod:`allure_testops_mcp.errors`.
        """
        r = self.session.get(f"{self.base}/{path.lstrip('/')}", params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    def close(self) -> None:
        """Close the underlying HTTP session."""
        self.session.close()
