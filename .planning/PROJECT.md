# PROJECT — allure-testops-mcp

**What this is:** An MCP server for [Allure TestOps](https://qameta.io/). Lets an LLM agent
(Claude Code, Cursor, OpenCode, …) query and mutate Allure data — projects, launches, test cases,
test results — through the Allure REST API over stdio transport.

**Stack:** Python 3.10+, FastMCP (official Python SDK), `requests`, Pydantic, `hatchling`.
Distributed on PyPI + the official MCP Registry; launched via `uvx`.

**Tech stack & conventions:**
- Source in `src/allure_testops_mcp/`; tests in `tests/` (pytest, mocked HTTP via `responses`).
- Read tools in `tools.py`; opt-in write tools in `tools_write.py` (gated by `ALLURE_ENABLE_WRITE`).
- HTTP through `AllureClient` (`client.py`); error mapping in `errors.py`; output shaping in `output.py`.
- Version lives in `pyproject.toml`, `server.json` (×2), `src/.../__init__.py` — see v0.4 Phase 3.
- Release: bump → tag `vX.Y.Z` → `publish.yml` (PyPI) + `publish-mcp.yml` (MCP Registry), both OIDC.

**Note:** This `.planning/` was bootstrapped retroactively during a `/gsd-autonomous` run on
2026-06-05. Prior milestones (v0.1–v0.3) were delivered without GSD; their history lives in
git tags, `CHANGELOG.md`, and `.planning/reports/MILESTONE_SUMMARY-v0.3.md`.

**Current milestone:** v0.4 — Quality & robustness hardening (post-write-tools).
