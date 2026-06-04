# Allure TestOps MCP — Test-case write operations

**Date:** 2026-06-04
**Status:** Approved (pending implementation)
**Target:** PR into upstream `mshegolev/allure-testops-mcp`

## Summary

Add three new MCP tools to the Allure TestOps MCP server — `allure_create_test_case`, `allure_update_test_case`, `allure_delete_test_case` — gated behind an opt-in environment variable so the server's existing read-only default is preserved.

## Motivation

The current server exposes 6 read-only tools. Users running test-management workflows through an LLM agent need to author and maintain test cases as part of the same conversation, not switch to the Allure UI. Read-only coverage forces an awkward split. The cost of adding write is real (it breaks the "no write operations exposed" promise in the README), so the design isolates the risk behind an explicit opt-in and a destructive-hint annotation on delete.

## Non-goals

- Test results (`/testresult` POST) — out of scope; usually populated by CI runners.
- Shared steps, test plans, custom fields, workflow transitions beyond the `status` name.
- Bulk operations (`/__bulk`). One TC per call.
- Step-level scenario editing as a structured array.
- A separate idempotency / retry layer.

## Design

### 1. Opt-in via environment variable

A single new env var:

| Variable | Required | Default | Description |
|---|---|---|---|
| `ALLURE_ENABLE_WRITE` | no | `false` | When `true`, three write tools are registered. When unset or `false`, the server exposes only the 6 read-only tools (current behavior). |

Parsed once at server start by `_mcp.py` using the existing `_parse_bool` helper from `client.py`. The check happens **before** importing the write-tools module, so tool registration is the gate — not a per-call check.

Rationale: a tool that registers but always errors at call time wastes agent planning tokens and misleads the model. Not showing the tool at all is the honest signal.

### 2. HTTP client extension (`client.py`)

Add three methods to `AllureClient`, symmetric with the existing `get`:

```python
def post(self, path: str, json_body: dict[str, Any] | None = None) -> Any
def patch(self, path: str, json_body: dict[str, Any] | None = None) -> Any
def delete(self, path: str) -> Any
```

- Same 30s timeout, same `raise_for_status()`, same session (already configured with `Api-Token`, JSON content type, SSL verify, no proxy).
- `delete` returns `None` for empty responses (HTTP 204); otherwise parses JSON.
- No retry, no idempotency keys, no instrumentation beyond what `get` already has. YAGNI.

### 3. New module `tools_write.py`

A separate module so the opt-in flag is enforced by **conditional import** in `_mcp.py`:

```python
if _parse_bool(os.environ.get("ALLURE_ENABLE_WRITE"), default=False):
    from allure_testops_mcp import tools_write  # noqa: F401
```

`tools.py` is untouched.

### 4. Tool: `allure_create_test_case`

**Signature:**

```python
project_id: int (ge=1, le=2_147_483_647)
name: str (min_length=1, max_length=255)
description: str | None = None
precondition: str | None = None
expected_result: str | None = None
automated: bool = False
status: str | None = None        # status name, e.g. "Draft" / "Active"
layer: str | None = None         # layer name, e.g. "API" / "E2E"
tags: list[str] | None = None    # each tag max 100 chars, max 50 tags
```

**HTTP:** `POST /testcase` (path confirmed during implementation).

**Body assembly:** via `_build_testcase_body` helper (see §6).

**Returns** (`TestCaseCreated` TypedDict):

```python
{
    "id": int,
    "name": str,
    "project_id": int,
    "url": str | None,   # deep-link if ALLURE_URL allows; null otherwise
}
```

**Annotations:**
- `readOnlyHint: False`
- `destructiveHint: False`
- `idempotentHint: False`
- `openWorldHint: True`

### 5. Tool: `allure_update_test_case`

**Signature:**

```python
test_case_id: int (ge=1, le=2_147_483_647)
name: str | None = None
description: str | None = None
precondition: str | None = None
expected_result: str | None = None
automated: bool | None = None
status: str | None = None
layer: str | None = None
tags: list[str] | None = None
```

**HTTP:** `PATCH /testcase/{id}` (method and path confirmed during implementation — may be `PUT` depending on Allure version; this changes only the inner `client.patch` vs `client.put` call, not the tool surface).

**Semantics:** partial update. Before serializing, the implementation strips all `None`-valued fields so unmentioned fields are not overwritten. If the resulting payload is empty (caller passed nothing beyond `test_case_id`), a Pydantic model-level validator raises "nothing to update" before the HTTP call.

**Returns** (`TestCaseUpdated` TypedDict):

```python
{
    "id": int,
    "name": str,             # actual name from Allure's response
    "updated_fields": list[str],
}
```

**Annotations:** same as create.

### 6. Tool: `allure_delete_test_case`

**Signature:**

```python
test_case_id: int (ge=1, le=2_147_483_647)
confirm: Literal[True]   # required explicit flag
```

**HTTP:** `DELETE /testcase/{id}`.

**Returns** (`TestCaseDeleted` TypedDict):

```python
{
    "id": int,
    "deleted": True,
}
```

**Annotations:**
- `readOnlyHint: False`
- `destructiveHint: True`   ← compliant MCP clients require per-call confirmation
- `idempotentHint: True`
- `openWorldHint: True`

The `confirm: Literal[True]` parameter is a belt-and-braces measure for clients that ignore `destructiveHint`. Pydantic rejects the call if absent or not exactly `True`.

### 7. Allure body shape — shared helper

Allure's REST accepts nested objects for `status` / `layer` / `tags`, not flat strings. The mapping is the same for create and update, so it lives in one private helper alongside `_test_case_summary`:

```python
def _build_testcase_body(fields: dict[str, Any]) -> dict[str, Any]:
    """Map MCP-flat inputs to Allure REST body shape.

    - name / description / precondition / expectedResult / automated → as-is
    - status (str)  → {"status": {"name": <s>}}
    - layer  (str)  → {"layer":  {"name": <s>}}
    - tags   (list) → {"tags":   [{"name": t} for t in tags]}
    - None values are dropped (so PATCH stays partial).
    """
```

If a particular Allure deployment rejects name-based status/layer (some require `id`), surface the 400 error message — we don't preemptively add a name-to-id lookup. That can be revisited as a follow-up if it becomes a real problem.

### 8. Models (`models.py`)

Add three new output TypedDicts, matching the existing style (Py-version-aware `TypedDict` import, every key required, optional values as `T | None`):

- `TestCaseCreated`
- `TestCaseUpdated`
- `TestCaseDeleted`

Input validation lives in `Annotated[..., Field(...)]` directly on tool signatures (consistent with existing code).

### 9. Error handling (`errors.py`)

Existing mappings cover 401/403/404/429/5xx. Add or verify:

- **400 Bad Request** — common on write when `status` / `layer` name doesn't exist or required field is missing. User-facing message: *"Allure rejected the payload — check that 'status' and 'layer' names exist in this project, and that all required fields are set"*.
- **409 Conflict** — duplicate name or stale state. Message: *"Allure conflict — likely a duplicate or stale state; re-fetch and retry"*.

If `errors.py` already has a generic 4xx fallback, these may already be covered with acceptable wording; the implementation step verifies and only adds what's missing.

### 10. Registration flow in `_mcp.py`

Pseudocode:

```python
from allure_testops_mcp.client import _parse_bool
# ... existing mcp = FastMCP(...) ...
from allure_testops_mcp import tools  # always
if _parse_bool(os.environ.get("ALLURE_ENABLE_WRITE"), default=False):
    from allure_testops_mcp import tools_write  # noqa: F401
```

No flag is exposed in tool responses, no log line that echoes the token — same hygiene as elsewhere.

## Testing

New test files under `tests/`:

- **`test_client_write.py`** — POST/PATCH/DELETE call the right URL with the right body / no body; 204 yields `None`; 400 / 409 paths.
- **`test_tools_write.py`** —
  - `create`: happy path; body mapping for status/layer/tags is correct; `automated` defaults to `False`.
  - `update`: `None` fields are stripped; empty-update raises validation error; `updated_fields` reflects what was sent.
  - `delete`: missing `confirm` rejected by Pydantic; `confirm=False` rejected; `confirm=True` calls the right endpoint.
- **`test_mcp_registration.py`** — short: when `ALLURE_ENABLE_WRITE` is unset/false, the FastMCP registry contains only the 6 existing tool names; when `true`, it contains 9.

No integration tests against a live Allure instance — out of scope for unit CI.

## Documentation changes

- **README.md**
  - "Design highlights": add a bullet that write is opt-in via env var.
  - "Features": new "Write (opt-in)" subsection listing the three tools.
  - "Environment variables": add `ALLURE_ENABLE_WRITE` row.
  - "Security considerations": replace the "No write operations exposed" bullet with the gated-write explanation and call out `destructiveHint: True` on delete.
- **.env.example**: add `ALLURE_ENABLE_WRITE=false` with a brief comment about scope and risks.
- **CHANGELOG.md**: new "Unreleased" section describing the addition.

## Open questions / deferred

1. **Exact Allure endpoint method (PATCH vs PUT) and path** for update — resolved at implementation time via Swagger / curl against the target instance. Only affects one line inside `update`.
2. **Name vs ID for status / layer** — design assumes name-based lookup works; falls back to surfacing the 400 if not. ID-based lookup helper can be a follow-up.
3. **Deep-link URL builder** — best-effort; if `ALLURE_URL` doesn't allow a deterministic construction for a given test case, `url` returns `null` and we don't add a separate lookup.

## File-level change summary

| File | Change |
|---|---|
| `src/allure_testops_mcp/client.py` | + `post`, `patch`, `delete` methods (~30 lines) |
| `src/allure_testops_mcp/tools_write.py` | **NEW** — 3 tools + body-mapper helper (~250 lines) |
| `src/allure_testops_mcp/models.py` | + 3 TypedDicts (~25 lines) |
| `src/allure_testops_mcp/_mcp.py` | + conditional import of `tools_write` (~3 lines) |
| `src/allure_testops_mcp/errors.py` | + 400 / 409 mappings if missing (~10 lines) |
| `tests/test_client_write.py` | NEW |
| `tests/test_tools_write.py` | NEW |
| `tests/test_mcp_registration.py` | NEW (short) |
| `README.md` | Sections: Design highlights, Features, Env vars, Security |
| `.env.example` | + `ALLURE_ENABLE_WRITE=false` |
| `CHANGELOG.md` | + Unreleased section |
