"""Unit tests for pure helpers in :mod:`allure_testops_mcp.tools`.

``_launch_stats`` and ``_test_result_summary`` have no side effects — they
just reshape raw Allure JSON into the TypedDict payloads. Keeping them
under test guards against schema drift if the Allure REST response evolves.
"""

from __future__ import annotations

from allure_testops_mcp.tools import _launch_stats, _test_result_summary


# ── _launch_stats ───────────────────────────────────────────────────────────


def test_launch_stats_full_breakdown():
    launch = {
        "statistic": {"passed": 10, "failed": 2, "broken": 1, "skipped": 3, "total": 16}
    }
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
