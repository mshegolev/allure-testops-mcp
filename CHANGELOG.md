# Changelog

All notable changes to `allure-testops-mcp` are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions use [SemVer](https://semver.org/).

## [0.1.2] — 2026-04-18

Same audit-hardening changes originally targeted at 0.1.1, re-tagged because
0.1.1 was claimed on PyPI by an earlier CI attempt before the fixes landed.

## [0.1.1] — 2026-04-18

### Added
- `ConfigError` subclass of `ValueError` for unambiguous env-var errors (no more false-positives from Pydantic validation errors hitting the `configuration problem` branch).
- URL validation in `AllureClient.__init__` — rejects missing scheme/host with an actionable error.
- `_parse_bool` helper for `ALLURE_SSL_VERIFY` (accepts `true`/`false`/`1`/`0`/`yes`/`no`).
- MCP `Context` injection for `allure_get_project_statistics`, `allure_search_failed_tests`, `allure_list_test_cases` — progress reported via `ctx.report_progress` + `ctx.info`.
- `next_page` field added to `PaginationMeta` TypedDict (previously documented in README but not in the output schema).
- Upper bounds (`le=`) on all integer IDs (`project_id`, `launch_id`) and `page` — closes unbounded-positive-int input space.
- README sections: **Security considerations** and **Rate limits**.
- Expanded tool docstrings: "Don't use when" cross-refs, full return schema, richer examples.
- `tests/` directory with unit tests for `_parse_bool`, `_validate_url`, `pagination_from`, and error mapping (no network).
- `.env.example` now lists SaaS `qameta.io` alongside self-hosted pattern.

### Changed
- `ctx` parameters declared as `Context` (required) rather than `Context | None = None` — matches FastMCP auto-injection contract.
- Client `errors.py` no longer catches generic `ValueError` — only `ConfigError` surfaces as "configuration problem".
- Client threading model documented in `client.py` module docstring (FastMCP `anyio.to_thread` wrapping).
- `session.headers` now includes `Accept: application/json`.

### Fixed
- Pagination with zero `size`/`totalPages` no longer produces `has_more=True` with stale `next_page`.
- `_launch_stats()` / `_test_result_summary()` helpers replace inline dict construction repeated across 3 tools (DRY).
- `output.fail()` annotated as `NoReturn` so type-checkers understand control flow.
- `get_client()` uses double-checked-locking for thread-safe lazy init.
- `ProjectStatistics` TypedDict tightened (no blanket `total=False`); `FailedTestsOutput` uses `Required`/`NotRequired`.
- Dropped `typing-extensions` dep (stdlib `typing.TypedDict` on Py 3.10+ is enough).
- Dockerfile now runs as non-root user `mcp`.
- Added `py.typed` marker for PEP 561 (downstream `mypy allure_testops_mcp` now checks types).
- New GitHub Actions `test.yml` — ruff lint/format + pytest across Python 3.10/3.11/3.12 on every push / PR.
- Re-added conditional `typing-extensions>=4.5; python_version < '3.11'` dep; on Py 3.10 **`TypedDict` itself is imported from `typing_extensions`** (the stdlib `typing.TypedDict` on 3.10 does not recognise PEP 655 `Required`/`NotRequired` annotations even when those names are imported from `typing_extensions` — only the backported `TypedDict` class correctly populates `__required_keys__` / `__optional_keys__`).
- `FailedTestsOutput.reason` (previously unused) now populated in the "no launches found" branch for agent explainability.
- `tests/test_errors.py` refactored to use `responses` for realistic HTTP mocking instead of hand-crafted `requests.Response`.
- Shared `_report(ctx, progress, message)` helper replaces 2 identical nested closures across `allure_get_project_statistics` and `allure_search_failed_tests`. `allure_list_test_cases` now also uses it.
- README links to `.env.example` from the Configuration section and shows a Tests CI badge.
- `launch_id` parameter in `allure_search_failed_tests` now constrained `ge=1, le=2_147_483_647` — consistent with other ID parameters, closes ambiguity where `launch_id=0` was both a valid Pydantic input AND treated as "not provided" by the `if not launch_id:` guard.
- README corrected: `allure_list_test_cases` was described as having `layer` filter (it does not — `layer` is returned per TC, not accepted as input).
- README Design highlights now lists progress reporting via MCP Context explicitly.
- README Rate limits section clarified: all 3 ctx-using tools emit progress events (previously "Both" was ambiguous).
- New `tests/test_tools_helpers.py` with unit tests for `_launch_stats` and `_test_result_summary` helpers.
- `typing-extensions` dep condition bumped to `python_version < '3.12'` (Pydantic 2.13+ requires `typing_extensions.TypedDict` on Py < 3.12). Matching guard in `models.py`.
- Dropped `Required`/`NotRequired` qualifiers — Pydantic 2.13 rejects them during runtime schema generation (`PydanticForbiddenQualifier`). Optional fields now use `str | None` convention with explicit `None` in happy-path.
- `_validate_url` now returns the whitespace-stripped URL (matches documented behaviour).

## [0.1.0] — 2026-04-18

### Added
- Initial release with 6 read-only tools covering Allure TestOps REST API:
  - `allure_list_projects` — list all projects
  - `allure_list_launches` — recent launches with pass/fail stats
  - `allure_get_test_results` — test results per launch (filter by status)
  - `allure_list_test_cases` — TC listing with automation/layer filters
  - `allure_get_project_statistics` — TC count, automation rate, last launch summary
  - `allure_search_failed_tests` — FAILED/BROKEN tests in last or specified launch
- FastMCP + Pydantic input validation + TypedDict output schemas.
- Structured error mapping for 401/403/404/429/5xx with actionable next steps.
- `ALLURE_SSL_VERIFY` toggle for self-signed corp certificates.
- MIT license.
- Published on PyPI and in the MCP Registry as `io.github.mshegolev/allure-testops-mcp`.
