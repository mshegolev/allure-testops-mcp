# allure-testops-mcp

<!-- mcp-name: io.github.mshegolev/allure-testops-mcp -->

[![PyPI](https://img.shields.io/pypi/v/allure-testops-mcp.svg?logo=pypi&logoColor=white)](https://pypi.org/project/allure-testops-mcp/)
[![Python](https://img.shields.io/pypi/pyversions/allure-testops-mcp.svg?logo=python&logoColor=white)](https://pypi.org/project/allure-testops-mcp/)
[![License: MIT](https://img.shields.io/pypi/l/allure-testops-mcp.svg)](LICENSE)
[![Tests](https://github.com/mshegolev/allure-testops-mcp/actions/workflows/test.yml/badge.svg)](https://github.com/mshegolev/allure-testops-mcp/actions/workflows/test.yml)

MCP server for [Allure TestOps](https://qameta.io/). Lets an LLM agent (Claude Code, Cursor, OpenCode, etc.) query projects, launches, test cases and test results through the Allure REST API.

Python, [FastMCP](https://github.com/modelcontextprotocol/python-sdk), stdio transport.

Works with any Allure TestOps instance — SaaS `qameta.io` or self-hosted / on-prem. Designed with corporate networks in mind: configurable proxy bypass, optional SSL-verify toggle, API-token auth.

## Design highlights

- **Tool annotations** — every read tool is marked `readOnlyHint: True` / `openWorldHint: True`. The 10 default tools are read-only; MCP clients won't ask for confirmation. Optional write tools are gated behind `ALLURE_ENABLE_WRITE` (see below) and carry the appropriate `destructiveHint` annotations.
- **Structured output on every tool** — each tool declares a `TypedDict` return type, so FastMCP auto-generates an `outputSchema` and every result carries both `structuredContent` (typed payload) and a pre-rendered markdown text block.
- **Structured errors** — auth, 404, 403, 429, 5xx, missing-env errors converted to actionable messages (e.g. _"Authentication failed — verify ALLURE_TOKEN has API scope"_).
- **Pydantic input validation** — every argument has typed constraints (ranges, lengths, literals) auto-exposed as JSON Schema.
- **Pagination** — list tools return a `pagination` block with `page`, `total`, `has_more`, `next_page`.
- **Progress reporting via MCP Context** — tools that make multiple API calls (`allure_get_project_statistics`, `allure_search_failed_tests`) and `allure_list_test_cases` emit `ctx.report_progress` + `ctx.info` events so compatible clients can render progress bars and step labels.
- **Version-agnostic update verb** — `allure_update_test_case` issues `PATCH` and transparently falls back to `PUT` on HTTP 405, so it works across Allure deployments that expose only one of the two verbs.
- **Single source of truth for version** — `__version__` is derived from installed package metadata, and a consistency test asserts `pyproject.toml` matches both `server.json` version fields, so the published version can't drift.

## Features

10 read-only tools covering everyday Allure TestOps workflows:

**Discovery**
- `allure_list_projects` — all projects with ID, name, abbreviation
- `allure_get_project_statistics` — TC count, automation rate, last launch summary
- `allure_list_statuses` — a project's test-case statuses (id, name, color); discover valid names/ids before setting a status
- `allure_list_layers` — a project's test layers (id, name); discover valid names/ids before setting a layer

**Launches & results**
- `allure_list_launches` — recent launches with pass/fail stats
- `allure_get_test_results` — test results in a launch (filter by status)
- `allure_search_failed_tests` — FAILED/BROKEN tests in last or specified launch

**Test cases**
- `allure_list_test_cases` — test cases with automated/manual filter (each result also carries its layer, e.g. `UNIT` / `API` / `E2E`)
- `allure_get_test_case` — one test case's full detail: description, precondition, expected result, status/layer, tags, and the manual scenario steps (flattened with a `depth` marker)
- `allure_get_test_case_custom_fields` — the custom-field values set on a test case (field name/id → value name/id)

**Test-case CRUD — opt-in write tools** _(new in 0.3.0)_

Off by default — the server is read-only unless you set `ALLURE_ENABLE_WRITE=true`. When enabled, three more tools register, giving an agent full create / update / delete over test cases:

- `allure_create_test_case` — create a TC in a project (`project_id`, `name`, plus optional `description`, `precondition`, `expected_result`, `automated`, `status`/`status_id`, `layer`/`layer_id`, `tags`)
- `allure_update_test_case` — partial update; only the fields you pass are changed, the rest are left untouched

Status and layer accept either a **name** (`status` / `layer`) or a numeric **id** (`status_id` / `layer_id`). Names are auto-resolved to ids against the project's status/layer list (`GET /api/rs/status`, `GET /api/rs/testlayer`) — sent as Allure's nested id object on create and as flat `statusId` / `testLayerId` on update. An unknown name returns an actionable error listing the valid names. Built-in ids are negative (e.g. `Draft = -1`, `API Tests = -3`).
- `allure_delete_test_case` — **permanent** delete; carries `destructiveHint: True` (compliant clients ask for confirmation) **and** requires an explicit `confirm=true` argument as a second guard

Without the flag these tools are never imported, so the agent doesn't even see them — see [Security considerations](#security-considerations).

## Installation

Requires Python 3.10+.

```bash
# via uvx (recommended)
uvx --from allure-testops-mcp allure-testops-mcp

# or via pipx
pipx install allure-testops-mcp
```

## Configuration

Short version — `claude mcp add`:

```bash
claude mcp add allure -s project \
  --env ALLURE_URL=https://allure.example.com \
  --env ALLURE_TOKEN=your-api-token \
  --env ALLURE_SSL_VERIFY=true \
  -- uvx --from allure-testops-mcp allure-testops-mcp
```

Or in `~/.claude.json` / project `.mcp.json`:

```json
{
  "mcpServers": {
    "allure": {
      "type": "stdio",
      "command": "uvx",
      "args": ["--from", "allure-testops-mcp", "allure-testops-mcp"],
      "env": {
        "ALLURE_URL": "https://allure.example.com",
        "ALLURE_TOKEN": "${ALLURE_TOKEN}",
        "ALLURE_SSL_VERIFY": "true"
      }
    }
  }
}
```

See [`.env.example`](./.env.example) for a template of all supported environment variables.

Check:

```bash
claude mcp list
# allure: uvx --from allure-testops-mcp allure-testops-mcp - ✓ Connected
```

## Updating

There's no in-process auto-update — the server is a stdio process that your client respawns each session, so the running version is decided entirely by the `uvx` invocation. `uvx` caches the resolved environment under `~/.cache/uv`, so a machine that already ran an older version keeps using it until you trigger a refresh.

```bash
# force the latest release on the next run
uvx --refresh --from allure-testops-mcp allure-testops-mcp

# or drop the cached env so the next run re-resolves
uv cache clean allure-testops-mcp
```

Then reconnect the server in your client (`/mcp` → reconnect, or restart the session).

To control the version from config instead, edit `args`:

```jsonc
// A. Pin a version — deterministic; bump consciously
"args": ["--from", "allure-testops-mcp==0.3.0", "allure-testops-mcp"]

// B. Always latest on every start — adds a PyPI lookup per launch
"args": ["--refresh", "--from", "allure-testops-mcp", "allure-testops-mcp"]
```

Pinning (A) is recommended for stability; `--refresh` (B) trades a little startup latency for always being current.

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `ALLURE_URL` | yes | Allure TestOps URL (e.g. `https://allure.example.com`) |
| `ALLURE_TOKEN` | yes | API token from Allure TestOps (Profile → API tokens) |
| `ALLURE_SSL_VERIFY` | no | `true`/`false`. Set to `false` for self-signed corp certs. Default: `true`. |
| `ALLURE_ENABLE_WRITE` | no | `true`/`false`. When `true`, registers the three write tools (`allure_create_test_case` / `allure_update_test_case` / `allure_delete_test_case`). Default: `false` — read-only server. |

## Example usage

In Claude Code:

- "List all Allure projects"
- "Show last 10 launches for project 63"
- "Failed tests in the last launch for project 175"
- "Automation rate for project 842"
- "Test results in launch 12345 with status FAILED"

With `ALLURE_ENABLE_WRITE=true` you can also drive test-case CRUD in natural language:

- "Create a Draft manual TC named 'Login flow' in project 63"
- "Add an automated smoke TC in project 63 tagged `smoke`, layer `E2E`"
- "Rename test case 555 to 'Login (rewritten)' and set status Active"
- "Delete test case 555" — the agent must pass `confirm=true`, and a compliant client also prompts you before it runs

## Security considerations

- **API token is read from `ALLURE_TOKEN` env var** — never passed on the command line and never written to logs.
- **Secrets are not echoed back** in tool responses (no `stat.request_headers` dumps, no `session.auth` reflection).
- **Self-signed SSL** is opt-in via `ALLURE_SSL_VERIFY=false` — the default is `true`. Disabling verification on a public network is a security risk; only use for trusted corporate instances.
- **Proxy discovery is disabled** (`session.trust_env = False`) — the MCP deliberately ignores `HTTP_PROXY`/`HTTPS_PROXY` env vars so the session cannot be silently routed through an unintended proxy. If your Allure instance is reachable only via proxy, run the MCP in an environment where `requests` can resolve directly.
- **Write operations are opt-in** — without `ALLURE_ENABLE_WRITE=true` the server registers only the 10 read-only tools and cannot create, modify, or delete anything, even if the API token has write scope. When the flag is set, the three write tools register; `allure_delete_test_case` carries `destructiveHint: True` so compliant MCP clients ask for per-call confirmation, and the tool itself requires an explicit `confirm=true` argument as a belt-and-braces guard.
- **Input validation via Pydantic** — every tool argument is typed and bounded (IDs must be ≥ 1, pagination capped at 200-500).

## Rate limits

Allure TestOps enforces per-instance rate limits (typically ~60 requests / minute for API tokens). On HTTP 429 the MCP returns an actionable error suggesting you:

- Wait 30-60 seconds before retrying.
- Reduce the `size` parameter (default 50 for test results, 200 for projects).
- Paginate with smaller page sizes.

Two tools perform multiple API calls internally:

- `allure_get_project_statistics` — 3 calls (TC counts + launches + launch statistic).
- `allure_search_failed_tests` — 2-3 calls (latest launch resolve + FAILED + BROKEN).

Both use MCP `Context` to report per-step progress; `allure_list_test_cases` also emits a single progress event. Monitor the progress stream in compatible clients.

## Development

```bash
git clone https://github.com/mshegolev/allure-testops-mcp.git
cd allure-testops-mcp
pip install -e '.[dev]'
pytest
```

### Live-instance integration tests

The unit suite mocks all HTTP. There is also an opt-in integration suite that runs a real
create → update → delete lifecycle against a live Allure project. It's deselected by default and
skips itself unless credentials are present:

```bash
export ALLURE_URL=https://allure.example.com
export ALLURE_TOKEN=...                 # token with write scope
export ALLURE_ENABLE_WRITE=true
export ALLURE_TEST_PROJECT_ID=63        # a throwaway project you can write to
pytest -m integration tests/integration -v
```

Run the server directly (stdio transport, waits on stdin for MCP messages):

```bash
ALLURE_URL=... ALLURE_TOKEN=... allure-testops-mcp
```

## License

MIT © Mikhail Shchegolev
