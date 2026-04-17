"""TypedDict output schemas for every MCP tool.

These schemas are read by FastMCP (``structured_output=True``) to generate
a JSON-Schema ``outputSchema`` for each tool. Clients that support
structured data use that schema to validate the ``structuredContent``
payload; clients that don't use the markdown ``content`` block instead.

**Note on Python / Pydantic compat.** We deliberately avoid ``Required`` /
``NotRequired`` qualifiers: Pydantic 2.13+ mishandles them on Py < 3.12 (see
https://errors.pydantic.dev/2.13/u/typed-dict-version and PydanticForbiddenQualifier).
Instead, every field is required at the type level; optional branches use
``| None`` and the code always sets the key (with ``None`` when absent).
"""

from __future__ import annotations

import sys

# Pydantic 2.13+ rejects stdlib ``typing.TypedDict`` on Python < 3.12 during
# runtime schema generation. On 3.12+ the stdlib class is fine. See the
# module docstring above for the full reasoning.
if sys.version_info >= (3, 12):
    from typing import TypedDict
else:
    from typing_extensions import TypedDict


class PaginationMeta(TypedDict, total=False):
    page: int | None
    size: int | None
    total: int | None
    total_pages: int | None
    has_more: bool
    next_page: int | None


# ── Projects ────────────────────────────────────────────────────────────────


class ProjectSummary(TypedDict):
    id: int
    name: str
    abbreviation: str | None


class ProjectsListOutput(TypedDict):
    count: int
    projects: list[ProjectSummary]


class ProjectStatistics(TypedDict):
    """Aggregate statistics for a project.

    ``last_launch_*`` fields are ``None`` when the project has no closed
    launches (required key, nullable value — different from "absent key").
    """

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
    """Output for :func:`allure_search_failed_tests`.

    ``launch_id`` is ``0`` when no launches exist for the project; in that
    short-circuit path ``reason`` carries a human-readable explanation.
    In the normal path ``reason`` is ``None``.
    """

    launch_id: int
    failed_count: int
    results: list[TestResultSummary]
    reason: str | None


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
