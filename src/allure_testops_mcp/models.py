"""TypedDict output schemas for every MCP tool.

These schemas are read by FastMCP (``structured_output=True``) to generate
a JSON-Schema ``outputSchema`` for each tool. Clients that support
structured data use that schema to validate the ``structuredContent``
payload; clients that don't use the markdown ``content`` block instead.

Precision matters: fields required on every response use :class:`Required`,
fields that appear only in certain branches (e.g. "no launches found") use
:class:`NotRequired`.
"""

from __future__ import annotations

import sys

if sys.version_info >= (3, 12):
    from typing import NotRequired, Required, TypedDict
else:
    # Pydantic 2.13+ rejects stdlib ``typing.TypedDict`` on Python < 3.12
    # (it mandates ``typing_extensions.TypedDict`` for runtime schema
    # introspection — see https://errors.pydantic.dev/2.13/u/typed-dict-version).
    #
    # Additionally, on Python 3.10 the stdlib ``typing.TypedDict`` does not
    # recognise ``Required`` / ``NotRequired`` annotations at all (PEP 655
    # landed in stdlib only with 3.11). Using ``typing_extensions.TypedDict``
    # + its own Required/NotRequired solves both problems with one import.
    #
    # ``typing-extensions>=4.5`` is a conditional dep declared in pyproject.toml
    # (applied on ``python_version < '3.12'``).
    from typing_extensions import NotRequired, Required, TypedDict


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

    ``launch_id`` is ``0`` when no launches exist for the project and the
    tool short-circuits to an empty result.
    """

    launch_id: Required[int]
    failed_count: Required[int]
    results: Required[list[TestResultSummary]]
    reason: NotRequired[str]


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
