"""Unit tests for pure helpers in :mod:`allure_testops_mcp.tools`.

``_launch_stats``, ``_test_result_summary`` and ``_test_case_summary`` have
no side effects — they just reshape raw Allure JSON into the TypedDict
payloads. Keeping them under test guards against schema drift if the
Allure REST response evolves.
"""

from __future__ import annotations

from pydantic import TypeAdapter

from allure_testops_mcp.models import TestCaseSummary
from allure_testops_mcp.tools import _launch_stats, _test_case_summary, _test_result_summary

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
# Regression coverage for the bug where Allure TestOps returns ``status`` and
# ``layer`` on ``/testcase`` items as ``{id, name}`` objects (or ``null``),
# not as primitive strings. Mapping those raw dicts into ``TestCaseSummary``
# previously broke Pydantic validation in FastMCP's structured-output layer.


def test_test_case_summary_unwraps_status_object():
    tc = {
        "id": 101,
        "name": "Login flow",
        "automated": True,
        "status": {"id": -1, "name": "Draft", "color": "#ccc"},
        "layer": {"id": 5, "name": "E2E"},
    }
    assert _test_case_summary(tc) == {
        "id": 101,
        "name": "Login flow",
        "automated": True,
        "status": "Draft",
        "layer": "E2E",
    }


def test_test_case_summary_status_null():
    tc = {"id": 1, "name": "x", "status": None, "layer": None}
    result = _test_case_summary(tc)
    assert result["status"] == ""
    assert result["layer"] == ""


def test_test_case_summary_status_missing_keys():
    result = _test_case_summary({"id": 2})
    assert result == {"id": 2, "name": "", "automated": False, "status": "", "layer": ""}


def test_test_case_summary_status_object_without_name():
    tc = {"id": 3, "status": {"id": -1}, "layer": {"id": 9}}
    result = _test_case_summary(tc)
    assert result["status"] == ""
    assert result["layer"] == ""


def test_test_case_summary_passes_pydantic_validation_with_status_dict():
    """The original bug surfaced as a Pydantic ``string_type`` error on the
    ``status`` field. Re-validate the helper's output through the same
    TypedDict the FastMCP output schema is built from — if this passes,
    ``allure_list_test_cases`` will not raise on a project whose test cases
    carry ``Draft`` (or any other named) statuses.
    """
    adapter = TypeAdapter(TestCaseSummary)
    raw = {
        "id": 42,
        "name": "Smoke",
        "automated": False,
        "status": {"id": -1, "name": "Draft", "lastModifiedBy": "system"},
        "layer": {"id": 1, "name": "API"},
    }
    validated = adapter.validate_python(_test_case_summary(raw))
    assert validated["status"] == "Draft"
    assert validated["layer"] == "API"
