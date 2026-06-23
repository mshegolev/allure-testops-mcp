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

import requests
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


def _build_testcase_body(fields: dict[str, Any], *, mode: str = "create") -> dict[str, Any]:
    """Map MCP-flat inputs to the Allure REST body shape for ``mode``.

    Allure's create and update endpoints take *different* shapes for status
    and layer — verified against the official Allure client
    (``eroshenkoam/allure-testops-utils``):

    * **create** (``POST /testcase`` — ``TestCase`` DTO) uses nested objects:
      ``status: {"id": …}`` / ``layer: {"id": …}`` (or ``{"name": …}`` as a
      best-effort when only a name is known).
    * **update** (``PATCH /testcase/{id}`` — ``TestCasePatch`` DTO) uses flat
      numeric ids: ``statusId`` and ``testLayerId``. The patch DTO has *no*
      nested status/layer field, so a name cannot be sent on update — callers
      must pass ``status_id`` / ``layer_id``.

    ``status_id`` / ``layer_id`` take precedence over the name variants.
    Drops ``None`` values so PATCH stays partial. Tags are always
    ``[{"name": …}]`` (the ``TestTag`` shape).

    Raises:
        ValueError: if a status/layer *name* (not id) is given in update mode.
    """
    out: dict[str, Any] = {}
    # Deterministic field order: project, name, scalars, automated, refs, tags.
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

    _apply_ref(out, mode, kind="status", ref_id=fields.get("status_id"), name=fields.get("status"))
    _apply_ref(out, mode, kind="layer", ref_id=fields.get("layer_id"), name=fields.get("layer"))

    if fields.get("tags") is not None:
        out["tags"] = [{"name": t} for t in fields["tags"]]
    return out


# Per-operation field names for the two named refs (verified against the
# Allure ``TestCase`` / ``TestCasePatch`` DTOs).
_UPDATE_ID_KEY = {"status": "statusId", "layer": "testLayerId"}
_CREATE_OBJ_KEY = {"status": "status", "layer": "layer"}


def _apply_ref(out: dict[str, Any], mode: str, *, kind: str, ref_id: int | None, name: str | None) -> None:
    """Emit the status/layer reference into ``out`` using the right shape.

    id wins over name. On update, only ids are valid (the patch DTO has no
    nested name field); a name raises so the caller gets an actionable error
    instead of a silently-ignored payload.
    """
    if ref_id is not None:
        if mode == "update":
            out[_UPDATE_ID_KEY[kind]] = ref_id
        else:
            out[_CREATE_OBJ_KEY[kind]] = {"id": ref_id}
        return
    if name is not None:
        if mode == "update":
            raise ValueError(
                f"Allure's test-case update API takes a numeric {kind} id, not a name — "
                f"pass {kind}_id=<id>. (Name→id auto-resolution is not yet available; "
                f"look up the id in Allure or via the project's {kind} list.)"
            )
        out[_CREATE_OBJ_KEY[kind]] = {"name": name}


# Keys the *caller* speaks (snake_case, unwrapped). Used to report
# ``updated_fields`` back without leaking the Allure-side renames.
_CALLER_FIELDS = (
    "name",
    "description",
    "precondition",
    "expected_result",
    "automated",
    "status",
    "status_id",
    "layer",
    "layer_id",
    "tags",
)


def _patch_or_put(client: Any, path: str, body: dict[str, Any]) -> Any:
    """Update via PATCH, falling back to PUT on HTTP 405.

    Allure's test-case update verb varies by deployment/version — some
    instances expose ``PATCH /testcase/{id}``, others only ``PUT``. Rather
    than pinning one (and silently breaking on the other), we try PATCH and,
    if the server answers 405 Method Not Allowed, transparently retry with
    PUT. Any other HTTP error propagates unchanged so the caller's error
    mapping still surfaces 400/404/409/etc.
    """
    try:
        return client.patch(path, body)
    except requests.HTTPError as exc:
        resp = getattr(exc, "response", None)
        if resp is not None and resp.status_code == 405:
            return client.put(path, body)
        raise


def _list_refs(client: Any, kind: str, project_id: int) -> dict[str, int]:
    """Return ``{name: id}`` for a project's statuses or layers.

    Endpoints (confirmed against a live Allure TestOps instance):

    * status → ``GET /status?projectId=…`` (paged)
    * layer  → ``GET /testlayer?projectId=…`` (paged)

    Built-in refs use negative ids (e.g. ``Draft = -1``, ``API Tests = -3``);
    custom ones are positive. Pages through ``content`` / ``totalPages``.
    """
    path = "/status" if kind == "status" else "/testlayer"
    refs: dict[str, int] = {}
    page = 0
    while True:
        data = client.get(path, {"projectId": project_id, "page": page, "size": 100}) or {}
        content = data.get("content", []) or []
        for item in content:
            name, rid = item.get("name"), item.get("id")
            if name is not None and rid is not None:
                refs[str(name)] = int(rid)
        page += 1
        if page >= int(data.get("totalPages", 1) or 1) or not content:
            break
    return refs


def _resolve_ref(client: Any, kind: str, project_id: int, name: str) -> int:
    """Resolve a status/layer *name* to its numeric id within a project.

    Case-insensitive. Raises ValueError listing the valid names if the name
    is not found — an actionable error instead of a downstream 400.
    """
    refs = _list_refs(client, kind, project_id)
    by_lower = {n.lower(): i for n, i in refs.items()}
    rid = by_lower.get(name.strip().lower())
    if rid is None:
        available = ", ".join(sorted(refs)) or "(none)"
        raise ValueError(f"{kind} '{name}' not found in project {project_id}. Available {kind} names: {available}")
    return rid


def _project_id_of(client: Any, test_case_id: int) -> int:
    """Fetch a test case's ``projectId`` (needed to resolve project-scoped refs on update)."""
    tc = client.get(f"/testcase/{test_case_id}") or {}
    pid = tc.get("projectId")
    if pid is None:
        raise ValueError(
            f"could not determine the project of test case {test_case_id} (needed to resolve status/layer)"
        )
    return int(pid)


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
            description="Status name in this project (e.g. 'Draft', 'Active'). Must exist server-side. "
            "Prefer status_id if you know the numeric id.",
        ),
    ] = None,
    status_id: Annotated[
        int | None,
        Field(
            default=None,
            ge=-2_147_483_648,
            le=2_147_483_647,
            description="Numeric status id (takes precedence over status). Built-ins are negative, e.g. Draft=-1.",
        ),
    ] = None,
    layer: Annotated[
        str | None,
        Field(
            default=None,
            max_length=100,
            description="Layer name (e.g. 'API', 'E2E'). Resolved to its id server-side.",
        ),
    ] = None,
    layer_id: Annotated[
        int | None,
        Field(
            default=None,
            ge=-2_147_483_648,
            le=2_147_483_647,
            description="Numeric layer id (takes precedence over layer). Built-ins are negative, e.g. API Tests=-3.",
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

    Status and layer accept either a ``status_id`` / ``layer_id`` (used as-is)
    or a ``status`` / ``layer`` *name*, which is resolved to its id against the
    project's status/layer list. An unknown name yields an actionable error
    listing the valid names.

    Examples:
        - "Create a Draft TC named 'Login flow' in project 63" ->
          ``project_id=63, name="Login flow", status="Draft"``
        - "Add an automated smoke TC" -> ``automated=True, tags=["smoke"]``
    """
    if tags is not None and any(len(t) > 100 for t in tags):
        raise ValueError("each tag must be 100 characters or fewer")
    try:
        client = get_client()
        # Resolve status/layer names to ids against the project's ref lists.
        if status_id is None and status is not None:
            status_id, status = _resolve_ref(client, "status", project_id, status), None
        if layer_id is None and layer is not None:
            layer_id, layer = _resolve_ref(client, "layer", project_id, layer), None
        body = _build_testcase_body(
            {
                "project_id": project_id,
                "name": name,
                "description": description,
                "precondition": precondition,
                "expected_result": expected_result,
                "automated": automated,
                "status_id": status_id,
                "layer_id": layer_id,
                "tags": tags,
            },
            mode="create",
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
    status_id: Annotated[
        int | None,
        Field(default=None, ge=-2_147_483_648, le=2_147_483_647, description="Numeric status id (e.g. Draft=-1)."),
    ] = None,
    layer_id: Annotated[
        int | None,
        Field(default=None, ge=-2_147_483_648, le=2_147_483_647, description="Numeric layer id (e.g. API Tests=-3)."),
    ] = None,
    status: Annotated[
        str | None,
        Field(default=None, max_length=100, description="Status name — resolved to its id via the TC's project."),
    ] = None,
    layer: Annotated[
        str | None,
        Field(default=None, max_length=100, description="Layer name — resolved to its id via the TC's project."),
    ] = None,
    tags: Annotated[list[str] | None, Field(default=None, max_length=50)] = None,
) -> TestCaseUpdated:
    """Partially update an existing test case.

    Only the fields you set are sent to Allure — the rest are left
    untouched. Pass ``tags=[]`` to clear every tag; omit ``tags`` to leave
    them as-is. Requires ``ALLURE_ENABLE_WRITE=true``.

    Status and layer accept a ``status_id`` / ``layer_id`` (sent as Allure's
    flat ``statusId`` / ``testLayerId``) or a ``status`` / ``layer`` *name*,
    which is resolved to its id — this performs an extra lookup of the test
    case's project. An unknown name yields an actionable error.

    Examples:
        - "Rename TC 555 to 'Login (rewritten)'" -> ``test_case_id=555, name="Login (rewritten)"``
        - "Mark TC 555 automated" -> ``test_case_id=555, automated=True``
        - "Set TC 555 status to Active" -> ``test_case_id=555, status="Active"``
    """
    provided = (name, description, precondition, expected_result, automated, status, status_id, layer, layer_id, tags)
    if all(v is None for v in provided):
        output.fail(
            ValueError("nothing to update — pass at least one field to change"),
            f"updating test case {test_case_id}",
        )
    if tags is not None and any(len(t) > 100 for t in tags):
        output.fail(ValueError("each tag must be 100 characters or fewer"), f"updating test case {test_case_id}")
    try:
        client = get_client()
        # Resolve status/layer names to ids. Refs are project-scoped, so we
        # first learn the test case's project.
        if (status_id is None and status is not None) or (layer_id is None and layer is not None):
            pid = _project_id_of(client, test_case_id)
            if status_id is None and status is not None:
                status_id, status = _resolve_ref(client, "status", pid, status), None
            if layer_id is None and layer is not None:
                layer_id, layer = _resolve_ref(client, "layer", pid, layer), None
        raw = {
            "name": name,
            "description": description,
            "precondition": precondition,
            "expected_result": expected_result,
            "automated": automated,
            "status_id": status_id,
            "layer_id": layer_id,
            "tags": tags,
        }
        body = _build_testcase_body(raw, mode="update")
        updated = _patch_or_put(client, f"/testcase/{test_case_id}", body) or {}
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
