"""MCP tools for Allure TestOps.

6 read-only tools covering the main REST API surface — projects, launches,
test cases, test results. All tools declare ``readOnlyHint: True`` so MCP
clients do not ask for per-call confirmation.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from allure_testops_mcp import output
from allure_testops_mcp._mcp import get_client, mcp, pagination_from
from allure_testops_mcp.models import (
    FailedTestsOutput,
    LaunchesListOutput,
    LaunchSummary,
    ProjectStatistics,
    ProjectsListOutput,
    ProjectSummary,
    TestCaseSummary,
    TestCasesListOutput,
    TestResultSummary,
    TestResultsOutput,
)

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
def allure_get_project_statistics(
    project_id: Annotated[int, Field(ge=1, description="Allure project ID.")],
) -> ProjectStatistics:
    """Get summary statistics for an Allure project.

    Returns TC count, automation rate, and the last closed launch's pass/fail
    breakdown.
    """
    try:
        client = get_client()
        total_tc = int(
            client.get("/testcase", {"projectId": project_id, "page": 0, "size": 1}).get("totalElements", 0)
        )
        auto_tc = int(
            client.get(
                "/testcase",
                {"projectId": project_id, "page": 0, "size": 1, "automated": "true"},
            ).get("totalElements", 0)
        )
        launches = client.get(
            "/launch",
            {"projectId": project_id, "page": 0, "size": 20, "sort": "createdDate,desc"},
        ).get("content", [])
        last = next((launch for launch in launches if launch.get("closed")), None)

        stat_map: dict[str, int] = {}
        if last:
            stat_list = client.get(f"/launch/{last['id']}/statistic")
            stat_map = {s["status"]: int(s.get("count", 0)) for s in stat_list}

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
    project_id: Annotated[int, Field(ge=1, description="Allure project ID.")],
    page: Annotated[int, Field(default=0, ge=0, description="0-based page.")] = 0,
    size: Annotated[int, Field(default=20, ge=1, le=100, description="Items per page (1-100).")] = 20,
) -> LaunchesListOutput:
    """List recent launches for a project, newest first.

    Each launch carries a pass/fail/broken/skipped breakdown from Allure's
    statistic field.
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
                "passed": int(launch.get("statistic", {}).get("passed", 0)),
                "failed": int(launch.get("statistic", {}).get("failed", 0)),
                "broken": int(launch.get("statistic", {}).get("broken", 0)),
                "skipped": int(launch.get("statistic", {}).get("skipped", 0)),
                "total": int(launch.get("statistic", {}).get("total", 0)),
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
    launch_id: Annotated[int, Field(ge=1, description="Allure launch ID.")],
    status: Annotated[
        StatusFilter | None,
        Field(default=None, description="Filter by status. None returns all statuses."),
    ] = None,
    page: Annotated[int, Field(default=0, ge=0, description="0-based page.")] = 0,
    size: Annotated[int, Field(default=50, ge=1, le=200, description="Items per page (1-200).")] = 50,
) -> TestResultsOutput:
    """Get individual test results inside a launch, optionally filtered by status.

    Use ``allure_search_failed_tests`` for a quick view of only failures.
    """
    try:
        client = get_client()
        params: dict[str, object] = {"launchId": launch_id, "page": page, "size": size}
        if status:
            params["status"] = status
        data = client.get("/testresult", params)
        results: list[TestResultSummary] = [
            {
                "id": int(r["id"]),
                "name": r.get("name", ""),
                "status": r.get("status", ""),
                "duration_ms": int(r.get("duration", 0) or 0),
                "error": (r.get("statusMessage", "") or "")[:300],
            }
            for r in data.get("content", [])
        ]
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
def allure_search_failed_tests(
    project_id: Annotated[int, Field(ge=1, description="Allure project ID.")],
    launch_id: Annotated[
        int | None,
        Field(default=None, description="Specific launch ID. If omitted, uses the most recent launch."),
    ] = None,
    limit: Annotated[int, Field(default=20, ge=1, le=200, description="Max failures to return per status.")] = 20,
) -> FailedTestsOutput:
    """Find FAILED and BROKEN tests in the most recent (or given) launch.

    Useful for triage: _"what's broken in the latest run"_ without listing
    everything.
    """
    try:
        client = get_client()
        if not launch_id:
            content = client.get(
                "/launch",
                {"projectId": project_id, "page": 0, "size": 1, "sort": "createdDate,desc"},
            ).get("content", [])
            if not content:
                result: FailedTestsOutput = {"launch_id": 0, "failed_count": 0, "results": []}
                return output.ok(result, "(no launches found for project)")  # type: ignore[return-value]
            launch_id = int(content[0]["id"])

        failed: list[TestResultSummary] = []
        for status in ("FAILED", "BROKEN"):
            items = client.get(
                "/testresult",
                {"launchId": launch_id, "status": status, "page": 0, "size": limit},
            ).get("content", [])
            for r in items:
                failed.append(
                    {
                        "id": int(r["id"]),
                        "name": r.get("name", ""),
                        "status": r.get("status", ""),
                        "duration_ms": int(r.get("duration", 0) or 0),
                        "error": (r.get("statusMessage", "") or "")[:300],
                    }
                )

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
def allure_list_test_cases(
    project_id: Annotated[int, Field(ge=1, description="Allure project ID.")],
    automated: Annotated[
        bool | None,
        Field(default=None, description="True: only automated. False: only manual. None: both."),
    ] = None,
    page: Annotated[int, Field(default=0, ge=0, description="0-based page.")] = 0,
    size: Annotated[int, Field(default=50, ge=1, le=200, description="Items per page (1-200).")] = 50,
) -> TestCasesListOutput:
    """List test cases for a project with optional manual/automated filter.

    Each TC returns id, name, automation flag, status and layer (e.g. ``UNIT``,
    ``API``, ``E2E``).
    """
    try:
        client = get_client()
        params: dict[str, object] = {"projectId": project_id, "page": page, "size": size}
        if automated is not None:
            params["automated"] = "true" if automated else "false"
        data = client.get("/testcase", params)
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
