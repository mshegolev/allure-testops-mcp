"""Unit tests for the write-side HTTP methods on :class:`AllureClient`.

Like :mod:`tests.test_errors`, the network layer is mocked with
:mod:`responses` so we exercise the real ``requests.Session`` path
(auth header, JSON body, timeout, ``raise_for_status``) rather than
hand-rolled stubs.
"""

from __future__ import annotations

import pytest
import requests
import responses

from allure_testops_mcp.client import AllureClient

BASE = "https://allure.test.local"


@pytest.fixture
def client():
    return AllureClient(url=BASE, token="t0k", ssl_verify=False)


@pytest.fixture
def http():
    with responses.RequestsMock() as rsps:
        yield rsps


# ── post ────────────────────────────────────────────────────────────────────


def test_post_sends_json_body_and_returns_parsed_json(client, http):
    captured: dict[str, object] = {}

    def callback(request):
        captured["body"] = request.body
        captured["headers"] = dict(request.headers)
        return (201, {}, '{"id": 42, "name": "TC"}')

    http.add_callback(responses.POST, f"{BASE}/api/rs/testcase", callback=callback)
    result = client.post("/testcase", {"name": "TC", "projectId": 1})
    assert result == {"id": 42, "name": "TC"}
    assert captured["body"] == b'{"name": "TC", "projectId": 1}'
    assert captured["headers"]["Authorization"] == "Api-Token t0k"
    assert captured["headers"]["Content-Type"] == "application/json"


def test_post_with_no_body_sends_no_body(client, http):
    captured: dict[str, object] = {}

    def callback(request):
        captured["body"] = request.body
        return (200, {}, "{}")

    http.add_callback(responses.POST, f"{BASE}/api/rs/ping", callback=callback)
    client.post("/ping")
    # ``None`` body -> no body sent (lets the server decide between {} and 400).
    assert captured["body"] in (None, b"", b"null")


def test_post_raises_on_4xx(client, http):
    http.add(responses.POST, f"{BASE}/api/rs/testcase", status=400, body="bad")
    with pytest.raises(requests.HTTPError):
        client.post("/testcase", {"x": 1})


def test_post_strips_leading_slash(client, http):
    http.add(responses.POST, f"{BASE}/api/rs/testcase", json={"id": 1})
    client.post("testcase", {"name": "x"})  # no leading slash
    assert len(http.calls) == 1


# ── patch ───────────────────────────────────────────────────────────────────


def test_patch_sends_json_body_and_returns_parsed_json(client, http):
    captured: dict[str, object] = {}

    def callback(request):
        captured["body"] = request.body
        return (200, {}, '{"id": 7, "name": "updated"}')

    http.add_callback(responses.PATCH, f"{BASE}/api/rs/testcase/7", callback=callback)
    result = client.patch("/testcase/7", {"name": "updated"})
    assert result == {"id": 7, "name": "updated"}
    assert captured["body"] == b'{"name": "updated"}'


def test_patch_raises_on_409(client, http):
    http.add(responses.PATCH, f"{BASE}/api/rs/testcase/7", status=409, body="conflict")
    with pytest.raises(requests.HTTPError):
        client.patch("/testcase/7", {"name": "x"})


# ── put ─────────────────────────────────────────────────────────────────────


def test_put_sends_json_body_and_returns_parsed_json(client, http):
    captured: dict[str, object] = {}

    def callback(request):
        captured["body"] = request.body
        return (200, {}, '{"id": 7, "name": "put-updated"}')

    http.add_callback(responses.PUT, f"{BASE}/api/rs/testcase/7", callback=callback)
    result = client.put("/testcase/7", {"name": "put-updated"})
    assert result == {"id": 7, "name": "put-updated"}
    assert captured["body"] == b'{"name": "put-updated"}'


def test_put_returns_none_on_204(client, http):
    http.add(responses.PUT, f"{BASE}/api/rs/testcase/7", status=204)
    assert client.put("/testcase/7", {"name": "x"}) is None


def test_put_raises_on_4xx(client, http):
    http.add(responses.PUT, f"{BASE}/api/rs/testcase/7", status=400, body="bad")
    with pytest.raises(requests.HTTPError):
        client.put("/testcase/7", {"name": "x"})


# ── delete ──────────────────────────────────────────────────────────────────


def test_delete_returns_none_on_204(client, http):
    http.add(responses.DELETE, f"{BASE}/api/rs/testcase/9", status=204)
    assert client.delete("/testcase/9") is None


def test_delete_returns_parsed_json_when_body_present(client, http):
    http.add(responses.DELETE, f"{BASE}/api/rs/testcase/9", status=200, json={"deleted": True})
    assert client.delete("/testcase/9") == {"deleted": True}


def test_delete_returns_none_on_empty_body(client, http):
    http.add(responses.DELETE, f"{BASE}/api/rs/testcase/9", status=200, body="")
    assert client.delete("/testcase/9") is None


def test_delete_raises_on_404(client, http):
    http.add(responses.DELETE, f"{BASE}/api/rs/testcase/9", status=404, body="not found")
    with pytest.raises(requests.HTTPError):
        client.delete("/testcase/9")
