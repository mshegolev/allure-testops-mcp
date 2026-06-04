# ROADMAP — Milestone v0.4 (Quality & robustness hardening)

Derived from the "Open questions / deferred" section of
`docs/superpowers/specs/2026-06-04-allure-write-test-cases-design.md` and the Tech-Debt section of
`.planning/reports/MILESTONE_SUMMARY-v0.3.md`. Scope chosen by the user on 2026-06-05.

| # | Phase | Status | One-liner |
|---|-------|--------|-----------|
| 1 | Name→ID lookup for status/layer | ⛔ blocked | Resolve status/layer names to Allure IDs before write |
| 2 | Live-instance integration tests | ✅ complete | Gated pytest suite exercising create/update/delete against a real Allure project |
| 3 | Version single-source-of-truth | ✅ complete | Eliminate 3-place version drift; CI asserts consistency |
| 4 | Harden update verb (PATCH vs PUT) | ✅ complete | Runtime 405→PUT fallback so update survives Allure version differences |

## Phase details

### Phase 1 — Name→ID lookup for status/layer  ⛔ BLOCKED
**Goal:** Before create/update, resolve `status`/`layer` *names* to Allure IDs so deployments that
reject name-based payloads succeed instead of returning HTTP 400.
**Blocker:** The existing code hits no status/layer listing endpoint, and the exact endpoint paths +
payload shapes are documented only per-instance at `<instance>/swagger-ui.html`. Public docs do not
pin them, and this environment has no `ALLURE_URL`/`ALLURE_TOKEN`. Shipping a guessed endpoint into a
published package is unacceptable. **Unblock by:** providing live Allure credentials (or the relevant
Swagger excerpt), then the Phase 2 integration suite verifies the resolution end-to-end.

### Phase 2 — Live-instance integration tests  ✅
**Goal:** An opt-in, env-gated pytest suite that runs create→update→delete against a throwaway Allure
project. Skipped (not failed) when credentials are absent, so CI stays green. Doubles as the
verification vehicle for Phases 1 and 4 once credentials exist.

### Phase 3 — Version single-source-of-truth  ✅
**Goal:** `__version__` derived from installed package metadata (cannot drift); a consistency test
asserts `pyproject.toml` == both `server.json` version fields. Prevents the `0.1.2` drift that recurred.

### Phase 4 — Harden update verb (PATCH vs PUT)  ✅
**Goal:** `allure_update_test_case` tries PATCH and, on HTTP 405 Method Not Allowed, transparently
retries with PUT — so the tool survives Allure deployments/versions that expose only one verb. Mockable
without a live instance.
