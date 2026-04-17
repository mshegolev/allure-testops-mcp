"""MCP tools for Allure TestOps.

6 read-only tools covering the main REST API surface — projects, launches,
test cases, test results. All tools declare ``readOnlyHint: True`` so MCP
clients do not ask for per-call confirmation.

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
from typing import Annotated, Any, Literal

from mcp.server.fastmcp import Context
from pydantic import Field

from allure_testops_mcp import output
from allure_testops_mcp._mcp import get_client, mcp, pagination_from
from allure_testops_mcp.models import (
    FailedTestsOutput,
    LaunchesListOutput,
    LaunchSummary,
    ProjectsListOutput,
    ProjectStatistics,
    ProjectSummary,
    TestCasesListOutput,
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

    Truncates ``statusMessage`` to 300 characters — agents typically need only
    the first line or two of the trace to triage a failure; the rest blows
    context.
    """
    return {
        "id": int(r["id"]),
        "name": r.get("name", ""),
        "status": r.get("status", ""),
        "duration_ms": int(r.get("duration", 0) or 0),
        "error": (r.get("statusMessage", "") or "")[:300],
    }


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
    page: Annotated[int, Field(default=0, ge=0, le=10_000, description="0-based page.")] = 0,
    size: Annotated[int, Field(default=50, ge=1, le=200, description="Items per page (1-200).")] = 50,
) -> TestCasesListOutput:
    """List test cases for a project with optional manual/automated filter.

    Each TC returns id, name, automation flag, status and layer (e.g.
    ``UNIT``, ``API``, ``E2E``).

    Args:
        project_id: Allure project ID.
        ctx: MCP Context (auto-injected by FastMCP for progress reporting).
        automated: ``True`` — only automated, ``False`` — only manual, ``None`` — both.
        page: 0-based page index.
        size: Items per page (1-200; default 50).

    Returns:
        dict with keys:
            - ``project_id`` (int)
            - ``count`` (int)
            - ``pagination`` (dict)
            - ``test_cases`` (list): ``id`` / ``name`` / ``automated`` / ``status`` / ``layer``

    Examples:
        - "How many manual TCs does project 63 have?" -> ``project_id=63, automated=False``, read ``pagination.total``
        - "First 200 automated TCs" -> ``automated=True, size=200``

        Don't use when:
        - You need just the automation % (``allure_get_project_statistics``).
    """
    try:
        client = get_client()
        await _report(ctx, 0.1, f"listing test cases for project {project_id}")
        params: dict[str, object] = {"projectId": project_id, "page": page, "size": size}
        if automated is not None:
            params["automated"] = "true" if automated else "false"
        data = await asyncio.to_thread(client.get, "/testcase", params)
        test_cases: list[TestCaseSummary] = [
            {
                "id": int(tc["id"]),
                "name": tc.get("name", ""),
                "automated": bool(tc.get("automated", False)),
                "status": tc.get("status", ""),
                "layer": (tc.get("layer") or {}).get("name", ""),
            }
            for tc in data.get("content", [])
        ]
        await _report(ctx, 1.0, f"{len(test_cases)} test cases fetched")
        result: TestCasesListOutput = {
            "project_id": project_id,
            "count": len(test_cases),
            "pagination": pagination_from(data),  # type: ignore[typeddict-item]
            "test_cases": test_cases,
        }
        md = f"## Test cases for project {project_id} ({len(test_cases)} shown)\n\n" + "\n".join(
            [
                f"- **#{tc['id']}** {tc['name']} "
                f"({'auto' if tc['automated'] else 'manual'}, {tc['layer'] or 'no-layer'})"
                for tc in test_cases
            ]
        )
        return output.ok(result, md)  # type: ignore[return-value]
    except Exception as exc:
        output.fail(exc, f"listing test cases for project {project_id}")
