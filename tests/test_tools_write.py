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


def _mock_status(http, mapping):
    """Register GET /status returning {name: id} as a single page."""
    http.add(
        responses.GET,
        f"{BASE}/api/rs/status",
        json={"content": [{"id": i, "name": n} for n, i in mapping.items()], "totalPages": 1},
    )


def _mock_layer(http, mapping):
    """Register GET /testlayer returning {name: id} as a single page."""
    http.add(
        responses.GET,
        f"{BASE}/api/rs/testlayer",
        json={"content": [{"id": i, "name": n} for n, i in mapping.items()], "totalPages": 1},
    )


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


# ── status/layer shapes differ by operation (create nested-id vs update flat-id) ──


def test_build_body_create_uses_nested_id_objects():
    body = _build_testcase_body({"status_id": 3, "layer_id": 9}, mode="create")
    assert body == {"status": {"id": 3}, "layer": {"id": 9}}


def test_build_body_update_uses_flat_ids():
    body = _build_testcase_body({"status_id": 3, "layer_id": 9}, mode="update")
    assert body == {"statusId": 3, "testLayerId": 9}


def test_build_body_id_takes_precedence_over_name():
    body = _build_testcase_body({"status": "Draft", "status_id": 3}, mode="create")
    assert body == {"status": {"id": 3}}


def test_build_body_update_rejects_status_name():
    with pytest.raises(ValueError, match="status id, not a name"):
        _build_testcase_body({"status": "Active"}, mode="update")


def test_build_body_update_rejects_layer_name():
    with pytest.raises(ValueError, match="layer id, not a name"):
        _build_testcase_body({"layer": "API"}, mode="update")


# ── name→id resolver ─────────────────────────────────────────────────────────


def test_list_refs_pages_through_all_results(patched_client, http):
    from allure_testops_mcp.tools_write import _list_refs

    http.add(
        responses.GET,
        f"{BASE}/api/rs/status",
        json={"content": [{"id": -1, "name": "Draft"}, {"id": -3, "name": "Active"}], "totalPages": 2},
    )
    http.add(
        responses.GET,
        f"{BASE}/api/rs/status",
        json={"content": [{"id": 5, "name": "Blocked"}], "totalPages": 2},
    )
    refs = _list_refs(patched_client, "status", 63)
    assert refs == {"Draft": -1, "Active": -3, "Blocked": 5}


def test_resolve_ref_is_case_insensitive(patched_client, http):
    from allure_testops_mcp.tools_write import _resolve_ref

    _mock_status(http, {"Draft": -1, "Active": -3})
    assert _resolve_ref(patched_client, "status", 63, "dRaFt") == -1


# ── allure_create_test_case ─────────────────────────────────────────────────


def test_create_test_case_happy_path(patched_client, http):
    captured: dict[str, object] = {}

    def callback(request):
        captured["body"] = request.body
        return (201, {}, '{"id": 555, "name": "Login flow"}')

    _mock_status(http, {"Draft": -1})
    _mock_layer(http, {"E2E": 99})
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
    # Names were resolved to ids and sent as Allure's nested id objects.
    assert captured["body"] == (
        b'{"projectId": 63, "name": "Login flow", "description": "checks login", '
        b'"automated": true, "status": {"id": -1}, "layer": {"id": 99}, '
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


def test_create_unknown_status_name_errors_before_post(patched_client, http):
    """An unknown status name fails at resolution with the valid names listed —
    no POST is attempted."""
    _mock_status(http, {"Draft": -1, "Active": -3})
    with pytest.raises(ToolError) as exc_info:
        allure_create_test_case(project_id=1, name="x", status="Nonexistent")
    msg = str(exc_info.value)
    assert "not found" in msg and "Draft" in msg
    # Resolution failed -> no test case was created.
    assert [c.request.method for c in http.calls] == ["GET"]


def test_create_surfaces_post_400_as_tool_error(patched_client, http):
    """A 400 from the create call itself still surfaces as an actionable error."""
    _mock_status(http, {"Draft": -1})
    http.add(responses.POST, f"{BASE}/api/rs/testcase", status=400, body="bad payload")
    with pytest.raises(ToolError) as exc_info:
        allure_create_test_case(project_id=1, name="x", status="Draft")
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
        status_id=7,
        tags=["smoke"],
    )
    assert set(result.structuredContent["updated_fields"]) == {"name", "automated", "status_id", "tags"}


def test_update_test_case_rejects_empty_update(patched_client):
    with pytest.raises(ToolError, match="nothing to update"):
        allure_update_test_case(test_case_id=42)


def test_update_test_case_surfaces_404(patched_client, http):
    http.add(responses.PATCH, f"{BASE}/api/rs/testcase/999", status=404, body="not found")
    with pytest.raises(ToolError) as exc_info:
        allure_update_test_case(test_case_id=999, name="x")
    assert "404" in str(exc_info.value) or "not found" in str(exc_info.value).lower()


def test_update_falls_back_to_put_on_405(patched_client, http):
    """Deployments that expose only PUT answer PATCH with 405 — the tool
    transparently retries with PUT and succeeds."""
    captured: dict[str, object] = {}

    def put_cb(request):
        captured["put_body"] = request.body
        return (200, {}, '{"id": 7, "name": "renamed"}')

    http.add(responses.PATCH, f"{BASE}/api/rs/testcase/7", status=405, body="method not allowed")
    http.add_callback(responses.PUT, f"{BASE}/api/rs/testcase/7", callback=put_cb)

    result = allure_update_test_case(test_case_id=7, name="renamed")
    assert result.structuredContent["id"] == 7
    assert result.structuredContent["updated_fields"] == ["name"]
    # PUT received the same mapped body PATCH would have.
    assert captured["put_body"] == b'{"name": "renamed"}'
    # Both verbs were exercised: PATCH (405) then PUT (200).
    assert [c.request.method for c in http.calls] == ["PATCH", "PUT"]


def test_update_does_not_fall_back_on_non_405(patched_client, http):
    """A 409 (or any non-405) must propagate, not trigger a PUT retry."""
    http.add(responses.PATCH, f"{BASE}/api/rs/testcase/7", status=409, body="conflict")
    with pytest.raises(ToolError):
        allure_update_test_case(test_case_id=7, name="x")
    # Only the PATCH was attempted — no silent PUT fallback on conflict.
    assert [c.request.method for c in http.calls] == ["PATCH"]


def test_update_sends_flat_status_and_layer_ids(patched_client, http):
    captured: dict[str, object] = {}

    def cb(request):
        captured["body"] = request.body
        return (200, {}, '{"id": 7, "name": "n"}')

    http.add_callback(responses.PATCH, f"{BASE}/api/rs/testcase/7", callback=cb)
    allure_update_test_case(test_case_id=7, status_id=3, layer_id=9)
    # Flat ids per the TestCasePatch DTO — not nested name objects.
    assert captured["body"] == b'{"statusId": 3, "testLayerId": 9}'


def test_update_resolves_status_name_via_project_lookup(patched_client, http):
    """A status *name* on update is resolved to its id: fetch the TC's project,
    look up the status list, then PATCH with the flat statusId."""
    captured: dict[str, object] = {}

    def patch_cb(request):
        captured["body"] = request.body
        return (200, {}, '{"id": 7, "name": "n"}')

    http.add(responses.GET, f"{BASE}/api/rs/testcase/7", json={"id": 7, "projectId": 63})
    _mock_status(http, {"Active": -3})
    http.add_callback(responses.PATCH, f"{BASE}/api/rs/testcase/7", callback=patch_cb)

    result = allure_update_test_case(test_case_id=7, status="Active")
    assert captured["body"] == b'{"statusId": -3}'
    assert "status_id" in result.structuredContent["updated_fields"]


def test_update_unknown_layer_name_errors(patched_client, http):
    http.add(responses.GET, f"{BASE}/api/rs/testcase/7", json={"id": 7, "projectId": 63})
    _mock_layer(http, {"API Tests": -3})
    with pytest.raises(ToolError) as exc_info:
        allure_update_test_case(test_case_id=7, layer="Nope")
    assert "not found" in str(exc_info.value)


def test_create_sends_nested_status_and_layer_ids(patched_client, http):
    captured: dict[str, object] = {}

    def cb(request):
        captured["body"] = request.body
        return (201, {}, '{"id": 1, "name": "TC"}')

    http.add_callback(responses.POST, f"{BASE}/api/rs/testcase", callback=cb)
    allure_create_test_case(project_id=1, name="TC", status_id=3, layer_id=9)
    # Nested id objects per the TestCase DTO.
    expected = b'{"projectId": 1, "name": "TC", "automated": false, "status": {"id": 3}, "layer": {"id": 9}}'
    assert captured["body"] == expected


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
