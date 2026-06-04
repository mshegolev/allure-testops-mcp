# Phase 2 — Live-instance integration tests ✅

**One-liner:** Opt-in, env-gated pytest suite running real create→update→delete against Allure.

## Accomplishments
- `tests/integration/test_write_live.py` — full lifecycle test + a name-based status/layer probe (the future Phase 1 verifier).
- Marked `integration`; `addopts = -m 'not integration'` deselects by default; module-level `skipif` skips (never fails) when `ALLURE_URL` / `ALLURE_TOKEN` / `ALLURE_ENABLE_WRITE=true` / `ALLURE_TEST_PROJECT_ID` are absent.
- Added pytest config to `pyproject.toml`: `testpaths`, `pythonpath = ["src"]` (bare `pytest` now works), and the `integration` marker. This also stopped a parent `/opt/develop/pytest.ini` from leaking `addopts` into local runs.

## Decisions
- Skip, don't fail, without credentials — keeps CI green and makes the suite a safe no-op for contributors.
- This suite is the verification vehicle for the blocked Phase 1 and the Phase 4 fallback once credentials exist.

## Verification
- `pytest -m integration` → 2 skipped (no creds). Full default suite: 117 passed, 2 deselected. ruff clean.
