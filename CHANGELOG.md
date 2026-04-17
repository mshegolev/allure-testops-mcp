# Changelog

All notable changes to `allure-testops-mcp` are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions use [SemVer](https://semver.org/).

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
