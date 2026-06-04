"""Opt-in write tools for Allure TestOps test cases.

Three tools — ``allure_create_test_case`` / ``allure_update_test_case`` /
``allure_delete_test_case`` — gated by the ``ALLURE_ENABLE_WRITE`` env var.
This module is only imported when the flag is truthy (see ``_mcp.py``), so
registration itself is the gate; a server started without the flag does
not advertise these tools to the agent at all.

**Design choices (see ``docs/superpowers/specs/2026-06-04…``).**

* ``status`` / ``layer`` / ``tags`` are received as flat strings/lists from
  the MCP caller and wrapped into Allure's nested object shape inside
  :func:`_build_testcase_body`. If a deployment requires id-based lookup
  rather than name-based, the 400 surfaces as a ``ToolError`` with the
  Allure message attached — we don't preemptively add a name-to-id lookup.
* ``allure_update_test_case`` strips ``None`` fields **before** the HTTP
  call so PATCH stays partial. An empty update is rejected with
  "nothing to update" rather than silently no-oping.
* ``allure_delete_test_case`` carries ``destructiveHint: True`` so
  compliant clients ask for per-call confirmation; the explicit
  ``confirm: Literal[True]`` parameter is the belt-and-braces guard for
  clients that ignore the annotation.
"""

from __future__ import annotations

import os
from typing import Annotated, Any, Literal

from pydantic import Field

from allure_testops_mcp import output
from allure_testops_mcp._mcp import get_client, mcp
from allure_testops_mcp.models import (
    TestCaseCreated,
    TestCaseDeleted,
    TestCaseUpdated,
)


def _build_testcase_body(fields: dict[str, Any]) -> dict[str, Any]:
    """Map MCP-flat inputs to Allure REST body shape.

    Drops ``None`` values so PATCH stays partial. Wraps named-ref fields
    (``status``, ``layer``, ``tags``) into Allure's ``{"name": ...}`` /
    ``[{"name": ...}]`` shape. Other fields pass through (with a
    snake_case → camelCase rename for the keys Allure expects).
    """
    out: dict[str, Any] = {}
    # Deterministic field order: project, name, scalars, automated, named refs, tags.
    if fields.get("project_id") is not None:
        out["projectId"] = fields["project_id"]
    if fields.get("name") is not None:
        out["name"] = fields["name"]
    if fields.get("description") is not None:
        out["description"] = fields["description"]
    if fields.get("precondition") is not None:
        out["precondition"] = fields["precondition"]
    if fields.get("expected_result") is not None:
        out["expectedResult"] = fields["expected_result"]
    if fields.get("automated") is not None:
        out["automated"] = fields["automated"]
    if fields.get("status") is not None:
        out["status"] = {"name": fields["status"]}
    if fields.get("layer") is not None:
        out["layer"] = {"name": fields["layer"]}
    if fields.get("tags") is not None:
        out["tags"] = [{"name": t} for t in fields["tags"]]
    return out


# Keys the *caller* speaks (snake_case, unwrapped). Used to report
# ``updated_fields`` back without leaking the Allure-side renames.
_CALLER_FIELDS = (
    "name",
    "description",
    "precondition",
    "expected_result",
    "automated",
    "status",
    "layer",
    "tags",
)


def _deep_link(project_id: int, test_case_id: int) -> str | None:
    """Build the Allure-UI deep link for a test case, or ``None`` if the
    base URL is not set in the process environment."""
    base = os.environ.get("ALLURE_URL", "").strip().rstrip("/")
    if not base:
        return None
    return f"{base}/project/{project_id}/test-cases/{test_case_id}"


# ── allure_create_test_case ─────────────────────────────────────────────────


@mcp.tool(
    name="allure_create_test_case",
    annotations={
        "title": "Create Test Case",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
    structured_output=True,
)
def allure_create_test_case(
    project_id: Annotated[int, Field(ge=1, le=2_147_483_647, description="Allure project ID.")],
    name: Annotated[str, Field(min_length=1, max_length=255, description="Test-case title.")],
    description: Annotated[
        str | None, Field(default=None, max_length=10_000, description="Free-form description.")
    ] = None,
    precondition: Annotated[str | None, Field(default=None, max_length=10_000, description="Setup steps.")] = None,
    expected_result: Annotated[
        str | None, Field(default=None, max_length=10_000, description="Expected outcome.")
    ] = None,
    automated: Annotated[
        bool, Field(default=False, description="True for an automated test case, False for manual.")
    ] = False,
    status: Annotated[
        str | None,
        Field(
            default=None,
            max_length=100,
            description="Status name in this project (e.g. 'Draft', 'Active'). Must exist server-side.",
        ),
    ] = None,
    layer: Annotated[
        str | None,
        Field(
            default=None,
            max_length=100,
            description="Layer name (e.g. 'API', 'E2E'). Must exist server-side.",
        ),
    ] = None,
    tags: Annotated[
        list[str] | None,
        Field(
            default=None,
            max_length=50,
            description="Tag names to attach (max 50, each max 100 chars).",
        ),
    ] = None,
) -> TestCaseCreated:
    """Create a new test case in an Allure TestOps project.

    Requires ``ALLURE_ENABLE_WRITE=true`` to be set when the server starts —
    otherwise this tool is not registered. Surfaces the Allure 400 / 409
    error text on rejection (e.g. unknown status/layer name, duplicate).

    Examples:
        - "Create a Draft TC named 'Login flow' in project 63" ->
          ``project_id=63, name="Login flow", status="Draft"``
        - "Add an automated smoke TC" -> ``automated=True, tags=["smoke"]``
    """
    if tags is not None and any(len(t) > 100 for t in tags):
        raise ValueError("each tag must be 100 characters or fewer")
    try:
        client = get_client()
        body = _build_testcase_body(
            {
                "project_id": project_id,
                "name": name,
                "description": description,
                "precondition": precondition,
                "expected_result": expected_result,
                "automated": automated,
                "status": status,
                "layer": layer,
                "tags": tags,
            }
        )
        created = client.post("/testcase", body) or {}
        new_id = int(created.get("id", 0))
        result: TestCaseCreated = {
            "id": new_id,
            "name": created.get("name", name),
            "project_id": project_id,
            "url": _deep_link(project_id, new_id) if new_id else None,
        }
        md = f"Created test case **#{new_id}** — {result['name']} in project {project_id}"
        if result["url"]:
            md += f"\n\n{result['url']}"
        return output.ok(result, md)  # type: ignore[return-value]
    except Exception as exc:
        output.fail(exc, f"creating test case in project {project_id}")


# ── allure_update_test_case ─────────────────────────────────────────────────


@mcp.tool(
    name="allure_update_test_case",
    annotations={
        "title": "Update Test Case",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
    structured_output=True,
)
def allure_update_test_case(
    test_case_id: Annotated[int, Field(ge=1, le=2_147_483_647, description="Allure test-case ID.")],
    name: Annotated[str | None, Field(default=None, min_length=1, max_length=255, description="New title.")] = None,
    description: Annotated[str | None, Field(default=None, max_length=10_000)] = None,
    precondition: Annotated[str | None, Field(default=None, max_length=10_000)] = None,
    expected_result: Annotated[str | None, Field(default=None, max_length=10_000)] = None,
    automated: Annotated[bool | None, Field(default=None)] = None,
    status: Annotated[str | None, Field(default=None, max_length=100)] = None,
    layer: Annotated[str | None, Field(default=None, max_length=100)] = None,
    tags: Annotated[list[str] | None, Field(default=None, max_length=50)] = None,
) -> TestCaseUpdated:
    """Partially update an existing test case.

    Only the fields you set are sent to Allure — the rest are left
    untouched. Pass ``tags=[]`` to clear every tag; omit ``tags`` to leave
    them as-is. Requires ``ALLURE_ENABLE_WRITE=true``.

    Examples:
        - "Rename TC 555 to 'Login (rewritten)'" -> ``test_case_id=555, name="Login (rewritten)"``
        - "Mark TC 555 automated" -> ``test_case_id=555, automated=True``
    """
    raw = {
        "name": name,
        "description": description,
        "precondition": precondition,
        "expected_result": expected_result,
        "automated": automated,
        "status": status,
        "layer": layer,
        "tags": tags,
    }
    if all(v is None for v in raw.values()):
        output.fail(
            ValueError("nothing to update — pass at least one field to change"),
            f"updating test case {test_case_id}",
        )
    if tags is not None and any(len(t) > 100 for t in tags):
        output.fail(ValueError("each tag must be 100 characters or fewer"), f"updating test case {test_case_id}")
    try:
        client = get_client()
        body = _build_testcase_body(raw)
        updated = client.patch(f"/testcase/{test_case_id}", body) or {}
        updated_fields = [k for k in _CALLER_FIELDS if raw.get(k) is not None]
        result: TestCaseUpdated = {
            "id": int(updated.get("id", test_case_id)),
            "name": updated.get("name", name or ""),
            "updated_fields": updated_fields,
        }
        md = f"Updated test case **#{result['id']}** — fields: {', '.join(updated_fields)}"
        return output.ok(result, md)  # type: ignore[return-value]
    except Exception as exc:
        output.fail(exc, f"updating test case {test_case_id}")


# ── allure_delete_test_case ─────────────────────────────────────────────────


@mcp.tool(
    name="allure_delete_test_case",
    annotations={
        "title": "Delete Test Case",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    structured_output=True,
)
def allure_delete_test_case(
    test_case_id: Annotated[int, Field(ge=1, le=2_147_483_647, description="Allure test-case ID to delete.")],
    confirm: Annotated[
        Literal[True],
        Field(
            description=(
                "Must be exactly True. Belt-and-braces guard against clients that ignore "
                "the destructiveHint annotation — without this flag, the call is rejected."
            ),
        ),
    ],
) -> TestCaseDeleted:
    """Permanently delete a test case from Allure TestOps.

    **Destructive**: the deletion is irreversible from Allure's side. The
    explicit ``confirm=True`` parameter is required so callers cannot
    delete by accident if the destructive-hint annotation is ignored.
    Requires ``ALLURE_ENABLE_WRITE=true``.

    Examples:
        - "Delete test case 555" -> ``test_case_id=555, confirm=True``
    """
    if confirm is not True:
        output.fail(
            ValueError("confirm must be exactly True to delete a test case"),
            f"deleting test case {test_case_id}",
        )
    try:
        client = get_client()
        client.delete(f"/testcase/{test_case_id}")
        result: TestCaseDeleted = {"id": test_case_id, "deleted": True}
        return output.ok(result, f"Deleted test case **#{test_case_id}**")  # type: ignore[return-value]
    except Exception as exc:
        output.fail(exc, f"deleting test case {test_case_id}")
