# Phase 4 — Harden update verb (PATCH vs PUT) ✅

**One-liner:** `allure_update_test_case` falls back from PATCH to PUT on HTTP 405.

## Accomplishments
- Added `AllureClient.put` (symmetric with `patch`; 204→`None`).
- Added `_patch_or_put(client, path, body)` in `tools_write.py`: tries `PATCH`, retries with `PUT` only on HTTP 405, re-raises every other HTTP error untouched.
- Wired the update tool through `_patch_or_put`.

## Decisions
- Runtime adaptation instead of pinning a verb: we don't know each deployment's verb a priori, and a 405-triggered fallback is correct without that knowledge — and fully mockable.
- Only 405 triggers fallback; 400/404/409 still propagate so error mapping is unchanged.

## Verification
- `tests/test_client_write.py`: PUT body/204/4xx.
- `tests/test_tools_write.py`: `test_update_falls_back_to_put_on_405` (asserts call order PATCH→PUT and identical body) and `test_update_does_not_fall_back_on_non_405` (409 → only PATCH attempted). All green.
