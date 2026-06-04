# Phase 1 — Name→ID lookup for status/layer ⛔ BLOCKED

**Goal:** Resolve `status`/`layer` *names* to Allure IDs before create/update, so deployments that
reject name-based payloads succeed instead of returning HTTP 400.

## Why blocked
- The existing client hits **no** status/layer listing endpoint (`tools.py` only uses `/project`,
  `/testcase`, `/testresult`).
- Allure documents the exact list endpoints + payload shapes only per-instance at
  `<instance>/swagger-ui.html`; public docs (docs.qameta.io) do not pin them.
- This environment has no `ALLURE_URL` / `ALLURE_TOKEN`, so the endpoints can't be verified.
- Shipping a guessed endpoint path into a published PyPI package is unacceptable — it would be an
  unverified claim baked into a release.

## Unblock criteria
1. Provide live Allure credentials (or the relevant Swagger excerpt for status/layer listing).
2. Implement `_resolve_ref(project_id, kind, name) -> id` using the confirmed endpoint, cached per
   process; have `_build_testcase_body` emit `{"id": ...}` when resolution succeeds, else fall back to
   the current `{"name": ...}` shape.
3. Verify end-to-end with `tests/integration/test_write_live.py::test_status_layer_by_name`
   (already written in Phase 2, gated on `ALLURE_TEST_STATUS` / `ALLURE_TEST_LAYER`).

## Current behaviour (acceptable interim)
`_build_testcase_body` wraps names as `{"name": ...}` and surfaces Allure's 400 with an actionable
message if a deployment rejects them. No silent failure.
