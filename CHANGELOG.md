# Changelog

All notable changes to `allure-testops-mcp` are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions use [SemVer](https://semver.org/).

## [Unreleased]

## [0.3.0] — 2026-06-05

### Added
- Three opt-in write tools for test cases — `allure_create_test_case`, `allure_update_test_case`, `allure_delete_test_case`. Gated behind a new `ALLURE_ENABLE_WRITE` environment variable so the default server stays read-only; when unset or `false`, the tools are not registered and the agent doesn't see them at all.
- `allure_delete_test_case` carries `destructiveHint: True` (compliant MCP clients ask for per-call confirmation) and additionally requires an explicit `confirm=true` argument as a belt-and-braces guard for clients that ignore the annotation.
- `AllureClient.post` / `patch` / `delete` HTTP methods (same session, timeout and error semantics as the existing `get`; `delete` returns `None` on HTTP 204).
- HTTP 400 and 409 error mappings — surface Allure's payload-rejection / conflict messages with actionable hints (check status/layer names exist; re-fetch on stale state).
- `TestCaseCreated`, `TestCaseUpdated`, `TestCaseDeleted` TypedDicts for the new tools' structured output.

## [0.2.1] — 2026-04-30

Internal cleanup pass; no behavioural or public-API changes.

### Changed
- DRY'd the `owner` username alphabet — `_USERNAME_PATTERN` is now a single source of truth, threaded through both the Pydantic `Field(pattern=...)` on `allure_list_test_cases` and the existing `_build_owner_rql` regex check. Invalid usernames now fail at the MCP-call boundary with a Pydantic validation error instead of bubbling up as `ValueError` from the helper. The helper still re-validates for defence in depth and to keep its unit tests independent of FastMCP wiring.
- Replaced `is automated` with `== automated` in the post-page automation filter (PEP-8: reserve `is` for sentinels, not value comparison).
- Rewrote the test-cases markdown rendering as a small parts-list / for-loop instead of nested f-string + conditional concatenation — same output, easier to extend.

### Removed
- `test_build_owner_rql_basic` (functionally subsumed by `test_build_owner_rql_accepts_allure_usernames`, which now asserts the exact RQL shape on each parametrised username).
- Dropped a leftover `""` fallback in the `tags` list comprehension (the `if t.get("name")` guard already filters out anonymous entries, so the default was unreachable).

## [0.2.0] — 2026-04-30

### Added
- `allure_list_test_cases` now exposes the audit-trail usernames and tags of every test case. `TestCaseSummary` gained three fields: `created_by` (str), `last_modified_by` (str) and `tags` (list[str]).
- New optional `owner: str | None = None` parameter on `allure_list_test_cases`. When set, the result is narrowed to TCs the user authored or last modified — server-side, via Allure's RQL `__search` endpoint with `createdBy = "<owner>" or lastModifiedBy = "<owner>"`. Pagination stays consistent (no client-side post-filter on the owner axis). Username is validated against `^[A-Za-z0-9._@-]+$` to prevent RQL injection through the URL — invalid input raises `ValueError`.
- New `_build_owner_rql` helper in `tools.py`, unit-tested for the happy path (jdoe, j.doe, jdoe-bot, j_doe, jdoe@corp) and against 7 injection-style inputs (embedded quotes, RQL keywords, backslash, empty, trailing space).

### Changed
- `allure_list_test_cases` now selects the upstream endpoint based on the filters in play:
  - Without `owner`: keeps using `GET /testcase` for compatibility — compact projection (audit fields and tags are absent and surface as `""` / `[]`), native server-side `automated` filter.
  - With `owner`: uses `GET /testcase/__search?rql=...` — full projection (audit fields and tags are populated). Allure's `__search` does not accept `automated` as a query parameter, so when both `owner` and `automated` are set the `automated` filter is applied client-side after the page is fetched; this is documented in the tool docstring.
- The `owner` semantics intentionally mean "creator OR last modifier", not "assignee". Allure TestOps does not expose a separate `owner` field in RQL on most deployments — the `createdBy`/`lastModifiedBy` union is the closest stable proxy for "TCs I touched".

### Fixed
- `_test_case_summary` no longer emits `None` for missing audit fields (Pydantic rejects `None` for `str` fields) and tolerates malformed `tags` entries (anonymous tags, non-dict items) by skipping them rather than raising.

## [0.1.3] — 2026-04-30

### Fixed
- `allure_list_test_cases` no longer fails Pydantic validation on every project. Allure TestOps returns the test-case `status` field as a `{id, name}` object (or `null`), but the mapping passed the raw dict straight into `TestCaseSummary.status: str`, raising `5 validation errors for TestCasesListOutput / test_cases.0.status / Input should be a valid string`. Mapping now unwraps `status` the same way `layer` was already handled — `(tc.get("status") or {}).get("name", "")` — handling both the object and the `null` case.

### Added
- New `_test_case_summary` helper in `tools.py` (mirrors `_test_result_summary`): single source of truth for shaping `/testcase` items, easier to unit-test in isolation.
- Regression tests in `tests/test_tools_helpers.py` covering `status` as object / `null` / missing, `status` object without `name`, and a Pydantic `TypeAdapter` round-trip on `TestCaseSummary` to lock in the exact failure mode the bug report described (`status: {id: -1, name: "Draft", ...}`).

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
