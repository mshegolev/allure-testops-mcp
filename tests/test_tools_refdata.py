"""Unit tests for the reference-data read tools (v0.5 Phase 1).

``allure_list_statuses`` / ``allure_list_layers`` fetch a project's status /
layer reference lists, paging through all results. The network layer is mocked
with :mod:`responses` so the real ``requests`` pipeline runs end-to-end; the
global client cache in ``_mcp`` is replaced for the duration of each test.
"""

from __future__ import annotations

import pytest
import responses

from allure_testops_mcp import _mcp
from allure_testops_mcp.client import AllureClient
from allure_testops_mcp.tools import allure_list_layers, allure_list_statuses

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


def test_list_statuses_returns_id_name_color(patched_client, http):
    http.add(
        responses.GET,
        f"{BASE}/api/rs/status",
        json={
            "content": [
                {"id": -1, "name": "Draft", "color": "#abc"},
                {"id": -3, "name": "Active", "color": "#2cbe4e"},
            ],
            "totalPages": 1,
        },
    )
    result = allure_list_statuses(project_id=63).structuredContent
    assert result["project_id"] == 63
    assert result["count"] == 2
    assert result["statuses"] == [
        {"id": -1, "name": "Draft", "color": "#abc"},
        {"id": -3, "name": "Active", "color": "#2cbe4e"},
    ]


def test_list_statuses_pages_through_all(patched_client, http):
    http.add(
        responses.GET,
        f"{BASE}/api/rs/status",
        json={"content": [{"id": -1, "name": "Draft"}], "totalPages": 2},
    )
    http.add(
        responses.GET,
        f"{BASE}/api/rs/status",
        json={"content": [{"id": 5, "name": "Blocked"}], "totalPages": 2},
    )
    result = allure_list_statuses(project_id=63).structuredContent
    assert [s["id"] for s in result["statuses"]] == [-1, 5]
    # color is required-but-nullable in the output schema
    assert result["statuses"][0]["color"] is None


def test_list_layers_returns_id_name(patched_client, http):
    http.add(
        responses.GET,
        f"{BASE}/api/rs/testlayer",
        json={"content": [{"id": -3, "name": "API Tests"}, {"id": 3, "name": "API"}], "totalPages": 1},
    )
    result = allure_list_layers(project_id=63).structuredContent
    assert result == {
        "project_id": 63,
        "count": 2,
        "layers": [{"id": -3, "name": "API Tests"}, {"id": 3, "name": "API"}],
    }


def test_list_statuses_empty_project(patched_client, http):
    http.add(responses.GET, f"{BASE}/api/rs/status", json={"content": [], "totalPages": 1})
    result = allure_list_statuses(project_id=63).structuredContent
    assert result == {"project_id": 63, "count": 0, "statuses": []}
