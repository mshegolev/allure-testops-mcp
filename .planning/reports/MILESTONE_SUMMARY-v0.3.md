# Milestone v0.3 — Project Summary

**Generated:** 2026-06-05
**Purpose:** Team onboarding and project review
**Scope:** The `v0.3` line — opt-in test-case write tools (CRUD) + publishing automation (PyPI & MCP Registry).

> **Source note:** This project is **not** managed under GSD — there is no `.planning/ROADMAP.md`,
> `REQUIREMENTS.md`, or phase artifacts. This summary is reconstructed from the real artifacts that
> exist: the approved design spec (`docs/superpowers/specs/2026-06-04-allure-write-test-cases-design.md`),
> `CHANGELOG.md`, `README.md`, and git history/tags. Treat the "Phases" section as a release timeline
> rather than GSD phases.

---

## 1. Project Overview

**What this is:** `allure-testops-mcp` is an [MCP](https://modelcontextprotocol.io) server for
[Allure TestOps](https://qameta.io/). It lets an LLM agent (Claude Code, Cursor, OpenCode, …) query
and now mutate Allure data — projects, launches, test cases, test results — through the Allure REST
API, over stdio transport.

**Stack:** Python 3.10+, [FastMCP](https://github.com/modelcontextprotocol/python-sdk) (the official
Python SDK), `requests` HTTP, Pydantic for input validation, `hatchling` build backend. Distributed on
PyPI and the official MCP Registry; intended to be launched via `uvx`.

**Core value:** test-management workflows can stay inside one LLM conversation. Before v0.3 the server
was read-only (6 tools); v0.3 closes the gap by letting the agent **author and maintain test cases**
without switching to the Allure UI — while keeping the read-only default intact for users who don't
opt in.

**Target users:** QA engineers and SDETs driving Allure TestOps through an agent, on both SaaS
(`qameta.io`) and self-hosted / corporate instances (hence the proxy-bypass and SSL-verify toggles).

**Milestone status:** ✅ Complete. Shipped end-to-end: code (`0.3.0`), docs (`0.3.1`), and full
publishing automation to PyPI + MCP Registry. `0.3.1` is live on both (`isLatest: true` in the registry).

---

## 2. Architecture & Technical Decisions

- **Decision: Write tools are opt-in via `ALLURE_ENABLE_WRITE`, enforced by conditional import.**
  - **Why:** Adding write breaks the "no write operations exposed" promise. Isolating it behind an
    env var preserves the safe default. Critically, the gate is *registration*, not a per-call check —
    a tool that registers but always errors "wastes agent planning tokens and misleads the model."
    When the flag is off, `tools_write.py` is never imported, so the agent never sees the tools.
  - **Where:** `_mcp.py` parses the flag once at startup via the existing `_parse_bool` helper, before
    importing the write module. `tools.py` (read tools) is untouched.

- **Decision: New `tools_write.py` module, symmetric `client.post/patch/delete`.**
  - **Why:** Keeps the opt-in boundary at the module level (one conditional import) and mirrors the
    existing `client.get` — same 30s timeout, same authenticated session, same `raise_for_status()`.
    `delete` returns `None` on HTTP 204. No retry/idempotency layer (explicit YAGNI).

- **Decision: `allure_delete_test_case` carries `destructiveHint: True` AND requires `confirm=true`.**
  - **Why:** Belt-and-braces. Compliant MCP clients prompt the user on `destructiveHint`; the explicit
    `confirm: Literal[True]` Pydantic parameter is a second guard for clients that ignore the annotation.

- **Decision: Partial update strips `None` fields before serializing.**
  - **Why:** So an update only touches the fields the caller passed. An empty payload (nothing but
    `test_case_id`) is rejected by a model-level validator *before* the HTTP call.

- **Decision: Name-based `status`/`layer`/`tags` mapped via one shared `_build_testcase_body` helper.**
  - **Why:** Allure expects nested objects (`{"status": {"name": …}}`), and the mapping is identical for
    create and update. If a deployment requires IDs instead of names, the design surfaces the Allure 400
    rather than preemptively adding a name→id lookup (deferred — see §6).

- **Decision: Two independent publish workflows on one tag, gated by a PyPI-readiness poll.**
  - **Why:** A `v*` tag triggers `publish.yml` (PyPI, Trusted-Publisher OIDC) **and** `publish-mcp.yml`
    (MCP Registry, GitHub OIDC) in parallel. The registry rejects a server whose PyPI package isn't live
    yet, so `publish-mcp.yml` polls the PyPI simple index until the version appears before calling
    `mcp-publisher`. Version is read from `server.json` (not the tag) so manual `workflow_dispatch` works
    identically for backfills.

---

## 3. Phases Delivered (release timeline)

| Phase | Name | Status | One-liner |
|-------|------|--------|-----------|
| Spec | Design write operations | ✅ | Approved design for 3 opt-in write tools (PR #3) |
| `0.3.0` | Opt-in test-case write tools | ✅ | `create` / `update` / `delete` behind `ALLURE_ENABLE_WRITE`; 6→9 tools (PR #4) |
| `0.3.1` | Docs: CRUD + Updating guide | ✅ | README CRUD section + uvx update/pinning guide; shipped as PyPI long_description (PR #5) |
| CI | MCP Registry automation | ✅ | `publish-mcp.yml` — OIDC publish to registry.modelcontextprotocol.io (PR #6) |

---

## 4. Requirements Coverage

Derived from the design spec's stated scope and the CHANGELOG.

- ✅ Three write tools (`allure_create_test_case`, `allure_update_test_case`, `allure_delete_test_case`)
- ✅ Opt-in gate via `ALLURE_ENABLE_WRITE`, enforced by conditional import (6 tools default, 9 when enabled — verified in `test_mcp_registration.py`)
- ✅ `client.post/patch/delete` with 204→`None` handling
- ✅ Structured output TypedDicts (`TestCaseCreated`, `TestCaseUpdated`, `TestCaseDeleted`)
- ✅ HTTP 400 / 409 error mappings with actionable hints
- ✅ `destructiveHint: True` + `confirm=true` on delete
- ✅ Partial-update semantics with empty-update rejection
- ✅ Documentation (README, `.env.example`, CHANGELOG) + Updating guide
- ✅ Full publishing automation: PyPI + MCP Registry, both verified live for `0.3.1`
- ⚠️ Name→ID lookup for `status`/`layer` — **intentionally deferred**; relies on surfacing Allure's 400 (see §6)
- ❌ (Non-goals, by design) test-result writes, shared steps/test-plans/custom-fields, bulk ops, structured step editing, retry/idempotency layer

---

## 5. Key Decisions Log

| ID | Decision | Rationale |
|----|----------|-----------|
| D1 | Opt-in via env var, not always-on | Preserve read-only default; honor README promise |
| D2 | Gate = conditional import, not per-call error | Don't waste agent tokens / mislead the model with always-failing tools |
| D3 | Separate `tools_write.py` | Module-level opt-in boundary; leave `tools.py` untouched |
| D4 | `destructiveHint` + mandatory `confirm=true` | Two independent guards against accidental deletes |
| D5 | Strip `None` on update | True partial semantics; empty update rejected pre-HTTP |
| D6 | Name-based status/layer via shared body mapper | One mapping for create+update; surface 400 instead of pre-flight lookup |
| D7 | `server.json` as version source of truth in CI | Manual dispatch and tag-push behave identically |
| D8 | PyPI-readiness poll before registry publish | Registry validates the PyPI package exists; gates the parallel-run race |
| D9 | Bump 0.3.0→0.3.1 for docs-only change | README ships as PyPI `long_description`; needs a release to surface |

---

## 6. Tech Debt & Deferred Items

From the spec's "Open questions / deferred" and observations made this milestone:

- **Name vs ID for `status`/`layer`** — assumes name-based lookup works on the target Allure; falls back
  to surfacing the 400. A name→id helper is a follow-up if a deployment rejects names.
- **Update HTTP verb (PATCH vs PUT)** — resolved at implementation time per Allure version; only affects
  one line inside `update`. Worth re-confirming if targeting a new Allure major.
- **Deep-link URL builder** — best-effort; returns `null` when `ALLURE_URL` doesn't allow deterministic
  construction. No separate lookup added.
- **No live-instance integration tests** — write tools are unit-tested with mocked HTTP only (out of
  scope for CI). A gated, opt-in integration suite against a throwaway Allure project would raise
  confidence.
- **`__version__` drift, now fixed** — `src/.../__init__.py` had drifted to `0.1.2` while the package was
  at `0.2.1`; aligned to the real version this milestone. Consider a single source of truth (e.g. read
  version from package metadata) to prevent recurrence across the 3 version locations
  (`pyproject.toml`, `server.json` ×2, `__init__.py`).
- **MCP Registry namespace coupling** — `io.github.mshegolev/*` is authorized via GitHub OIDC tied to the
  repo owner. A repo move to another org/owner requires re-doing OIDC from the new owner or switching to
  DNS auth.

---

## 7. Getting Started

- **Run it (as a user):**
  ```bash
  uvx --from allure-testops-mcp allure-testops-mcp
  # or register in Claude Code:
  claude mcp add allure -s project \
    --env ALLURE_URL=https://allure.example.com \
    --env ALLURE_TOKEN=your-api-token \
    -- uvx --from allure-testops-mcp allure-testops-mcp
  ```
  Set `ALLURE_ENABLE_WRITE=true` to expose the three write tools.

- **Develop:**
  ```bash
  git clone https://github.com/mshegolev/allure-testops-mcp.git
  cd allure-testops-mcp
  pip install -e '.[dev]'
  pytest                       # note: a parent /opt/develop/pytest.ini may leak addopts;
                               # run `pytest tests -o addopts="" --rootdir=.` to isolate
  ```

- **Key directories / files (where to look first):**
  - `src/allure_testops_mcp/_mcp.py` — shared FastMCP instance, client cache, **the opt-in gate**
  - `src/allure_testops_mcp/server.py` — entry point (`main()`), conditional write-tools import
  - `src/allure_testops_mcp/tools.py` — the 6 read-only tools
  - `src/allure_testops_mcp/tools_write.py` — the 3 opt-in write tools + `_build_testcase_body`
  - `src/allure_testops_mcp/client.py` — `AllureClient` (auth, SSL, no-proxy, get/post/patch/delete)
  - `src/allure_testops_mcp/{models,errors,output}.py` — TypedDicts, error mapping, response formatting
  - `server.json` — MCP Registry manifest (version must match `pyproject.toml`)
  - `.github/workflows/` — `test.yml`, `publish.yml` (PyPI), `publish-mcp.yml` (registry)
  - `docs/superpowers/specs/` — the design spec that drove this milestone

- **Release process (one tag does everything):**
  1. Bump version in `pyproject.toml`, `server.json` (×2), `src/.../__init__.py`; promote CHANGELOG `[Unreleased]`.
  2. Merge to `main`, then `git tag vX.Y.Z && git push origin vX.Y.Z`.
  3. `publish.yml` → PyPI; `publish-mcp.yml` → MCP Registry (after PyPI is live). Both via OIDC, no secrets.

---

## Stats

- **Project timeline:** 2026-04-18 → 2026-06-05
- **v0.3 milestone:** 2026-06-04 → 2026-06-05 (spec → registry automation)
- **Releases in line:** `0.3.0` (write tools), `0.3.1` (docs)
- **Commits since `v0.2.1`:** 11 (incl. merges)
- **Files changed since `v0.2.1`:** 17 files, +1216 / −7
- **Tests:** 109 passing
- **Contributors (all-time):** mshegolev (17), SadLiter (3), mvschegole (3), ojkukushki (2)
- **Distribution:** PyPI `latest=0.3.1` · MCP Registry `0.3.1` active (`isLatest: true`)
