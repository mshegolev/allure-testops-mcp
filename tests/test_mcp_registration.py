"""Verify ``ALLURE_ENABLE_WRITE`` gates registration of the write tools.

The check uses :func:`importlib.reload` on the entry-point module — the
side effect of importing ``server`` is the registration of @mcp.tool
decorators, which is what we want to flip with the env var.

We always start with a clean FastMCP instance by reloading ``_mcp``
first; otherwise the global ``mcp`` registry from earlier tests would
leak across test cases.
"""

from __future__ import annotations

import importlib

import pytest

from allure_testops_mcp import _mcp, server

READ_ONLY_TOOL_NAMES = {
    "allure_list_projects",
    "allure_get_project_statistics",
    "allure_list_launches",
    "allure_get_test_results",
    "allure_search_failed_tests",
    "allure_list_test_cases",
    "allure_list_statuses",
    "allure_list_layers",
    "allure_get_test_case",
    "allure_get_test_case_custom_fields",
}
WRITE_TOOL_NAMES = {
    "allure_create_test_case",
    "allure_update_test_case",
    "allure_delete_test_case",
}


def _reload(monkeypatch, enable_write: str | None) -> set[str]:
    """Rebuild the server module under the given env-var setting and
    return the set of registered tool names.

    Submodules must be evicted both from ``sys.modules`` AND from the
    parent package's namespace — otherwise ``from package import submod``
    inside the reloaded server uses the cached attribute instead of
    re-executing the module body (where @mcp.tool decorators register).
    """
    import sys

    import allure_testops_mcp as _pkg

    if enable_write is None:
        monkeypatch.delenv("ALLURE_ENABLE_WRITE", raising=False)
    else:
        monkeypatch.setenv("ALLURE_ENABLE_WRITE", enable_write)
    importlib.reload(_mcp)
    for sub in ("tools", "tools_write"):
        sys.modules.pop(f"allure_testops_mcp.{sub}", None)
        if hasattr(_pkg, sub):
            delattr(_pkg, sub)
    importlib.reload(server)
    return set(_mcp.mcp._tool_manager._tools.keys())


def test_default_registers_only_read_only_tools(monkeypatch):
    names = _reload(monkeypatch, enable_write=None)
    assert names == READ_ONLY_TOOL_NAMES


def test_flag_false_registers_only_read_only_tools(monkeypatch):
    names = _reload(monkeypatch, enable_write="false")
    assert names == READ_ONLY_TOOL_NAMES


@pytest.mark.parametrize("value", ["true", "True", "1", "yes", "on"])
def test_flag_truthy_registers_write_tools(monkeypatch, value):
    names = _reload(monkeypatch, enable_write=value)
    assert names == READ_ONLY_TOOL_NAMES | WRITE_TOOL_NAMES
