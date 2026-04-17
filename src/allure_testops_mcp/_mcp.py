"""Shared FastMCP instance and client cache."""

from __future__ import annotations

import logging
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from mcp.server.fastmcp import FastMCP

from allure_testops_mcp.client import AllureClient

logger = logging.getLogger(__name__)

_client: AllureClient | None = None
_client_lock = threading.Lock()


@asynccontextmanager
async def app_lifespan(_app: FastMCP) -> AsyncIterator[dict[str, Any]]:
    """Server lifespan: close HTTP session on shutdown."""
    logger.debug("allure_testops_mcp: startup")
    try:
        yield {}
    finally:
        global _client
        with _client_lock:
            if _client is not None:
                try:
                    _client.close()
                except Exception:
                    pass
                _client = None
        logger.debug("allure_testops_mcp: shutdown — HTTP session closed")


mcp = FastMCP("allure_testops_mcp", lifespan=app_lifespan)


def get_client() -> AllureClient:
    """Return a cached :class:`AllureClient` (thread-safe lazy-init).

    FastMCP runs synchronous tools in worker threads via
    ``anyio.to_thread.run_sync``; concurrent first-calls could otherwise
    race on the ``_client`` global. The lock ensures exactly one instance
    is constructed.
    """
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:  # double-checked locking
                _client = AllureClient()
    return _client


def pagination_from(data: dict[str, Any]) -> dict[str, Any]:
    """Extract a pagination summary from an Allure list response.

    Allure's Spring Data-style responses include ``totalElements``, ``size``,
    ``number`` (0-based page index), and ``totalPages``. This helper maps
    those to the MCP-canonical shape — ``page`` / ``size`` / ``total`` /
    ``total_pages`` / ``has_more`` / ``next_page`` — tolerating missing or
    zero-valued fields.

    Returns:
        dict with keys:
            - ``page`` (int): current 0-based page
            - ``size`` (int): items per page
            - ``total`` (int): total elements across all pages
            - ``total_pages`` (int): total page count
            - ``has_more`` (bool): whether a next page exists
            - ``next_page`` (int | None): next page index if any
    """
    total = int(data.get("totalElements", 0) or 0)
    size = int(data.get("size", 0) or 0)
    page = int(data.get("number", 0) or 0)
    total_pages = int(data.get("totalPages", 0) or 0)

    # Normalise: if total_pages was not reported, infer from total/size.
    if total_pages == 0 and size > 0:
        total_pages = (total + size - 1) // size

    has_more = total_pages > 0 and page < total_pages - 1
    return {
        "page": page,
        "size": size,
        "total": total,
        "total_pages": total_pages,
        "has_more": has_more,
        "next_page": page + 1 if has_more else None,
    }
