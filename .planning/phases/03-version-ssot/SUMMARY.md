# Phase 3 — Version single-source-of-truth ✅

**One-liner:** Make `__version__` metadata-derived and guard cross-file version consistency in tests.

## Accomplishments
- `src/allure_testops_mcp/__init__.py` now derives `__version__` via `importlib.metadata.version("allure-testops-mcp")`, falling back to `0+unknown` on a bare source checkout. It can no longer be a stale hand-typed literal.
- `tests/test_version_consistency.py` asserts `pyproject.toml` == `server.json` top-level == `server.json` packages[0], and that `__version__` is metadata-derived (not drifted). Drift-catching behavior was proven with a simulated mismatch.
- Added `tomli>=2.0; python_version < '3.11'` to dev deps for the 3.10 runner.

## Decisions
- Version stays authored in `pyproject.toml` + `server.json` (×2); `__init__` *derives* rather than declares. The test enforces the file-pair consistency that bump steps must keep.

## Verification
- 3/3 new tests pass; consistency test re-confirmed green after the 0.3.1→0.4.0 bump.
