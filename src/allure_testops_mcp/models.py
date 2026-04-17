"""TypedDict output schemas for every MCP tool."""

from __future__ import annotations

from typing_extensions import TypedDict


class PaginationMeta(TypedDict, total=False):
    page: int | None
    size: int | None
    total: int | None
    total_pages: int | None
    has_more: bool


# ── Projects ────────────────────────────────────────────────────────────────


class ProjectSummary(TypedDict):
    id: int
    name: str
    abbreviation: str | None


class ProjectsListOutput(TypedDict):
    count: int
    projects: list[ProjectSummary]


class ProjectStatistics(TypedDict, total=False):
    project_id: int
    total_test_cases: int
    automated_test_cases: int
    manual_test_cases: int
    automation_rate_pct: float
    last_launch_id: int | None
    last_launch_name: str | None
    last_launch_passed: int
    last_launch_failed: int
    last_launch_broken: int
    last_launch_total: int
    recent_launches_count: int


# ── Launches ────────────────────────────────────────────────────────────────


class LaunchSummary(TypedDict):
    id: int
    name: str
    status: str
    created_date: str | None
    passed: int
    failed: int
    broken: int
    skipped: int
    total: int


class LaunchesListOutput(TypedDict):
    project_id: int
    count: int
    pagination: PaginationMeta
    launches: list[LaunchSummary]


# ── Test results ────────────────────────────────────────────────────────────


class TestResultSummary(TypedDict):
    id: int
    name: str
    status: str
    duration_ms: int
    error: str


class TestResultsOutput(TypedDict):
    launch_id: int
    count: int
    pagination: PaginationMeta
    results: list[TestResultSummary]


class FailedTestsOutput(TypedDict):
    launch_id: int
    failed_count: int
    results: list[TestResultSummary]


# ── Test cases ──────────────────────────────────────────────────────────────


class TestCaseSummary(TypedDict):
    id: int
    name: str
    automated: bool
    status: str
    layer: str


class TestCasesListOutput(TypedDict):
    project_id: int
    count: int
    pagination: PaginationMeta
    test_cases: list[TestCaseSummary]
