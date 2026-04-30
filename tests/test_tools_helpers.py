"""Unit tests for pure helpers in :mod:`allure_testops_mcp.tools`.

``_launch_stats``, ``_test_result_summary``, ``_test_case_summary`` and
``_build_owner_rql`` have no side effects — the first three reshape raw
Allure JSON into TypedDict payloads, the last builds an RQL clause from
a username. Keeping them under test guards against schema drift on the
Allure side and against accidental RQL-injection regressions.
"""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter

from allure_testops_mcp.models import TestCaseSummary
from allure_testops_mcp.tools import (
    _build_owner_rql,
    _launch_stats,
    _test_case_summary,
    _test_result_summary,
)

# ── _launch_stats ───────────────────────────────────────────────────────────


def test_launch_stats_full_breakdown():
    launch = {"statistic": {"passed": 10, "failed": 2, "broken": 1, "skipped": 3, "total": 16}}
    assert _launch_stats(launch) == {
        "passed": 10,
        "failed": 2,
        "broken": 1,
        "skipped": 3,
        "total": 16,
    }


def test_launch_stats_missing_statistic_block():
    assert _launch_stats({}) == {
        "passed": 0,
        "failed": 0,
        "broken": 0,
        "skipped": 0,
        "total": 0,
    }


def test_launch_stats_null_statistic_block():
    assert _launch_stats({"statistic": None}) == {
        "passed": 0,
        "failed": 0,
        "broken": 0,
        "skipped": 0,
        "total": 0,
    }


def test_launch_stats_missing_individual_keys():
    launch = {"statistic": {"passed": 5}}
    assert _launch_stats(launch) == {
        "passed": 5,
        "failed": 0,
        "broken": 0,
        "skipped": 0,
        "total": 0,
    }


def test_launch_stats_coerces_string_numbers():
    launch = {"statistic": {"passed": "7", "failed": "0"}}
    result = _launch_stats(launch)
    assert result["passed"] == 7
    assert result["failed"] == 0


# ── _test_result_summary ────────────────────────────────────────────────────


def test_test_result_summary_full():
    r = {
        "id": 42,
        "name": "test_login",
        "status": "FAILED",
        "duration": 1234,
        "statusMessage": "AssertionError: expected 200",
    }
    assert _test_result_summary(r) == {
        "id": 42,
        "name": "test_login",
        "status": "FAILED",
        "duration_ms": 1234,
        "error": "AssertionError: expected 200",
    }


def test_test_result_summary_missing_optional_fields():
    result = _test_result_summary({"id": 1})
    assert result == {
        "id": 1,
        "name": "",
        "status": "",
        "duration_ms": 0,
        "error": "",
    }


def test_test_result_summary_truncates_error_at_300_chars():
    long_error = "X" * 500
    result = _test_result_summary({"id": 1, "statusMessage": long_error})
    assert len(result["error"]) == 300
    assert result["error"] == "X" * 300


def test_test_result_summary_null_status_message():
    # Allure sometimes returns explicit null for missing trace.
    result = _test_result_summary({"id": 1, "statusMessage": None})
    assert result["error"] == ""


def test_test_result_summary_coerces_id_and_duration():
    result = _test_result_summary({"id": "7", "duration": "500"})
    assert result["id"] == 7
    assert result["duration_ms"] == 500


# ── _test_case_summary ──────────────────────────────────────────────────────
#
# Regression coverage for the original bug where Allure returns ``status``
# and ``layer`` on ``/testcase`` items as ``{id, name}`` objects (or ``null``),
# not as primitive strings — mapping those raw dicts into ``TestCaseSummary``
# previously broke Pydantic validation. The cases below also pin the
# enriched-projection mapping (``createdBy`` / ``lastModifiedBy`` / ``tags``)
# returned by the ``__search`` endpoint.


def test_test_case_summary_full_search_projection():
    """The shape returned by ``GET /testcase/__search`` carries every field
    we surface — verify the full unwrap in one go."""
    tc = {
        "id": 101,
        "name": "Login flow",
        "automated": True,
        "status": {"id": -1, "name": "Draft", "color": "#ccc"},
        "layer": {"id": 5, "name": "E2E"},
        "createdBy": "jdoe",
        "lastModifiedBy": "system",
        "tags": [{"id": 1, "name": "smoke"}, {"id": 2, "name": "regression"}],
    }
    assert _test_case_summary(tc) == {
        "id": 101,
        "name": "Login flow",
        "automated": True,
        "status": "Draft",
        "layer": "E2E",
        "created_by": "jdoe",
        "last_modified_by": "system",
        "tags": ["smoke", "regression"],
    }


def test_test_case_summary_compact_projection():
    """Plain ``GET /testcase`` returns only id/name/automated/status — the
    audit fields and tags are absent. Mapping must not raise and must
    fill the missing fields with empty strings / empty list (Pydantic
    rejects ``None`` for ``str`` / ``list``)."""
    tc = {"id": 2, "name": "x", "automated": False, "status": {"id": 11, "name": "Active"}}
    assert _test_case_summary(tc) == {
        "id": 2,
        "name": "x",
        "automated": False,
        "status": "Active",
        "layer": "",
        "created_by": "",
        "last_modified_by": "",
        "tags": [],
    }


def test_test_case_summary_status_null():
    tc = {"id": 1, "name": "x", "status": None, "layer": None}
    result = _test_case_summary(tc)
    assert result["status"] == ""
    assert result["layer"] == ""


def test_test_case_summary_status_object_without_name():
    tc = {"id": 3, "status": {"id": -1}, "layer": {"id": 9}}
    result = _test_case_summary(tc)
    assert result["status"] == ""
    assert result["layer"] == ""


def test_test_case_summary_audit_fields_null():
    """``createdBy`` / ``lastModifiedBy`` may be explicit ``null`` for
    system-imported TCs — must collapse to empty strings, never ``None``."""
    tc = {"id": 11, "createdBy": None, "lastModifiedBy": None}
    result = _test_case_summary(tc)
    assert result["created_by"] == ""
    assert result["last_modified_by"] == ""


def test_test_case_summary_tags_skips_anonymous_entries():
    """Allure occasionally returns a tag without a ``name`` (rare, deleted
    tag still referenced). Drop them rather than emit ``""`` strings."""
    tc = {
        "id": 12,
        "tags": [
            {"id": 1, "name": "smoke"},
            {"id": 2},
            {"id": 3, "name": ""},
            "not-an-object",  # defensive: Allure always sends dicts, but guard anyway
        ],
    }
    assert _test_case_summary(tc)["tags"] == ["smoke"]


def test_test_case_summary_passes_pydantic_validation():
    """Re-validate the helper's output through the same TypedDict the
    FastMCP structured-output schema is built from. If this passes, the
    tool will not raise Pydantic ``string_type`` / ``list_type`` errors on
    real Allure responses (the original bug, plus its tag/list-shape
    cousin)."""
    adapter = TypeAdapter(TestCaseSummary)
    raw = {
        "id": 42,
        "name": "Smoke",
        "automated": False,
        "status": {"id": -1, "name": "Draft", "lastModifiedBy": "system"},
        "layer": {"id": 1, "name": "API"},
        "createdBy": "jdoe",
        "lastModifiedBy": "system",
        "tags": [{"id": 9, "name": "smoke"}],
    }
    validated = adapter.validate_python(_test_case_summary(raw))
    assert validated["status"] == "Draft"
    assert validated["layer"] == "API"
    assert validated["created_by"] == "jdoe"
    assert validated["last_modified_by"] == "system"
    assert validated["tags"] == ["smoke"]


# ── _build_owner_rql ────────────────────────────────────────────────────────
#
# RQL is interpolated into the request URL — every test here doubles as
# regression coverage against accidental query-injection.


def test_build_owner_rql_basic():
    assert _build_owner_rql("jdoe") == 'createdBy = "jdoe" or lastModifiedBy = "jdoe"'


@pytest.mark.parametrize("username", ["jdoe", "j.doe", "jdoe-bot", "j_doe", "jdoe@corp", "User123"])
def test_build_owner_rql_accepts_allure_usernames(username):
    """Allure usernames may contain letters, digits, dot, dash, underscore
    and ``@`` (some deployments use email-style logins)."""
    rql = _build_owner_rql(username)
    assert username in rql
    assert "createdBy" in rql and "lastModifiedBy" in rql


@pytest.mark.parametrize(
    "bad",
    [
        'jdoe"',  # quote — would break out of the string literal
        'jdoe"; or 1=1 --',  # classic SQL/RQL injection shape
        "jdoe' or 'a'='a",  # single-quote variant
        "jdoe\\",  # backslash — escape ambiguity
        'jdoe and lastModifiedBy = "root"',  # space + RQL keywords
        "",  # empty username — would build broken RQL
        "jdoe ",  # trailing space
    ],
)
def test_build_owner_rql_rejects_injection_attempts(bad):
    with pytest.raises(ValueError, match="username"):
        _build_owner_rql(bad)
