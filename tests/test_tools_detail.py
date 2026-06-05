"""Unit tests for ``allure_get_test_case`` (v0.6 Phase 1).

Covers the step-flattening helper and the tool's detail + scenario assembly,
with the network layer mocked via :mod:`responses`.
"""

from __future__ import annotations

import pytest
import responses

from allure_testops_mcp import _mcp
from allure_testops_mcp.client import AllureClient
from allure_testops_mcp.tools import (
    _flatten_steps,
    allure_get_test_case,
    allure_get_test_case_custom_fields,
)

BASE = "https://allure.test.local"


@pytest.fixture
def http():
    with responses.RequestsMock() as rsps:
        yield rsps


@pytest.fixture
def patched_client(monkeypatch):
    client = AllureClient(url=BASE, token="t0k", ssl_verify=False)
    monkeypatch.setattr(_mcp, "_client", client)
    return client


# ── _flatten_steps ───────────────────────────────────────────────────────────


def test_flatten_steps_records_depth_and_nesting():
    steps = [
        {"keyword": "Given", "name": "a precondition", "steps": []},
        {
            "keyword": "When",
            "name": "an action",
            "expectedResult": "ok",
            "steps": [{"keyword": "And", "name": "a nested step"}],
        },
    ]
    flat = _flatten_steps(steps)
    assert flat == [
        {"depth": 0, "keyword": "Given", "name": "a precondition", "expected_result": ""},
        {"depth": 0, "keyword": "When", "name": "an action", "expected_result": "ok"},
        {"depth": 1, "keyword": "And", "name": "a nested step", "expected_result": ""},
    ]


def test_flatten_steps_handles_none():
    assert _flatten_steps(None) == []


# ── allure_get_test_case ─────────────────────────────────────────────────────


def test_get_test_case_assembles_detail_and_steps(patched_client, http):
    http.add(
        responses.GET,
        f"{BASE}/api/rs/testcase/555",
        json={
            "id": 555,
            "name": "Login flow",
            "projectId": 63,
            "automated": False,
            "precondition": "be logged out",
            "expectedResult": "lands on dashboard",
            "status": {"id": -1, "name": "Draft"},
            "layer": {"id": -3, "name": "E2E"},
            "tags": [{"id": 1, "name": "smoke"}],
            "createdBy": "jdoe",
            "lastModifiedBy": "asmith",
        },
    )
    http.add(
        responses.GET,
        f"{BASE}/api/rs/testcase/555/scenario",
        json={"steps": [{"keyword": "When", "name": "click login", "steps": []}]},
    )
    result = allure_get_test_case(test_case_id=555).structuredContent
    assert result["id"] == 555
    assert result["project_id"] == 63
    assert result["status"] == "Draft"
    assert result["layer"] == "E2E"
    assert result["tags"] == ["smoke"]
    assert result["precondition"] == "be logged out"
    assert result["steps"] == [{"depth": 0, "keyword": "When", "name": "click login", "expected_result": ""}]


def test_get_test_case_without_scenario_skips_the_call(patched_client, http):
    http.add(
        responses.GET,
        f"{BASE}/api/rs/testcase/9",
        json={"id": 9, "name": "x", "projectId": 1},
    )
    result = allure_get_test_case(test_case_id=9, include_scenario=False).structuredContent
    assert result["steps"] == []
    # Only the detail call was made — no /scenario fetch.
    assert [c.request.url.split("/api/rs/")[1] for c in http.calls] == ["testcase/9"]


def test_get_test_case_empty_optionals_collapse(patched_client, http):
    http.add(responses.GET, f"{BASE}/api/rs/testcase/9", json={"id": 9, "name": "x", "projectId": 1})
    http.add(responses.GET, f"{BASE}/api/rs/testcase/9/scenario", json={"steps": []})
    result = allure_get_test_case(test_case_id=9).structuredContent
    assert result["description"] == "" and result["precondition"] == "" and result["layer"] == ""
    assert result["tags"] == [] and result["steps"] == []


# ── allure_get_test_case_custom_fields ───────────────────────────────────────


def test_get_custom_fields_flattens_field_and_value(patched_client, http):
    http.add(
        responses.GET,
        f"{BASE}/api/rs/testcase/641012/cfv",
        json=[
            {"id": 99075, "name": "N/A", "customField": {"id": 168, "name": "Automation status"}},
            {"id": 41990, "name": "Medium", "customField": {"id": 12, "name": "Priority"}},
        ],
    )
    result = allure_get_test_case_custom_fields(test_case_id=641012).structuredContent
    assert result["test_case_id"] == 641012
    assert result["count"] == 2
    assert result["custom_fields"][0] == {
        "field_id": 168,
        "field_name": "Automation status",
        "value_id": 99075,
        "value_name": "N/A",
    }
    assert result["custom_fields"][1]["field_name"] == "Priority"


def test_get_custom_fields_empty(patched_client, http):
    http.add(responses.GET, f"{BASE}/api/rs/testcase/9/cfv", json=[])
    result = allure_get_test_case_custom_fields(test_case_id=9).structuredContent
    assert result == {"test_case_id": 9, "count": 0, "custom_fields": []}
