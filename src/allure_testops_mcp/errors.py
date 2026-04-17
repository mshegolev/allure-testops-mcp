"""Actionable error messages for Allure TestOps HTTP errors."""

from __future__ import annotations

import requests


def handle(exc: Exception, action: str) -> str:
    """Convert an exception raised while performing ``action`` into an
    LLM-readable string with a suggested next step.
    """
    if isinstance(exc, ValueError):
        return f"Error: configuration problem — {exc}"

    if isinstance(exc, requests.HTTPError):
        code = exc.response.status_code if exc.response is not None else None
        if code == 401:
            return (
                f"Error: authentication failed (HTTP 401) while {action}. "
                "Verify that ALLURE_TOKEN is set, not expired, and has API scope."
            )
        if code == 403:
            return (
                f"Error: forbidden (HTTP 403) while {action}. "
                "Your token does not have permission for this resource."
            )
        if code == 404:
            return (
                f"Error: resource not found (HTTP 404) while {action}. "
                "Check project_id / launch_id / IDs and spelling."
            )
        if code == 429:
            return (
                f"Error: rate-limited (HTTP 429) while {action}. "
                "Wait 30-60s before retrying, reduce page size, or make fewer calls."
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
            "Check ALLURE_URL, network access, proxy settings."
        )

    if isinstance(exc, requests.Timeout):
        return f"Error: request timed out while {action}. Check network and retry."

    return f"Error: unexpected {type(exc).__name__} while {action}: {exc}"
