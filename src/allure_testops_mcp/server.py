"""FastMCP server entry point for Allure TestOps MCP."""

from __future__ import annotations

import os

# Importing the tools module attaches @mcp.tool decorators to the shared
# FastMCP instance. The re-exports below are for external consumers.
from allure_testops_mcp import tools as _tools  # noqa: F401
from allure_testops_mcp._mcp import app_lifespan, mcp
from allure_testops_mcp.client import _parse_bool

# Opt-in write tools (create / update / delete test case). Registered only
# when ``ALLURE_ENABLE_WRITE`` is truthy — see
# docs/superpowers/specs/2026-06-04-allure-write-test-cases-design.md.
# The conditional import is the gate: tools the server never imports are
# never exposed to the agent at all.
if _parse_bool(os.environ.get("ALLURE_ENABLE_WRITE"), default=False):
    from allure_testops_mcp import tools_write as _tools_write  # noqa: F401


def main() -> None:
    """Entry point for the ``allure-testops-mcp`` console script (stdio)."""
    mcp.run()


__all__ = ["mcp", "app_lifespan", "main"]


if __name__ == "__main__":
    main()
