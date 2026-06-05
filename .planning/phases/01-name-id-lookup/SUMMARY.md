# Phase 1 — Name→ID lookup for status/layer 🟡 PARTIAL (v0.4.1)

**One-liner:** Corrected the status/layer write shapes and added id-based params; name→id
auto-resolution still pending live verification.

## Research (ground truth)
Verified against `eroshenkoam/allure-testops-utils` (an Allure maintainer's Java client):
- create `POST /api/rs/testcase` (`TestCase` DTO) → **nested** `status:{id,name,color}`, `layer:{id,name}`, `tags:[{id,name}]`.
- update `PATCH /api/rs/testcase/{id}` (`TestCasePatch` DTO) → **flat** `statusId`, `testLayerId`; no nested status/layer field.

## Bug found & fixed
The previous `_build_testcase_body` emitted `{"status":{"name":…}}` for **both** ops, so name-based
status/layer on **update was silently ignored** (unknown keys dropped by Allure). Now:
- create: nested `{id}` (or best-effort `{name}`);
- update: flat `statusId` / `testLayerId`; a *name* on update raises an actionable error.

## Shipped (v0.4.1)
- `status_id` / `layer_id` params on create + update (id wins over name).
- Operation-aware `_build_testcase_body(fields, *, mode)`; `_apply_ref` helper.
- 9 new unit tests (builder shapes per mode + tool-level flat/nested id bodies + name-on-update rejection). 125 tests pass, ruff clean.

## Still blocked (→ deferred)
Name→id **auto-resolution** needs the project status/layer **list endpoints**, which neither
authoritative client exposes and public docs don't pin. Requires live Allure creds (user agreed to
provide) to confirm the endpoints and verify end-to-end via `tests/integration/test_write_live.py`.

## Next (on creds)
1. Confirm list endpoints (likely `GET /api/rs/...` for statuses/layers, project-scoped).
2. Add `_resolve_ref(project_id, kind, name) -> id`, cached; map name→id then reuse the id path above.
3. Verify with the integration suite (`test_status_layer_by_name`).

---

## v0.4.2 — COMPLETE (name→id resolver)

**Live-confirmed endpoints** (against allure.services.mts.ru, project 2031):
- statuses: `GET /api/rs/status?projectId=…` (paged) — 23 found; `Draft=-1`, `Active=-3`, `Blocked=5`
- layers:   `GET /api/rs/testlayer?projectId=…` (paged) — 19 found; `API Tests=-3`, `UI Tests=-2`

**Shipped:**
- `_list_refs` (paged), `_resolve_ref` (case-insensitive, actionable not-found error), `_project_id_of`.
- create + update resolve `status`/`layer` names → ids, then emit the correct shape (nested `{id}` / flat `statusId`,`testLayerId`).
- Relaxed `status_id`/`layer_id` bounds to int32 (built-in ids are negative — the old `ge=1` would reject `Draft=-1`).
- update accepts names again (v0.4.1 had hard-rejected them).

**Verified:**
- Resolver verified LIVE read-only (`draft`→-1, `API Tests`→-3, unknown→error).
- 129 unit tests pass (incl. resolver paging, case-insensitivity, create/update name→id, unknown-name errors); ruff clean.

**Residual (not blocking):** live create/update/delete mutation needs a **write-scoped** token — the
aiqa-core token is read-only (create returned HTTP 403, cleanly surfaced). The gated suite
`tests/integration/test_write_live.py` performs the full live mutation once such a token + project id
are provided.
