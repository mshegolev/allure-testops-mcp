"""Actionable error messages for Allure TestOps HTTP errors."""

from __future__ import annotations

import requests


class ConfigError(ValueError):
    """Raised when required environment variables are missing or malformed.

    Subclass of :class:`ValueError` so existing code continues to work, but
    narrow enough that :func:`handle` can distinguish config errors from
    Pydantic validation errors bubbling up from tool input.
    """


def handle(exc: Exception, action: str) -> str:
    """Convert an exception raised while performing ``action`` into an
    LLM-readable string with a suggested next step.

    The goal is that the agent sees *why* the call failed and *what it could
    do about it* without needing to inspect a Python traceback.
    """
    if isinstance(exc, ConfigError):
        return (
            f"Error: configuration problem while {action} — {exc}. "
            "Check ALLURE_URL, ALLURE_TOKEN, ALLURE_SSL_VERIFY environment variables."
        )

    if isinstance(exc, requests.HTTPError):
        code = exc.response.status_code if exc.response is not None else None
        if code == 401:
            return (
                f"Error: authentication failed (HTTP 401) while {action}. "
                "Verify that ALLURE_TOKEN is set, not expired, and has API scope "
                "(generate in Profile -> API tokens)."
            )
        if code == 403:
            return (
                f"Error: forbidden (HTTP 403) while {action}. "
                "Your token does not have permission for this resource — "
                "check project membership or use a broader-scoped token."
            )
        if code == 404:
            return (
                f"Error: resource not found (HTTP 404) while {action}. "
                "Check project_id / launch_id / IDs and spelling. "
                "Use allure_list_projects to discover valid project IDs."
            )
        if code == 429:
            return (
                f"Error: rate-limited (HTTP 429) while {action}. "
                "Wait 30-60s before retrying, reduce the `size` parameter, "
                "or paginate with smaller page sizes."
            )
        if code is not None and 500 <= code < 600:
            return (
                f"Error: Allure TestOps server error (HTTP {code}) while {action}. "
                "This is usually transient — retry in a few seconds."
            )
        body = ""
        if exc.response is not None:
            try:
                body = exc.response.text[:200]
            except Exception:
                pass
        return f"Error: HTTP {code} while {action}. Response: {body}"

    if isinstance(exc, requests.ConnectionError):
        return (
            f"Error: could not connect to Allure TestOps while {action}. "
            "Check ALLURE_URL, network access, proxy settings "
            "(HTTP_PROXY / HTTPS_PROXY env vars may block direct access)."
        )

    if isinstance(exc, requests.Timeout):
        return (
            f"Error: request timed out while {action}. "
            "Check network latency and retry; reduce page size if pulling large result sets."
        )

    # Pydantic ValidationError and other ValueError subclasses (not ConfigError)
    # surface through FastMCP's own validation layer before reaching us; any
    # ValueError arriving here is unexpected and gets the generic path.
    return f"Error: unexpected {type(exc).__name__} while {action}: {exc}"
