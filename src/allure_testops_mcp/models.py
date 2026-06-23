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


# ── Reference data (statuses / layers) ──────────────────────────────────────


class StatusRef(TypedDict):
    id: int
    name: str
    color: str | None


class StatusesListOutput(TypedDict):
    project_id: int
    count: int
    statuses: list[StatusRef]


class LayerRef(TypedDict):
    id: int
    name: str


class LayersListOutput(TypedDict):
    project_id: int
    count: int
    layers: list[LayerRef]


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
    created_by: str
    last_modified_by: str
    tags: list[str]


class TestCasesListOutput(TypedDict):
    project_id: int
    count: int
    pagination: PaginationMeta
    test_cases: list[TestCaseSummary]


class TestCaseStepFlat(TypedDict):
    """One scenario step, flattened. ``depth`` is the nesting level (0 = top).

    The Allure scenario tree is recursive; flattening with a depth marker keeps
    the structured-output schema simple while preserving the hierarchy for
    rendering.
    """

    depth: int
    keyword: str
    name: str
    expected_result: str


class TestCaseDetail(TypedDict):
    """Full single-test-case view. Empty optional fields collapse to "" / []."""

    id: int
    name: str
    project_id: int
    automated: bool
    description: str
    precondition: str
    expected_result: str
    status: str
    layer: str
    tags: list[str]
    created_by: str
    last_modified_by: str
    steps: list[TestCaseStepFlat]


class CustomFieldValueRef(TypedDict):
    """One custom-field value set on a test case.

    Allure's ``/cfv`` row carries the value (``id`` / ``name``) and the field
    it belongs to (``customField.id`` / ``customField.name``); we flatten both.
    """

    field_id: int
    field_name: str
    value_id: int
    value_name: str


class CustomFieldsOutput(TypedDict):
    test_case_id: int
    count: int
    custom_fields: list[CustomFieldValueRef]


class CustomFieldDef(TypedDict):
    """A custom field defined on a project (its schema, not a value)."""

    field_id: int
    name: str
    single_select: bool
    required: bool


class CustomFieldDefsOutput(TypedDict):
    project_id: int
    count: int
    custom_fields: list[CustomFieldDef]


# ── Test-case writes (opt-in via ALLURE_ENABLE_WRITE) ───────────────────────


class TestCaseCreated(TypedDict):
    """Output for :func:`allure_create_test_case`.

    ``url`` carries a best-effort deep-link to the test case in the Allure UI;
    it is ``None`` when ``ALLURE_URL`` is unset or the project id is unknown
    at response time.
    """

    id: int
    name: str
    project_id: int
    url: str | None


class TestCaseUpdated(TypedDict):
    """Output for :func:`allure_update_test_case`.

    ``updated_fields`` reflects the keys that were actually sent to Allure
    (after ``None`` stripping) — useful for the agent's audit trail.
    """

    id: int
    name: str
    updated_fields: list[str]


class TestCaseDeleted(TypedDict):
    id: int
    deleted: bool


# ── Defect categories & automation matchers ─────────────────────────────────
#
# Allure TestOps splits defect classification into two entities:
#   * Category        — a named, coloured bucket (`name` / `color` / `description`).
#   * CategoryMatcher — the regex rule (`messageRegex` / `traceRegex`) that
#                       auto-assigns failing results to a category at ingest.
# A Category alone is inert; the Matcher is what makes classification automatic
# (this is the project's "automation schema" page in the UI).


class CategorySummary(TypedDict):
    id: int
    name: str
    color: str
    description: str


class CategoriesListOutput(TypedDict):
    project_id: int
    count: int
    pagination: PaginationMeta
    categories: list[CategorySummary]


class CategoryMatcherSummary(TypedDict):
    """One regex rule. ``category_id`` / ``category_name`` denote the bucket the
    rule feeds; both are ``0`` / ``""`` if the matcher is detached from any
    category (an orphaned rule that classifies nothing)."""

    id: int
    name: str
    message_regex: str
    trace_regex: str
    category_id: int
    category_name: str


class CategoryMatchersListOutput(TypedDict):
    project_id: int
    count: int
    pagination: PaginationMeta
    matchers: list[CategoryMatcherSummary]


# ── Category / matcher writes (opt-in via ALLURE_ENABLE_WRITE) ──────────────


class CategoryCreated(TypedDict):
    id: int
    name: str
    project_id: int


class CategoryDeleted(TypedDict):
    id: int
    deleted: bool


class CategoryMatcherCreated(TypedDict):
    """Output for :func:`allure_create_category_matcher`. ``attached`` reports
    whether the matcher was linked to the project's automation schema (the
    second API step); a matcher that is created but not attached classifies
    nothing."""

    id: int
    name: str
    project_id: int
    category_id: int
    attached: bool


class CategoryMatcherDeleted(TypedDict):
    id: int
    deleted: bool
