"""Shared FastMCP instance and client cache."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from mcp.server.fastmcp import FastMCP

from allure_testops_mcp.client import AllureClient

logger = logging.getLogger(__name__)

_client: AllureClient | None = None


@asynccontextmanager
async def app_lifespan(_app: FastMCP) -> AsyncIterator[dict[str, Any]]:
    """Server lifespan: close HTTP session on shutdown."""
    logger.debug("allure_testops_mcp: startup")
    try:
        yield {}
    finally:
        global _client
        if _client is not None:
            try:
                _client.close()
            except Exception:
                pass
            _client = None
        logger.debug("allure_testops_mcp: shutdown — HTTP session closed")


mcp = FastMCP("allure_testops_mcp", lifespan=app_lifespan)


def get_client() -> AllureClient:
    """Return a cached :class:`AllureClient` (lazy-init on first call)."""
    global _client
    if _client is None:
        _client = AllureClient()
    return _client


def pagination_from(data: dict[str, Any]) -> dict[str, Any]:
    """Extract a pagination summary from an Allure list response."""
    total = data.get("totalElements", 0)
    size = data.get("size", 0) or 1
    page = data.get("number", 0)
    total_pages = data.get("totalPages", 1)
    return {
        "page": page,
        "size": size,
        "total": total,
        "total_pages": total_pages,
        "has_more": page < max(total_pages - 1, 0),
    }
