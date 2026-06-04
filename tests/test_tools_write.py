"""Unit tests for the opt-in write tools in :mod:`allure_testops_mcp.tools_write`.

Approach is the same as :mod:`tests.test_errors`:

* the AllureClient is constructed against a fake URL,
* :mod:`responses` mocks the network layer so the real ``requests``
  pipeline runs end-to-end,
* the global client cache in ``_mcp`` is replaced for the duration of
  each test so the @mcp.tool functions see our test client.

The body-builder helper is pure and tested in isolation.
"""

from __future__ import annotations

import pytest
import responses
from mcp.server.fastmcp.exceptions import ToolError

from allure_testops_mcp import _mcp
from allure_testops_mcp.client import AllureClient
from allure_testops_mcp.tools_write import (
    _build_testcase_body,
    allure_create_test_case,
    allure_delete_test_case,
    allure_update_test_case,
)

BASE = "https://allure.test.local"


@pytest.fixture
def http():
    with responses.RequestsMock() as rsps:
        yield rsps


@pytest.fixture
def patched_client(monkeypatch):
    """Replace the lazy global client with one pointing at the mocked host."""
    client = AllureClient(url=BASE, token="t0k", ssl_verify=False)
    monkeypatch.setattr(_mcp, "_client", client)
    monkeypatch.setenv("ALLURE_URL", BASE)
    return client


# ── _build_testcase_body ────────────────────────────────────────────────────


def test_build_body_drops_none_values():
    body = _build_testcase_body({"name": "TC", "description": None, "automated": False})
    assert body == {"name": "TC", "automated": False}


def test_build_body_passes_through_scalar_fields():
    body = _build_testcase_body(
        {
            "name": "TC",
            "description": "desc",
            "precondition": "pre",
            "expected_result": "ok",
            "automated": True,
        }
    )
    assert body == {
        "name": "TC",
        "description": "desc",
        "precondition": "pre",
        "expectedResult": "ok",
        "automated": True,
    }


def test_build_body_wraps_status_as_named_object():
    body = _build_testcase_body({"status": "Draft"})
    assert body == {"status": {"name": "Draft"}}


def test_build_body_wraps_layer_as_named_object():
    body = _build_testcase_body({"layer": "API"})
    assert body == {"layer": {"name": "API"}}


def test_build_body_wraps_tags_as_list_of_named_objects():
    body = _build_testcase_body({"tags": ["smoke", "regression"]})
    assert body == {"tags": [{"name": "smoke"}, {"name": "regression"}]}


def test_build_body_includes_project_id_when_set():
    body = _build_testcase_body({"project_id": 63, "name": "TC"})
    assert body == {"projectId": 63, "name": "TC"}


def test_build_body_empty_when_all_none():
    assert _build_testcase_body({"name": None, "status": None, "tags": None}) == {}


# ── allure_create_test_case ─────────────────────────────────────────────────


def test_create_test_case_happy_path(patched_client, http):
    captured: dict[str, object] = {}

    def callback(request):
        captured["body"] = request.body
        return (201, {}, '{"id": 555, "name": "Login flow"}')

    http.add_callback(responses.POST, f"{BASE}/api/rs/testcase", callback=callback)
    result = allure_create_test_case(
        project_id=63,
        name="Login flow",
        description="checks login",
        automated=True,
        status="Draft",
        layer="E2E",
        tags=["smoke"],
    )
    assert result.structuredContent == {
        "id": 555,
        "name": "Login flow",
        "project_id": 63,
        "url": f"{BASE}/project/63/test-cases/555",
    }
    assert captured["body"] == (
        b'{"projectId": 63, "name": "Login flow", "description": "checks login", '
        b'"automated": true, "status": {"name": "Draft"}, "layer": {"name": "E2E"}, '
        b'"tags": [{"name": "smoke"}]}'
    )


def test_create_test_case_defaults_automated_false(patched_client, http):
    captured: dict[str, object] = {}

    def callback(request):
        captured["body"] = request.body
        return (201, {}, '{"id": 1, "name": "TC"}')

    http.add_callback(responses.POST, f"{BASE}/api/rs/testcase", callback=callback)
    allure_create_test_case(project_id=1, name="TC")
    assert b'"automated": false' in captured["body"]  # type: ignore[operator]


def test_create_test_case_url_is_null_when_allure_url_missing(monkeypatch, patched_client, http):
    monkeypatch.delenv("ALLURE_URL", raising=False)
    http.add(responses.POST, f"{BASE}/api/rs/testcase", json={"id": 7, "name": "x"}, status=201)
    result = allure_create_test_case(project_id=1, name="x")
    assert result.structuredContent["url"] is None


def test_create_test_case_surfaces_400_as_tool_error(patched_client, http):
    http.add(responses.POST, f"{BASE}/api/rs/testcase", status=400, body="bad status")
    with pytest.raises(ToolError) as exc_info:
        allure_create_test_case(project_id=1, name="x", status="Nonexistent")
    assert "400" in str(exc_info.value) or "Allure" in str(exc_info.value)


# ── allure_update_test_case ─────────────────────────────────────────────────


def test_update_test_case_strips_none_fields(patched_client, http):
    captured: dict[str, object] = {}

    def callback(request):
        captured["body"] = request.body
        return (200, {}, '{"id": 555, "name": "renamed"}')

    http.add_callback(responses.PATCH, f"{BASE}/api/rs/testcase/555", callback=callback)
    result = allure_update_test_case(test_case_id=555, name="renamed", description=None)
    # description=None must not appear in the body
    assert b"description" not in captured["body"]  # type: ignore[operator]
    assert captured["body"] == b'{"name": "renamed"}'
    assert result.structuredContent == {
        "id": 555,
        "name": "renamed",
        "updated_fields": ["name"],
    }


def test_update_test_case_reports_all_updated_fields(patched_client, http):
    http.add(responses.PATCH, f"{BASE}/api/rs/testcase/12", json={"id": 12, "name": "n"})
    result = allure_update_test_case(
        test_case_id=12,
        name="n",
        automated=True,
        status="Active",
        tags=["smoke"],
    )
    assert set(result.structuredContent["updated_fields"]) == {"name", "automated", "status", "tags"}


def test_update_test_case_rejects_empty_update(patched_client):
    with pytest.raises(ToolError, match="nothing to update"):
        allure_update_test_case(test_case_id=42)


def test_update_test_case_surfaces_404(patched_client, http):
    http.add(responses.PATCH, f"{BASE}/api/rs/testcase/999", status=404, body="not found")
    with pytest.raises(ToolError) as exc_info:
        allure_update_test_case(test_case_id=999, name="x")
    assert "404" in str(exc_info.value) or "not found" in str(exc_info.value).lower()


# ── allure_delete_test_case ─────────────────────────────────────────────────


def test_delete_test_case_happy_path(patched_client, http):
    http.add(responses.DELETE, f"{BASE}/api/rs/testcase/9", status=204)
    result = allure_delete_test_case(test_case_id=9, confirm=True)
    assert result.structuredContent == {"id": 9, "deleted": True}


def test_delete_test_case_rejects_confirm_false(patched_client):
    with pytest.raises(ToolError, match="confirm"):
        allure_delete_test_case(test_case_id=9, confirm=False)  # type: ignore[arg-type]


def test_delete_test_case_surfaces_404(patched_client, http):
    http.add(responses.DELETE, f"{BASE}/api/rs/testcase/9", status=404, body="not found")
    with pytest.raises(ToolError):
        allure_delete_test_case(test_case_id=9, confirm=True)
