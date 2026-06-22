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
    CategoryCreated,
    CategoryDeleted,
    CategoryMatcherCreated,
    CategoryMatcherDeleted,
    TestCaseCreated,
    TestCaseDeleted,
    TestCaseUpdated,
)

# Allure category colours are CSS hex (e.g. ``#E67E22``). The server rejects an
# empty colour with HTTP 409, so the tool defaults to a neutral grey when the
# caller omits it. The pattern is enforced at the MCP-input boundary.
_HEX_COLOR_PATTERN = r"^#[0-9A-Fa-f]{6}$"
_DEFAULT_CATEGORY_COLOR = "#9E9E9E"


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


# ── allure_create_category ───────────────────────────────────────────────────


@mcp.tool(
    name="allure_create_category",
    annotations={
        "title": "Create Defect Category",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
    structured_output=True,
)
def allure_create_category(
    project_id: Annotated[int, Field(ge=1, le=2_147_483_647, description="Allure project ID.")],
    name: Annotated[str, Field(min_length=1, max_length=255, description="Category (bucket) name.")],
    color: Annotated[
        str,
        Field(
            default=_DEFAULT_CATEGORY_COLOR,
            pattern=_HEX_COLOR_PATTERN,
            description="CSS hex colour, e.g. '#E67E22'. Defaults to neutral grey.",
        ),
    ] = _DEFAULT_CATEGORY_COLOR,
    description: Annotated[
        str | None, Field(default=None, max_length=2_000, description="Free-form description.")
    ] = None,
) -> CategoryCreated:
    """Create a defect category (named, coloured bucket) in a project.

    A category on its own classifies nothing — pair it with a matcher
    (``allure_create_category_matcher``) to auto-assign failures by regex.
    Requires ``ALLURE_ENABLE_WRITE=true``. The server rejects an empty colour
    (HTTP 409), so a default grey is sent when ``color`` is omitted.

    Examples:
        - "Add a category 'Infra: WireMock down' to project 175" ->
          ``project_id=175, name="Infra: WireMock down", color="#E67E22"``
    """
    try:
        client = get_client()
        body: dict[str, Any] = {"name": name, "projectId": project_id, "color": color}
        if description is not None:
            body["description"] = description
        created = client.post("/category", body) or {}
        new_id = int(created.get("id", 0))
        result: CategoryCreated = {"id": new_id, "name": created.get("name", name), "project_id": project_id}
        return output.ok(result, f"Created category **#{new_id}** — {result['name']} in project {project_id}")  # type: ignore[return-value]
    except Exception as exc:
        output.fail(exc, f"creating category in project {project_id}")


# ── allure_delete_category ───────────────────────────────────────────────────


@mcp.tool(
    name="allure_delete_category",
    annotations={
        "title": "Delete Defect Category",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    structured_output=True,
)
def allure_delete_category(
    category_id: Annotated[int, Field(ge=1, le=2_147_483_647, description="Allure category ID to delete.")],
    confirm: Annotated[
        Literal[True],
        Field(description="Must be exactly True — guard against accidental deletion."),
    ],
) -> CategoryDeleted:
    """Permanently delete a defect category.

    **Destructive.** Any matchers still pointing at this category are
    orphaned (they classify nothing). Requires ``ALLURE_ENABLE_WRITE=true``.

    Examples:
        - "Delete category 377" -> ``category_id=377, confirm=True``
    """
    if confirm is not True:
        output.fail(ValueError("confirm must be exactly True to delete a category"), f"deleting category {category_id}")
    try:
        client = get_client()
        client.delete(f"/category/{category_id}")
        result: CategoryDeleted = {"id": category_id, "deleted": True}
        return output.ok(result, f"Deleted category **#{category_id}**")  # type: ignore[return-value]
    except Exception as exc:
        output.fail(exc, f"deleting category {category_id}")


# ── allure_create_category_matcher ───────────────────────────────────────────


@mcp.tool(
    name="allure_create_category_matcher",
    annotations={
        "title": "Create Category Matcher",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
    structured_output=True,
)
def allure_create_category_matcher(
    project_id: Annotated[int, Field(ge=1, le=2_147_483_647, description="Allure project ID.")],
    category_id: Annotated[
        int, Field(ge=1, le=2_147_483_647, description="ID of the category this rule feeds (allure_list_categories).")
    ],
    name: Annotated[str, Field(min_length=1, max_length=255, description="Matcher name (usually the category name).")],
    message_regex: Annotated[
        str | None,
        Field(default=None, max_length=4_000, description="Java regex vs the failure message; use (?s)/(?si) flags."),
    ] = None,
    trace_regex: Annotated[
        str | None,
        Field(default=None, max_length=4_000, description="Java regex matched against the stack trace."),
    ] = None,
) -> CategoryMatcherCreated:
    """Create a regex matcher and attach it to a project's automation schema.

    This is the rule that makes a category *automatic*: at result-ingest time
    Allure assigns any failure whose message/trace matches to ``category_id``.
    Two API calls — create the matcher, then attach it to the project; the
    ``attached`` flag reports whether the second step succeeded. At least one
    of ``message_regex`` / ``trace_regex`` should be set (a matcher with
    neither classifies nothing). Requires ``ALLURE_ENABLE_WRITE=true``.

    **Existing-run caveat.** Matchers evaluate at ingest, so a new matcher does
    NOT retroactively reclassify past launches — it applies from the next run.

    Examples:
        - "Auto-route ISSO token failures to category 382 in project 175" ->
          ``project_id=175, category_id=382, name="Auth/ISSO",
          message_regex="(?s).*(unauthenticated|sign in via ISSO).*"``
    """
    if message_regex is None and trace_regex is None:
        output.fail(
            ValueError("provide at least one of message_regex / trace_regex — an empty matcher classifies nothing"),
            f"creating category matcher in project {project_id}",
        )
    try:
        client = get_client()
        body: dict[str, Any] = {"category": {"id": category_id}, "name": name, "projectId": project_id}
        if message_regex is not None:
            body["messageRegex"] = message_regex
        if trace_regex is not None:
            body["traceRegex"] = trace_regex
        created = client.post("/categorymatcher", body) or {}
        new_id = int(created.get("id", 0))
        # Attach to the project's automation schema; tolerate "already attached".
        attached = False
        if new_id:
            try:
                client.post(f"/project/{project_id}/categorymatcher", {"matcherId": new_id})
                attached = True
            except Exception:
                attached = False
        result: CategoryMatcherCreated = {
            "id": new_id,
            "name": created.get("name", name),
            "project_id": project_id,
            "category_id": category_id,
            "attached": attached,
        }
        md = f"Created matcher **#{new_id}** — {result['name']} -> category {category_id}"
        md += " (attached)" if attached else " (created; attach pending)"
        return output.ok(result, md)  # type: ignore[return-value]
    except Exception as exc:
        output.fail(exc, f"creating category matcher in project {project_id}")


# ── allure_delete_category_matcher ───────────────────────────────────────────


@mcp.tool(
    name="allure_delete_category_matcher",
    annotations={
        "title": "Delete Category Matcher",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    structured_output=True,
)
def allure_delete_category_matcher(
    matcher_id: Annotated[int, Field(ge=1, le=2_147_483_647, description="Allure matcher ID to delete.")],
    confirm: Annotated[
        Literal[True],
        Field(description="Must be exactly True — guard against accidental deletion."),
    ],
) -> CategoryMatcherDeleted:
    """Permanently delete a category matcher (regex automation rule).

    **Destructive.** Removing the matcher stops auto-classification into its
    category from the next run onward; the category bucket itself remains.
    Requires ``ALLURE_ENABLE_WRITE=true``.

    Examples:
        - "Delete matcher 278" -> ``matcher_id=278, confirm=True``
    """
    if confirm is not True:
        output.fail(
            ValueError("confirm must be exactly True to delete a matcher"), f"deleting category matcher {matcher_id}"
        )
    try:
        client = get_client()
        client.delete(f"/categorymatcher/{matcher_id}")
        result: CategoryMatcherDeleted = {"id": matcher_id, "deleted": True}
        return output.ok(result, f"Deleted matcher **#{matcher_id}**")  # type: ignore[return-value]
    except Exception as exc:
        output.fail(exc, f"deleting category matcher {matcher_id}")
