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
