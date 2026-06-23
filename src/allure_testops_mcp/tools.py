"""MCP tools for Allure TestOps.

13 read-only tools covering the main REST API surface — projects, launches,
test cases (list + single-case detail + custom-field values), test results,
reference data (statuses, layers, custom-field definitions), and defect
categories + automation matchers. All tools declare ``readOnlyHint: True`` so
MCP clients do not ask for per-call confirmation.

**Threading model.**

* ``allure_list_projects``, ``allure_list_launches``, ``allure_get_test_results``
  are synchronous ``def`` — FastMCP runs them in a worker thread via
  ``anyio.to_thread.run_sync`` so the asyncio event loop isn't blocked.
* ``allure_get_project_statistics``, ``allure_search_failed_tests``,
  ``allure_list_test_cases`` are ``async def`` — they take an MCP ``Context``
  and emit ``ctx.info`` / ``ctx.report_progress`` events during multi-call
  operations. Synchronous HTTP calls inside async tools are wrapped with
  ``asyncio.to_thread`` explicitly.
"""

from __future__ import annotations

import asyncio
import re
from typing import Annotated, Any, Literal

from mcp.server.fastmcp import Context
from pydantic import Field

from allure_testops_mcp import output
from allure_testops_mcp._mcp import get_client, mcp, pagination_from
from allure_testops_mcp.models import (
    CategoriesListOutput,
    CategoryMatchersListOutput,
    CategoryMatcherSummary,
    CategorySummary,
    CustomFieldDef,
    CustomFieldDefsOutput,
    CustomFieldsOutput,
    CustomFieldValueRef,
    FailedTestsOutput,
    LaunchesListOutput,
    LaunchSummary,
    LayerRef,
    LayersListOutput,
    ProjectsListOutput,
    ProjectStatistics,
    ProjectSummary,
    StatusesListOutput,
    StatusRef,
    TestCaseDetail,
    TestCasesListOutput,
    TestCaseStepFlat,
    TestCaseSummary,
    TestResultsOutput,
    TestResultSummary,
)

# ── Small response-shaping helpers (DRY) ────────────────────────────────────


_STAT_KEYS = ("passed", "failed", "broken", "skipped", "total")


def _launch_stats(launch: dict[str, Any]) -> dict[str, int]:
    """Extract a launch's ``statistic`` block into a typed dict.

    Allure's ``/launch`` response nests counts under ``launch.statistic.<key>``
    and may omit missing keys. This helper coerces them to ``int`` with a
    zero default.
    """
    stat = launch.get("statistic") or {}
    return {k: int(stat.get(k, 0) or 0) for k in _STAT_KEYS}


def _test_result_summary(r: dict[str, Any]) -> TestResultSummary:
    """Shape a single ``/testresult`` item into :class:`TestResultSummary`.

    Truncates the error text to 300 characters — agents typically need only
    the first line or two of the trace to triage a failure; the rest blows
    context.

    **Field note.** Allure's ``/testresult`` projection carries the failure
    reason in ``message`` (with the stack in ``trace``); the ``statusMessage``
    key is present in the schema but is ``null`` on this deployment. We read
    ``message`` first and fall back to ``statusMessage`` / ``trace`` so the
    ``error`` field is never silently empty for a real failure.
    """
    error = r.get("message") or r.get("statusMessage") or r.get("trace") or ""
    return {
        "id": int(r["id"]),
        "name": r.get("name", ""),
        "status": r.get("status", ""),
        "duration_ms": int(r.get("duration", 0) or 0),
        "error": error[:300],
    }


def _test_case_summary(tc: dict[str, Any]) -> TestCaseSummary:
    """Shape a single ``/testcase`` item into :class:`TestCaseSummary`.

    Allure mixes shapes across the testcase endpoints:

    * Ref-like fields (``status``, ``layer``) come as ``{"id", "name"}``
      objects or ``null`` — unwrapped to ``name``.
    * Audit fields (``createdBy``, ``lastModifiedBy``) come as plain
      username strings (e.g. ``"system"``), or ``null`` / missing.
    * ``tags`` is a list of ``{"id", "name"}`` rows; we keep only the names.

    The compact projection of plain ``GET /testcase`` omits the audit
    fields and tags entirely (they appear only on ``__search`` and detail
    responses), which is fine — missing keys collapse to ``""`` / ``[]``
    and the structured-output schema still validates.
    """
    return {
        "id": int(tc["id"]),
        "name": tc.get("name", ""),
        "automated": bool(tc.get("automated", False)),
        "status": (tc.get("status") or {}).get("name", ""),
        "layer": (tc.get("layer") or {}).get("name", ""),
        "created_by": tc.get("createdBy") or "",
        "last_modified_by": tc.get("lastModifiedBy") or "",
        "tags": [t["name"] for t in (tc.get("tags") or []) if isinstance(t, dict) and t.get("name")],
    }


# Allure usernames are alphanumeric plus a small punctuation set. Restricting
# input to that alphabet kills RQL injection at the boundary — no need to
# escape inside the query string, which Allure's RQL parser handles
# inconsistently across versions. The pattern is duplicated into the
# ``owner`` Pydantic ``Field`` below so invalid input is rejected at the
# MCP-call boundary; ``_build_owner_rql`` re-checks for defence in depth
# (and so the helper stays directly testable in isolation).
_USERNAME_PATTERN = r"^[A-Za-z0-9._@-]+$"
_USERNAME_ALPHABET_DESC = "letters, digits, '.', '_', '-', '@'"
_RQL_USERNAME_RE = re.compile(_USERNAME_PATTERN)


def _build_owner_rql(owner: str) -> str:
    """Build the RQL clause for "TCs touched by user ``owner``".

    Allure's ``GET /testcase/__search`` does not expose an ``owner`` field
    in its query language (the testcase entity simply doesn't carry a
    separate owner column on most deployments). The closest stable proxy
    is "I created it OR I last modified it", which maps to::

        createdBy = "<owner>" or lastModifiedBy = "<owner>"

    Raises:
        ValueError: if ``owner`` contains characters outside Allure's
            username alphabet (a defence against RQL-injection — the
            input is interpolated into a query string).
    """
    if not _RQL_USERNAME_RE.fullmatch(owner):
        raise ValueError(f"owner must be a plain Allure username ({_USERNAME_ALPHABET_DESC}); got {owner!r}")
    return f'createdBy = "{owner}" or lastModifiedBy = "{owner}"'


async def _report(ctx: Context, progress: float, message: str) -> None:
    """Emit a combined MCP progress + info event.

    Agents get a progress fraction (0.0-1.0) for UI / timeout decisions plus
    a human-readable message for logs. Pairing them avoids drift between the
    progress bar and the narrative.
    """
    await ctx.report_progress(progress, message=message)
    await ctx.info(message)


# ── Projects ────────────────────────────────────────────────────────────────


@mcp.tool(
    name="allure_list_projects",
    annotations={
        "title": "List Projects",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    structured_output=True,
)
def allure_list_projects(
    page: Annotated[int, Field(default=0, ge=0, description="0-based page number.")] = 0,
    size: Annotated[int, Field(default=200, ge=1, le=500, description="Items per page (1-500).")] = 200,
) -> ProjectsListOutput:
    """List all projects in the Allure TestOps instance.

    Use this first to discover which project IDs exist — all other tools
    take a ``project_id`` that you can look up here.

    Returns:
        dict with keys:
            - ``count`` (int): number of projects in this response
            - ``projects`` (list): each item has ``id``, ``name``, ``abbreviation``

    Examples:
        - "Which projects exist in Allure?" -> default call, take the names/ids
        - "Find project by abbreviation" -> iterate ``projects`` and match

        Don't use when:
        - You already know the project id (skip discovery, go straight to the target tool).
    """
    try:
        client = get_client()
        data = client.get("/project", {"page": page, "size": size})
        content = data.get("content", [])
        projects: list[ProjectSummary] = [
            {
                "id": int(p["id"]),
                "name": p.get("name", ""),
                "abbreviation": p.get("abbreviation"),
            }
            for p in content
        ]
        result: ProjectsListOutput = {"count": len(projects), "projects": projects}
        md = "\n".join([f"- **{p['id']}** — {p['name']}" for p in projects]) or "(no projects)"
        return output.ok(result, f"## Projects ({len(projects)})\n\n{md}")  # type: ignore[return-value]
    except Exception as exc:
        output.fail(exc, "listing projects")


@mcp.tool(
    name="allure_get_project_statistics",
    annotations={
        "title": "Get Project Statistics",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    structured_output=True,
)
async def allure_get_project_statistics(
    project_id: Annotated[
        int,
        Field(
            ge=1,
            le=2_147_483_647,
            description="Allure project ID (discover via allure_list_projects).",
        ),
    ],
    ctx: Context,
) -> ProjectStatistics:
    """Get summary statistics for an Allure project.

    Returns TC count, automation rate, and the last closed launch's
    pass/fail breakdown. Performs 3-4 API calls — progress is reported via
    MCP Context (visible as progress updates in compatible clients).

    Args:
        project_id: Allure project ID (see ``allure_list_projects``).
        ctx: MCP Context injected by FastMCP (used for progress reporting;
            never supplied by the agent directly).

    Returns:
        dict with keys:
            - ``project_id`` (int)
            - ``total_test_cases`` (int)
            - ``automated_test_cases`` (int)
            - ``manual_test_cases`` (int)
            - ``automation_rate_pct`` (float)
            - ``last_launch_id`` (int | None): latest *closed* launch
            - ``last_launch_name`` (str | None)
            - ``last_launch_passed`` / ``last_launch_failed`` / ``last_launch_broken`` (int)
            - ``last_launch_total`` (int)
            - ``recent_launches_count`` (int): launches examined to find the latest closed one

    Examples:
        - "How automated is project 63?" -> ``project_id=63``, read ``automation_rate_pct``
        - "What was the last passing run for project 175?" -> read ``last_launch_passed``

        Don't use when:
        - You need per-test detail (use ``allure_get_test_results``).
        - You need the full launch history (use ``allure_list_launches``).
    """
    try:
        client = get_client()

        await _report(ctx, 0.1, "fetching total test case count")
        total_data = await asyncio.to_thread(client.get, "/testcase", {"projectId": project_id, "page": 0, "size": 1})
        total_tc = int(total_data.get("totalElements", 0))

        await _report(ctx, 0.3, "fetching automated test case count")
        auto_data = await asyncio.to_thread(
            client.get,
            "/testcase",
            {"projectId": project_id, "page": 0, "size": 1, "automated": "true"},
        )
        auto_tc = int(auto_data.get("totalElements", 0))

        await _report(ctx, 0.6, "fetching recent launches")
        launches_data = await asyncio.to_thread(
            client.get,
            "/launch",
            {"projectId": project_id, "page": 0, "size": 20, "sort": "createdDate,desc"},
        )
        launches = launches_data.get("content", [])
        last = next((launch for launch in launches if launch.get("closed")), None)

        stat_map: dict[str, int] = {}
        if last:
            await _report(ctx, 0.85, f"fetching statistics for launch {last['id']}")
            stat_list = await asyncio.to_thread(client.get, f"/launch/{last['id']}/statistic")
            stat_map = {s["status"]: int(s.get("count", 0)) for s in stat_list}

        await _report(ctx, 1.0, "done")

        result: ProjectStatistics = {
            "project_id": project_id,
            "total_test_cases": total_tc,
            "automated_test_cases": auto_tc,
            "manual_test_cases": total_tc - auto_tc,
            "automation_rate_pct": round(auto_tc / total_tc * 100, 1) if total_tc else 0.0,
            "last_launch_id": int(last["id"]) if last else None,
            "last_launch_name": last.get("name", "") if last else None,
            "last_launch_passed": stat_map.get("passed", 0),
            "last_launch_failed": stat_map.get("failed", 0),
            "last_launch_broken": stat_map.get("broken", 0),
            "last_launch_total": sum(stat_map.values()),
            "recent_launches_count": len(launches),
        }
        md = (
            f"## Project {project_id}\n\n"
            f"- **Test cases:** {total_tc} ({auto_tc} automated, "
            f"{result['automation_rate_pct']}%)\n"
        )
        if last:
            md += (
                f"- **Last launch #{result['last_launch_id']}** — {result['last_launch_name']}\n"
                f"  passed={result['last_launch_passed']} / failed={result['last_launch_failed']} / "
                f"broken={result['last_launch_broken']} / total={result['last_launch_total']}\n"
            )
        return output.ok(result, md)  # type: ignore[return-value]
    except Exception as exc:
        output.fail(exc, f"getting statistics for project {project_id}")


# ── Launches ────────────────────────────────────────────────────────────────


@mcp.tool(
    name="allure_list_launches",
    annotations={
        "title": "List Launches",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    structured_output=True,
)
def allure_list_launches(
    project_id: Annotated[int, Field(ge=1, le=2_147_483_647, description="Allure project ID.")],
    page: Annotated[int, Field(default=0, ge=0, le=10_000, description="0-based page.")] = 0,
    size: Annotated[int, Field(default=20, ge=1, le=100, description="Items per page (1-100).")] = 20,
) -> LaunchesListOutput:
    """List recent launches for a project, newest first.

    Each launch carries a pass/fail/broken/skipped breakdown from Allure's
    ``statistic`` field. Pagination info is returned in the ``pagination``
    block (use ``next_page`` to continue).

    Args:
        project_id: Allure project ID.
        page: 0-based page index.
        size: Items per page (1-100; 20 is usually enough for triage).

    Returns:
        dict with keys:
            - ``project_id`` (int)
            - ``count`` (int): items in this response
            - ``pagination`` (dict): ``page`` / ``size`` / ``total`` /
              ``total_pages`` / ``has_more`` / ``next_page``
            - ``launches`` (list): each with ``id`` / ``name`` / ``status`` /
              ``created_date`` / ``passed`` / ``failed`` / ``broken`` /
              ``skipped`` / ``total``

    Examples:
        - "Last 10 launches for project 63" -> ``project_id=63, size=10``
        - "Older launches beyond page 1" -> repeat with ``page=1``

        Don't use when:
        - You need test results inside a launch (``allure_get_test_results``).
        - You need just the latest FAILED/BROKEN tests (``allure_search_failed_tests``).
    """
    try:
        client = get_client()
        data = client.get(
            "/launch",
            {
                "projectId": project_id,
                "page": page,
                "size": size,
                "sort": "createdDate,desc",
            },
        )
        launches: list[LaunchSummary] = [
            {
                "id": int(launch["id"]),
                "name": launch.get("name", ""),
                "status": launch.get("status", ""),
                "created_date": launch.get("createdDate"),
                **_launch_stats(launch),  # type: ignore[typeddict-item]
            }
            for launch in data.get("content", [])
        ]
        result: LaunchesListOutput = {
            "project_id": project_id,
            "count": len(launches),
            "pagination": pagination_from(data),  # type: ignore[typeddict-item]
            "launches": launches,
        }
        md = f"## Launches for project {project_id} ({len(launches)} shown)\n\n" + "\n".join(
            [
                f"- **#{lnch['id']}** {lnch['name']} — {lnch['status']} "
                f"(P{lnch['passed']} / F{lnch['failed']} / B{lnch['broken']} / S{lnch['skipped']})"
                for lnch in launches
            ]
        )
        return output.ok(result, md)  # type: ignore[return-value]
    except Exception as exc:
        output.fail(exc, f"listing launches for project {project_id}")


# ── Test results ────────────────────────────────────────────────────────────


StatusFilter = Literal["PASSED", "FAILED", "BROKEN", "SKIPPED"]


@mcp.tool(
    name="allure_get_test_results",
    annotations={
        "title": "Get Test Results",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    structured_output=True,
)
def allure_get_test_results(
    launch_id: Annotated[int, Field(ge=1, le=2_147_483_647, description="Allure launch ID.")],
    status: Annotated[
        StatusFilter | None,
        Field(default=None, description="Filter by status. None returns all statuses."),
    ] = None,
    page: Annotated[int, Field(default=0, ge=0, le=10_000, description="0-based page.")] = 0,
    size: Annotated[int, Field(default=50, ge=1, le=200, description="Items per page (1-200).")] = 50,
) -> TestResultsOutput:
    """Get individual test results inside a launch, optionally filtered by status.

    Args:
        launch_id: Allure launch ID (from ``allure_list_launches``).
        status: Filter — ``PASSED`` / ``FAILED`` / ``BROKEN`` / ``SKIPPED``. ``None`` returns all.
        page: 0-based page index.
        size: Items per page (1-200; default 50).

    Returns:
        dict with keys:
            - ``launch_id`` (int)
            - ``count`` (int)
            - ``pagination`` (dict)
            - ``results`` (list): each with ``id`` / ``name`` / ``status`` /
              ``duration_ms`` / ``error`` (first 300 chars of ``statusMessage``)

    Examples:
        - "FAILED tests in launch 12345" -> ``launch_id=12345, status="FAILED"``
        - "All results in launch X, second page" -> ``launch_id=X, page=1``

        Don't use when:
        - You want only FAILED+BROKEN (``allure_search_failed_tests`` does both in one call).
    """
    try:
        client = get_client()
        params: dict[str, object] = {"launchId": launch_id, "page": page, "size": size}
        if status:
            params["status"] = status
        data = client.get("/testresult", params)
        results: list[TestResultSummary] = [_test_result_summary(r) for r in data.get("content", [])]
        result: TestResultsOutput = {
            "launch_id": launch_id,
            "count": len(results),
            "pagination": pagination_from(data),  # type: ignore[typeddict-item]
            "results": results,
        }
        md = f"## Test results in launch {launch_id} ({len(results)} shown)\n\n" + "\n".join(
            [f"- **{r['status']}** {r['name']} ({r['duration_ms']} ms)" for r in results]
        )
        return output.ok(result, md)  # type: ignore[return-value]
    except Exception as exc:
        output.fail(exc, f"getting test results for launch {launch_id}")


@mcp.tool(
    name="allure_search_failed_tests",
    annotations={
        "title": "Search Failed Tests",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    structured_output=True,
)
async def allure_search_failed_tests(
    project_id: Annotated[int, Field(ge=1, le=2_147_483_647, description="Allure project ID.")],
    ctx: Context,
    launch_id: Annotated[
        int | None,
        Field(
            default=None,
            ge=1,
            le=2_147_483_647,
            description="Specific launch ID. If omitted, uses the most recent launch.",
        ),
    ] = None,
    limit: Annotated[int, Field(default=20, ge=1, le=200, description="Max failures to return per status.")] = 20,
) -> FailedTestsOutput:
    """Find FAILED and BROKEN tests in the most recent (or given) launch.

    Useful for triage: _"what's broken in the latest run"_ without listing
    every test. Performs up to 3 API calls; progress reported via MCP Context.

    Args:
        project_id: Allure project ID.
        launch_id: Specific launch ID. If ``None``, the latest launch is used.
        limit: Max failures per status (so up to ``2 * limit`` total).
        ctx: MCP Context (auto-injected).

    Returns:
        dict with keys:
            - ``launch_id`` (int): the resolved launch (latest if not passed in)
            - ``failed_count`` (int)
            - ``results`` (list): ``id`` / ``name`` / ``status`` / ``duration_ms`` / ``error``

    Examples:
        - "What's failing in project 63 right now?" -> ``project_id=63``
        - "Failures in launch 98765" -> ``project_id=N, launch_id=98765``

        Don't use when:
        - You need PASSED tests too (use ``allure_get_test_results`` without status filter).
    """
    try:
        client = get_client()

        if not launch_id:
            await _report(ctx, 0.1, "resolving latest launch")
            latest_data = await asyncio.to_thread(
                client.get,
                "/launch",
                {"projectId": project_id, "page": 0, "size": 1, "sort": "createdDate,desc"},
            )
            content = latest_data.get("content", [])
            if not content:
                empty: FailedTestsOutput = {
                    "launch_id": 0,
                    "failed_count": 0,
                    "results": [],
                    "reason": "no launches found for this project",
                }
                return output.ok(empty, "(no launches found for project)")  # type: ignore[return-value]
            launch_id = int(content[0]["id"])

        failed: list[TestResultSummary] = []
        for i, status in enumerate(("FAILED", "BROKEN")):
            await _report(ctx, 0.3 + 0.3 * i, f"fetching {status} results")
            items_data = await asyncio.to_thread(
                client.get,
                "/testresult",
                {"launchId": launch_id, "status": status, "page": 0, "size": limit},
            )
            items = items_data.get("content", [])
            failed.extend(_test_result_summary(r) for r in items)

        await _report(ctx, 1.0, "done")

        result: FailedTestsOutput = {
            "launch_id": int(launch_id),
            "failed_count": len(failed),
            "results": failed[:limit],
            "reason": None,
        }
        md = f"## Failed tests in launch {launch_id} ({len(failed)} total)\n\n" + "\n".join(
            [f"- **{r['status']}** {r['name']} — {r['error'][:120]}" for r in failed[:limit]]
        )
        return output.ok(result, md)  # type: ignore[return-value]
    except Exception as exc:
        output.fail(exc, f"searching failed tests for project {project_id}")


# ── Test cases ──────────────────────────────────────────────────────────────


@mcp.tool(
    name="allure_list_test_cases",
    annotations={
        "title": "List Test Cases",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    structured_output=True,
)
async def allure_list_test_cases(
    project_id: Annotated[int, Field(ge=1, le=2_147_483_647, description="Allure project ID.")],
    ctx: Context,
    automated: Annotated[
        bool | None,
        Field(default=None, description="True: only automated. False: only manual. None: both."),
    ] = None,
    owner: Annotated[
        str | None,
        Field(
            default=None,
            max_length=255,
            pattern=_USERNAME_PATTERN,
            description=(
                "Allure username — narrows the result to TCs where the user is the creator "
                "OR the last modifier. Applied server-side via Allure RQL (see docstring)."
            ),
        ),
    ] = None,
    page: Annotated[int, Field(default=0, ge=0, le=10_000, description="0-based page.")] = 0,
    size: Annotated[int, Field(default=50, ge=1, le=200, description="Items per page (1-200).")] = 50,
) -> TestCasesListOutput:
    """List test cases for a project with optional automation and ownership filters.

    Each TC carries ``id``, ``name``, ``automated``, ``status``, ``layer``
    (e.g. ``UNIT``, ``API``, ``E2E``), the ``createdBy`` / ``lastModifiedBy``
    audit usernames, and a flat list of tag names. **Caveat:** the audit
    fields and ``tags`` are only populated when ``owner`` is set, because
    Allure's plain ``/testcase`` endpoint returns a compact projection
    that omits them — the ``owner`` path uses ``__search`` which returns
    the full projection.

    Args:
        project_id: Allure project ID.
        ctx: MCP Context (auto-injected by FastMCP for progress reporting).
        automated: ``True`` — only automated, ``False`` — only manual,
            ``None`` — both.
        owner: Optional Allure username. When set, the response is narrowed
            to TCs where ``createdBy = owner OR lastModifiedBy = owner``
            (case-sensitive, exact match), enforced **server-side** via
            Allure's RQL ``__search`` endpoint. The username must match
            ``[A-Za-z0-9._@-]+`` — anything else is rejected at the MCP
            input layer (Pydantic ``pattern``) to prevent RQL injection.

            **Why "creator/modifier" and not "owner".** Allure TestOps does
            not expose a separate ``owner`` field in RQL on most
            deployments — the closest stable proxy for "TCs I touched" is
            the union of ``createdBy`` and ``lastModifiedBy``.

            **Trade-off when ``owner`` is set.** ``__search`` does not
            accept the ``automated`` query parameter, so an ``automated``
            filter combined with ``owner`` is applied **client-side after
            the page is fetched**. ``pagination`` then reflects the raw
            owner-filtered set, not the further automation-filtered view —
            a fetched page of 50 may shrink. Raise ``size`` (max 200) or
            iterate ``page`` for full coverage.
        page: 0-based page index.
        size: Items per page (1-200; default 50).

    Returns:
        dict with keys:
            - ``project_id`` (int)
            - ``count`` (int): items in this response (post any client-side ``automated`` filter)
            - ``pagination`` (dict): raw Allure paging
            - ``test_cases`` (list): each item carries ``id`` / ``name`` /
              ``automated`` / ``status`` / ``layer`` / ``created_by`` /
              ``last_modified_by`` / ``tags``

    Examples:
        - "How many manual TCs does project 63 have?" -> ``project_id=63, automated=False``, read ``pagination.total``
        - "First 200 automated TCs" -> ``automated=True, size=200``
        - "My manual TCs in project 63" -> ``project_id=63, automated=False, owner="jdoe", size=200``

        Don't use when:
        - You need just the automation % (``allure_get_project_statistics``).
    """
    try:
        client = get_client()
        await _report(ctx, 0.1, f"listing test cases for project {project_id}")

        if owner:
            # __search path: server-side ownership filter via RQL, rich projection.
            rql = _build_owner_rql(owner)
            params: dict[str, object] = {
                "projectId": project_id,
                "rql": rql,
                "page": page,
                "size": size,
            }
            data = await asyncio.to_thread(client.get, "/testcase/__search", params)
            raw = data.get("content", [])
            if automated is not None:
                raw = [tc for tc in raw if bool(tc.get("automated", False)) == automated]
        else:
            # Plain /testcase path: native automated filter, compact projection.
            params = {"projectId": project_id, "page": page, "size": size}
            if automated is not None:
                params["automated"] = "true" if automated else "false"
            data = await asyncio.to_thread(client.get, "/testcase", params)
            raw = data.get("content", [])

        test_cases: list[TestCaseSummary] = [_test_case_summary(tc) for tc in raw]
        await _report(ctx, 1.0, f"{len(test_cases)} test cases fetched")
        result: TestCasesListOutput = {
            "project_id": project_id,
            "count": len(test_cases),
            "pagination": pagination_from(data),  # type: ignore[typeddict-item]
            "test_cases": test_cases,
        }
        header = f"## Test cases for project {project_id} ({len(test_cases)} shown"
        if owner:
            header += f", touched by '{owner}'"
        header += ")\n\n"
        md_lines: list[str] = []
        for tc in test_cases:
            parts = ["auto" if tc["automated"] else "manual", tc["layer"] or "no-layer"]
            if tc["created_by"]:
                parts.append(f"by {tc['created_by']}")
            if tc["tags"]:
                parts.append(f"tags: {', '.join(tc['tags'])}")
            md_lines.append(f"- **#{tc['id']}** {tc['name']} ({', '.join(parts)})")
        md = header + "\n".join(md_lines)
        return output.ok(result, md)  # type: ignore[return-value]
    except Exception as exc:
        output.fail(exc, f"listing test cases for project {project_id}")


# ── Reference data: statuses & layers ───────────────────────────────────────


def _fetch_all_refs(client, path: str, project_id: int) -> list[dict]:
    """Fetch every item of a project-scoped reference list, paging through.

    Used by the status/layer list tools. These reference sets are small and
    bounded, so fetching all pages is cheap and gives the agent the full set
    in one call.
    """
    items: list[dict] = []
    page = 0
    while True:
        data = client.get(path, {"projectId": project_id, "page": page, "size": 100}) or {}
        content = data.get("content", []) or []
        items.extend(content)
        page += 1
        if page >= int(data.get("totalPages", 1) or 1) or not content:
            break
    return items


@mcp.tool(
    name="allure_list_statuses",
    annotations={
        "title": "List Statuses",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    structured_output=True,
)
def allure_list_statuses(
    project_id: Annotated[int, Field(ge=1, le=2_147_483_647, description="Allure project ID.")],
) -> StatusesListOutput:
    """List the test-case statuses defined in a project (id, name, color).

    Use this to discover valid status names/ids before setting a status on
    ``allure_create_test_case`` / ``allure_update_test_case``. Built-in
    statuses use negative ids (e.g. Draft = -1).

    Returns:
        dict with ``project_id``, ``count`` and ``statuses`` (each: ``id``,
        ``name``, ``color``).
    """
    try:
        client = get_client()
        statuses: list[StatusRef] = [
            {"id": int(s["id"]), "name": s.get("name", ""), "color": s.get("color")}
            for s in _fetch_all_refs(client, "/status", project_id)
        ]
        result: StatusesListOutput = {"project_id": project_id, "count": len(statuses), "statuses": statuses}
        md = "\n".join(f"- **{s['id']}** — {s['name']}" for s in statuses) or "(no statuses)"
        return output.ok(result, f"## Statuses in project {project_id} ({len(statuses)})\n\n{md}")  # type: ignore[return-value]
    except Exception as exc:
        output.fail(exc, f"listing statuses for project {project_id}")


@mcp.tool(
    name="allure_list_layers",
    annotations={
        "title": "List Layers",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    structured_output=True,
)
def allure_list_layers(
    project_id: Annotated[int, Field(ge=1, le=2_147_483_647, description="Allure project ID.")],
) -> LayersListOutput:
    """List the test layers defined in a project (id, name).

    Use this to discover valid layer names/ids before setting a layer on
    ``allure_create_test_case`` / ``allure_update_test_case``. Built-in
    layers use negative ids (e.g. API Tests = -3).

    Returns:
        dict with ``project_id``, ``count`` and ``layers`` (each: ``id``, ``name``).
    """
    try:
        client = get_client()
        layers: list[LayerRef] = [
            {"id": int(layer["id"]), "name": layer.get("name", "")}
            for layer in _fetch_all_refs(client, "/testlayer", project_id)
        ]
        result: LayersListOutput = {"project_id": project_id, "count": len(layers), "layers": layers}
        md = "\n".join(f"- **{layer['id']}** — {layer['name']}" for layer in layers) or "(no layers)"
        return output.ok(result, f"## Layers in project {project_id} ({len(layers)})\n\n{md}")  # type: ignore[return-value]
    except Exception as exc:
        output.fail(exc, f"listing layers for project {project_id}")


# ── Single test-case detail ─────────────────────────────────────────────────


def _flatten_steps(steps: list[dict[str, Any]] | None, depth: int = 0) -> list[TestCaseStepFlat]:
    """Flatten Allure's recursive scenario step tree into a depth-tagged list.

    Each Allure step may nest child ``steps``; we walk depth-first and record
    the nesting level so a client can re-indent without recursion.
    """
    out: list[TestCaseStepFlat] = []
    for s in steps or []:
        out.append(
            {
                "depth": depth,
                "keyword": s.get("keyword") or "",
                "name": s.get("name") or "",
                "expected_result": s.get("expectedResult") or "",
            }
        )
        out.extend(_flatten_steps(s.get("steps"), depth + 1))
    return out


@mcp.tool(
    name="allure_get_test_case",
    annotations={
        "title": "Get Test Case",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    structured_output=True,
)
def allure_get_test_case(
    test_case_id: Annotated[int, Field(ge=1, le=2_147_483_647, description="Allure test-case ID.")],
    include_scenario: Annotated[
        bool, Field(default=True, description="Also fetch the manual scenario steps (one extra call).")
    ] = True,
) -> TestCaseDetail:
    """Get one test case's full detail — fields, status/layer, tags, and steps.

    Unlike ``allure_list_test_cases`` (summaries), this returns the body of a
    single test case: description, precondition, expected result, and the
    manual scenario steps (flattened with a ``depth`` marker). Use it to read
    or review the actual content of a test case.

    Returns:
        dict with ``id``, ``name``, ``project_id``, ``automated``,
        ``description``, ``precondition``, ``expected_result``, ``status``,
        ``layer``, ``tags`` and ``steps`` (each: ``depth``, ``keyword``,
        ``name``, ``expected_result``). ``steps`` is empty when
        ``include_scenario`` is false or the case has none.
    """
    try:
        client = get_client()
        tc = client.get(f"/testcase/{test_case_id}") or {}
        steps: list[TestCaseStepFlat] = []
        if include_scenario:
            scenario = client.get(f"/testcase/{test_case_id}/scenario") or {}
            steps = _flatten_steps(scenario.get("steps"))
        result: TestCaseDetail = {
            "id": int(tc.get("id", test_case_id)),
            "name": tc.get("name", ""),
            "project_id": int(tc.get("projectId", 0) or 0),
            "automated": bool(tc.get("automated", False)),
            "description": tc.get("description") or "",
            "precondition": tc.get("precondition") or "",
            "expected_result": tc.get("expectedResult") or "",
            "status": (tc.get("status") or {}).get("name", ""),
            "layer": (tc.get("layer") or {}).get("name", ""),
            "tags": [t["name"] for t in (tc.get("tags") or []) if isinstance(t, dict) and t.get("name")],
            "created_by": tc.get("createdBy") or "",
            "last_modified_by": tc.get("lastModifiedBy") or "",
            "steps": steps,
        }
        parts = [f"# {result['name']} (#{result['id']})"]
        meta = f"status: {result['status'] or '—'} · layer: {result['layer'] or '—'} · "
        meta += "automated" if result["automated"] else "manual"
        parts.append(meta)
        if result["precondition"]:
            parts.append(f"\n**Precondition:** {result['precondition']}")
        if steps:
            parts.append("\n**Steps:**")
            parts.extend(f"{'  ' * s['depth']}- {s['keyword'] + ' ' if s['keyword'] else ''}{s['name']}" for s in steps)
        return output.ok(result, "\n".join(parts))  # type: ignore[return-value]
    except Exception as exc:
        output.fail(exc, f"getting test case {test_case_id}")


# ── Test-case custom fields ─────────────────────────────────────────────────


@mcp.tool(
    name="allure_get_test_case_custom_fields",
    annotations={
        "title": "Get Test Case Custom Fields",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    structured_output=True,
)
def allure_get_test_case_custom_fields(
    test_case_id: Annotated[int, Field(ge=1, le=2_147_483_647, description="Allure test-case ID.")],
) -> CustomFieldsOutput:
    """List the custom-field values set on a test case.

    Returns each value flattened to ``field_id`` / ``field_name`` (the custom
    field) and ``value_id`` / ``value_name`` (the chosen value) — e.g. field
    "Priority" → value "High". These are not included in
    ``allure_get_test_case``; fetch them here when you need a test case's
    custom-field assignments.
    """
    try:
        client = get_client()
        rows = client.get(f"/testcase/{test_case_id}/cfv") or []
        fields: list[CustomFieldValueRef] = []
        for row in rows:
            cf = row.get("customField") or {}
            fields.append(
                {
                    "field_id": int(cf.get("id", 0) or 0),
                    "field_name": cf.get("name", ""),
                    "value_id": int(row.get("id", 0) or 0),
                    "value_name": row.get("name", ""),
                }
            )
        result: CustomFieldsOutput = {
            "test_case_id": test_case_id,
            "count": len(fields),
            "custom_fields": fields,
        }
        md = "\n".join(f"- **{f['field_name']}**: {f['value_name']}" for f in fields) or "(no custom fields)"
        return output.ok(result, f"## Custom fields for TC #{test_case_id} ({len(fields)})\n\n{md}")  # type: ignore[return-value]
    except Exception as exc:
        output.fail(exc, f"getting custom fields for test case {test_case_id}")


@mcp.tool(
    name="allure_list_custom_fields",
    annotations={
        "title": "List Custom Fields",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    structured_output=True,
)
def allure_list_custom_fields(
    project_id: Annotated[int, Field(ge=1, le=2_147_483_647, description="Allure project ID.")],
) -> CustomFieldDefsOutput:
    """List the custom fields defined on a project (its schema).

    Returns each field's ``field_id``, ``name``, ``single_select`` and
    ``required``. Use it to discover which custom fields a project has before
    reading a test case's values with ``allure_get_test_case_custom_fields``.
    Built-in metadata fields (Epic/Feature/Story/Component/Suite) use negative
    ids; project-specific custom fields use positive ids.
    """
    try:
        client = get_client()
        rows = client.get("/cf", {"projectId": project_id}) or []
        fields: list[CustomFieldDef] = []
        for row in rows:
            inner = row.get("customField") or {}
            fields.append(
                {
                    "field_id": int(inner.get("id", row.get("id", 0)) or 0),
                    "name": row.get("name", inner.get("name", "")),
                    "single_select": bool(row.get("singleSelect", False)),
                    "required": bool(row.get("required", False)),
                }
            )
        result: CustomFieldDefsOutput = {
            "project_id": project_id,
            "count": len(fields),
            "custom_fields": fields,
        }
        md = "\n".join(f"- **{f['name']}** (#{f['field_id']}){' *required*' if f['required'] else ''}" for f in fields)
        return output.ok(result, f"## Custom fields in project {project_id} ({len(fields)})\n\n{md or '(none)'}")  # type: ignore[return-value]
    except Exception as exc:
        output.fail(exc, f"listing custom fields for project {project_id}")


# ── Defect categories & automation matchers ─────────────────────────────────


def _category_summary(c: dict[str, Any]) -> CategorySummary:
    """Shape a ``/project/{id}/category`` item into :class:`CategorySummary`."""
    return {
        "id": int(c["id"]),
        "name": c.get("name", ""),
        "color": c.get("color", ""),
        "description": c.get("description") or "",
    }


def _matcher_summary(m: dict[str, Any]) -> CategoryMatcherSummary:
    """Shape a ``/project/{id}/categorymatcher`` item into
    :class:`CategoryMatcherSummary`.

    Allure nests the target category as ``category: {id, name, ...}``; we
    flatten it to ``category_id`` / ``category_name``. A detached matcher
    (``category`` null) collapses to ``0`` / ``""``.
    """
    cat = m.get("category") or {}
    return {
        "id": int(m["id"]),
        "name": m.get("name", ""),
        "message_regex": m.get("messageRegex") or "",
        "trace_regex": m.get("traceRegex") or "",
        "category_id": int(cat.get("id", 0) or 0),
        "category_name": cat.get("name", "") or "",
    }


@mcp.tool(
    name="allure_list_categories",
    annotations={
        "title": "List Defect Categories",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    structured_output=True,
)
def allure_list_categories(
    project_id: Annotated[int, Field(ge=1, le=2_147_483_647, description="Allure project ID.")],
    page: Annotated[int, Field(default=0, ge=0, le=10_000, description="0-based page.")] = 0,
    size: Annotated[int, Field(default=100, ge=1, le=500, description="Items per page (1-500).")] = 100,
) -> CategoriesListOutput:
    """List the defect categories configured for a project.

    Categories are the named, coloured buckets shown on the project's
    *Categories* settings page (``name`` / ``color`` / ``description``). They
    are inert on their own — the regex rules that auto-assign failures live
    in ``allure_list_category_matchers``.

    Args:
        project_id: Allure project ID.
        page: 0-based page index.
        size: Items per page (1-500).

    Returns:
        dict with keys:
            - ``project_id`` (int)
            - ``count`` (int): items in this response
            - ``pagination`` (dict)
            - ``categories`` (list): each ``id`` / ``name`` / ``color`` / ``description``

    Examples:
        - "What defect categories does project 175 have?" -> ``project_id=175``

        Don't use when:
        - You want the regex automation rules (use ``allure_list_category_matchers``).
    """
    try:
        client = get_client()
        data = client.get(f"/project/{project_id}/category", {"page": page, "size": size})
        cats: list[CategorySummary] = [_category_summary(c) for c in data.get("content", [])]
        result: CategoriesListOutput = {
            "project_id": project_id,
            "count": len(cats),
            "pagination": pagination_from(data),  # type: ignore[typeddict-item]
            "categories": cats,
        }
        md = f"## Categories for project {project_id} ({len(cats)} shown)\n\n" + "\n".join(
            [f"- **#{c['id']}** {c['name']} (`{c['color']}`)" for c in cats]
        )
        return output.ok(result, md)  # type: ignore[return-value]
    except Exception as exc:
        output.fail(exc, f"listing categories for project {project_id}")


@mcp.tool(
    name="allure_list_category_matchers",
    annotations={
        "title": "List Category Matchers",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    structured_output=True,
)
def allure_list_category_matchers(
    project_id: Annotated[int, Field(ge=1, le=2_147_483_647, description="Allure project ID.")],
    page: Annotated[int, Field(default=0, ge=0, le=10_000, description="0-based page.")] = 0,
    size: Annotated[int, Field(default=200, ge=1, le=500, description="Items per page (1-500).")] = 200,
) -> CategoryMatchersListOutput:
    """List the regex automation rules (matchers) for a project.

    Each matcher carries a ``message_regex`` / ``trace_regex`` (Java regex)
    and the ``category_id`` / ``category_name`` it feeds. This is the
    project's *automation schema* — what makes failing results land in a
    category automatically at result-ingest time.

    Args:
        project_id: Allure project ID.
        page: 0-based page index.
        size: Items per page (1-500).

    Returns:
        dict with keys:
            - ``project_id`` (int)
            - ``count`` (int)
            - ``pagination`` (dict)
            - ``matchers`` (list): each ``id`` / ``name`` / ``message_regex`` /
              ``trace_regex`` / ``category_id`` / ``category_name``

    Examples:
        - "Show the auto-classification rules for project 175" -> ``project_id=175``

        Don't use when:
        - You only need the bucket names/colours (use ``allure_list_categories``).
    """
    try:
        client = get_client()
        data = client.get(f"/project/{project_id}/categorymatcher", {"page": page, "size": size})
        matchers: list[CategoryMatcherSummary] = [_matcher_summary(m) for m in data.get("content", [])]
        result: CategoryMatchersListOutput = {
            "project_id": project_id,
            "count": len(matchers),
            "pagination": pagination_from(data),  # type: ignore[typeddict-item]
            "matchers": matchers,
        }
        md = f"## Category matchers for project {project_id} ({len(matchers)} shown)\n\n" + "\n".join(
            [f"- **#{m['id']}** {m['name']} -> cat #{m['category_id']} (`{m['message_regex'][:60]}`)" for m in matchers]
        )
        return output.ok(result, md)  # type: ignore[return-value]
    except Exception as exc:
        output.fail(exc, f"listing category matchers for project {project_id}")
