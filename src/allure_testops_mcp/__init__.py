"""MCP server for Allure TestOps."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    # Single source of truth: the version declared in pyproject.toml and
    # baked into the installed distribution metadata. Deriving it here means
    # __version__ can never drift from the published package.
    __version__ = version("allure-testops-mcp")
except PackageNotFoundError:  # running from a source checkout without install
    __version__ = "0+unknown"

__all__ = ["__version__"]
