# allure-testops-mcp

<!-- mcp-name: io.github.mshegolev/allure-testops-mcp -->

[![PyPI](https://img.shields.io/pypi/v/allure-testops-mcp.svg?logo=pypi&logoColor=white)](https://pypi.org/project/allure-testops-mcp/)
[![Python](https://img.shields.io/pypi/pyversions/allure-testops-mcp.svg?logo=python&logoColor=white)](https://pypi.org/project/allure-testops-mcp/)
[![License: MIT](https://img.shields.io/pypi/l/allure-testops-mcp.svg)](LICENSE)
[![Tests](https://github.com/mshegolev/allure-testops-mcp/actions/workflows/test.yml/badge.svg)](https://github.com/mshegolev/allure-testops-mcp/actions/workflows/test.yml)

An [MCP](https://modelcontextprotocol.io) server for [Allure TestOps](https://qameta.io/). It lets an
LLM agent (Claude Code, Cursor, OpenCode, …) explore and manage projects, launches, test cases, test
results and reference data through the Allure REST API.

- **Stack:** Python 3.10+, [FastMCP](https://github.com/modelcontextprotocol/python-sdk), **stdio** transport.
- **Compatibility:** any Allure TestOps instance — SaaS `qameta.io` or self-hosted / on-prem (API at `/api/rs`).
- **Corporate-friendly:** API-token auth, optional SSL-verify toggle, deliberate proxy bypass.
- **Safe by default:** 11 read-only tools; the 3 write tools are off unless you opt in.

## Quick start

```bash
claude mcp add allure -s user \
  --env ALLURE_URL=https://allure.example.com \
  --env ALLURE_TOKEN=your-api-token \
  -- uvx --from allure-testops-mcp allure-testops-mcp
```

Then ask your agent: *"List all Allure projects"* or *"Show failed tests in the last launch for project 175"*.
Get an API token in Allure TestOps under **Profile → API tokens**. See [Configuration](#configuration) for
other clients and [Environment variables](#environment-variables) for all options.

## Tools at a glance

14 tools — 11 read-only (always on) and 3 write tools (opt-in via `ALLURE_ENABLE_WRITE=true`). Every tool
carries MCP annotations and returns both a typed `structuredContent` payload and a markdown summary.

| Tool | Kind | Purpose |
|------|------|---------|
| `allure_list_projects` | read | All projects (id, name, abbreviation) |
| `allure_get_project_statistics` | read | TC count, automation rate, last-launch summary |
| `allure_list_launches` | read | Recent launches with pass/fail stats |
| `allure_get_test_results` | read | Test results in a launch (filter by status) |
| `allure_search_failed_tests` | read | FAILED/BROKEN tests in the last or a given launch |
| `allure_list_test_cases` | read | Test cases (automated/manual + owner filters) |
| `allure_get_test_case` | read | One test case's full detail + scenario steps |
| `allure_get_test_case_custom_fields` | read | A test case's custom-field values |
| `allure_list_statuses` | read | A project's statuses (id, name, color) |
| `allure_list_layers` | read | A project's test layers (id, name) |
| `allure_list_custom_fields` | read | A project's custom-field schema |
| `allure_create_test_case` | write&nbsp;⚑ | Create a test case |
| `allure_update_test_case` | write&nbsp;⚑ | Partial update of a test case |
| `allure_delete_test_case` | write&nbsp;⚑ | Permanent delete (destructive — needs `confirm=true`) |

⚑ Registered only when `ALLURE_ENABLE_WRITE=true`. Without the flag they are never imported, so the agent
never sees them — see [Security considerations](#security-considerations).

### Write tools — status & layer by name or id

`allure_create_test_case` / `allure_update_test_case` accept status and layer as either a **name**
(`status` / `layer`) or a numeric **id** (`status_id` / `layer_id`). Names are auto-resolved to ids against
the project's status/layer lists (`GET /api/rs/status`, `GET /api/rs/testlayer`) — an unknown name returns an
actionable error listing the valid options. Update is partial (only the fields you pass change), and
`allure_delete_test_case` is irreversible: it carries `destructiveHint: True` (compliant clients prompt) and
additionally requires an explicit `confirm=true` argument.

## Design highlights

- **Full tool annotations** — read tools are `readOnlyHint: True` / `openWorldHint: True` so clients don't
  prompt; `allure_delete_test_case` is `destructiveHint: True`.
- **Structured output on every tool** — each tool declares a `TypedDict` return type, so FastMCP
  auto-generates an `outputSchema` and every result carries both `structuredContent` and a markdown block.
- **Actionable errors** — auth / 400 / 403 / 404 / 409 / 429 / 5xx / missing-env errors are converted to
  specific, next-step messages (e.g. *"Authentication failed — verify ALLURE_TOKEN has API scope"*).
- **Pydantic input validation** — every argument has typed constraints (ranges, lengths, literals), exposed
  as JSON Schema; usernames are alphabet-restricted to prevent RQL injection.
- **Pagination** — list tools return a `pagination` block with `page`, `total`, `has_more`, `next_page`.
- **Progress reporting** — multi-call tools emit `ctx.report_progress` + `ctx.info` events.
- **Version-agnostic update verb** — `allure_update_test_case` issues `PATCH` and falls back to `PUT` on
  HTTP 405, so it works across Allure deployments that expose only one verb.
- **Single source of truth for version** — `__version__` derives from installed package metadata, and a test
  asserts `pyproject.toml` matches both `server.json` version fields, so the published version can't drift.

## Installation

Requires Python 3.10+. No manual install needed if you use `uvx` (recommended) — your MCP client runs it.

```bash
# run on demand via uvx (recommended)
uvx --from allure-testops-mcp allure-testops-mcp

# or install with pipx
pipx install allure-testops-mcp
```

## Configuration

**Claude Code** — one command:

```bash
claude mcp add allure -s user \
  --env ALLURE_URL=https://allure.example.com \
  --env ALLURE_TOKEN=your-api-token \
  --env ALLURE_SSL_VERIFY=true \
  -- uvx --from allure-testops-mcp allure-testops-mcp
```

**Any MCP client** — add to `~/.claude.json`, a project `.mcp.json`, Cursor's `mcp.json`, etc.:

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

See [`.env.example`](./.env.example) for a template. Verify the connection:

```bash
claude mcp list
# allure: uvx --from allure-testops-mcp allure-testops-mcp - ✓ Connected
```

## Environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `ALLURE_URL` | yes | — | Allure TestOps URL (e.g. `https://allure.example.com`) |
| `ALLURE_TOKEN` | yes | — | API token (Allure → Profile → API tokens) |
| `ALLURE_SSL_VERIFY` | no | `true` | `true`/`false`. Set `false` for self-signed corp certs |
| `ALLURE_ENABLE_WRITE` | no | `false` | `true` registers the 3 write tools; default is a read-only server |

`ALLURE_TEST_PROJECT_ID` (plus optional `ALLURE_TEST_STATUS` / `ALLURE_TEST_LAYER`) are used only by the
opt-in live integration tests — see [Development](#development).

## Updating

The server is a stdio process your client respawns each session, so the running version is decided by the
`uvx` invocation. `uvx` caches the resolved environment under `~/.cache/uv`, so an older version sticks until
you refresh:

```bash
uvx --refresh --from allure-testops-mcp allure-testops-mcp   # force latest on next run
uv cache clean allure-testops-mcp                            # or drop the cached env
```

Then reconnect the server (`/mcp` → reconnect, or restart the session). To control the version from config,
edit `args` — pin for stability, or always-latest for currency:

```jsonc
// Pin a version (deterministic; bump consciously)
"args": ["--from", "allure-testops-mcp==0.8.0", "allure-testops-mcp"]

// Always latest on every start (adds a PyPI lookup per launch)
"args": ["--refresh", "--from", "allure-testops-mcp", "allure-testops-mcp"]
```

## Example prompts

Read-only:

- "List all Allure projects"
- "Show the last 10 launches for project 63"
- "Failed tests in the last launch for project 175"
- "What's the automation rate for project 842?"
- "Show me the steps of test case 641012"
- "Which custom fields does project 1664 have?"

With `ALLURE_ENABLE_WRITE=true`, drive test-case CRUD in natural language:

- "Create a Draft manual TC named 'Login flow' in project 63"
- "Add an automated smoke TC in project 63 tagged `smoke`, layer `E2E`"
- "Rename test case 555 to 'Login (rewritten)' and set its status to Active"
- "Delete test case 555" — the agent passes `confirm=true`, and a compliant client prompts you first

## Security considerations

- **API token is read from `ALLURE_TOKEN` only** — never passed on the command line, never written to logs.
- **Secrets are never echoed back** in tool responses (no header dumps, no auth reflection).
- **Self-signed SSL is opt-in** via `ALLURE_SSL_VERIFY=false` (default `true`). Disabling verification on a
  public network is a risk; use only for trusted corporate instances.
- **Proxy discovery is disabled** (`session.trust_env = False`) — the server ignores `HTTP_PROXY` /
  `HTTPS_PROXY` so it can't be silently routed through an unintended proxy.
- **Writes are opt-in and least-privilege** — without `ALLURE_ENABLE_WRITE=true` the server registers only the
  11 read-only tools and cannot create, modify, or delete anything, even with a write-scoped token. When
  enabled, `allure_delete_test_case` carries `destructiveHint: True` and requires `confirm=true`.
- **Input validation via Pydantic** — every argument is typed and bounded; usernames are alphabet-restricted
  to prevent RQL injection through the search endpoint.
- **A token is never more privileged than its account** — Allure `Api-Token` auth inherits the issuing user's
  role, so a read-only (guest) account yields a read-only server regardless of the `ALLURE_ENABLE_WRITE` flag.

## Rate limits

Allure TestOps enforces per-instance rate limits (typically ~60 requests/minute per token). On HTTP 429 the
server returns an actionable error suggesting you wait 30–60s, reduce `size`, or paginate with smaller pages.
Two tools make multiple API calls internally — `allure_get_project_statistics` (3) and
`allure_search_failed_tests` (2–3) — and report per-step progress via MCP `Context`.

## Development

```bash
git clone https://github.com/mshegolev/allure-testops-mcp.git
cd allure-testops-mcp
pip install -e '.[dev]'
pytest          # unit suite (all HTTP mocked)
ruff check src tests && ruff format --check src tests
```

Run the server directly (stdio transport — waits on stdin for MCP messages):

```bash
ALLURE_URL=... ALLURE_TOKEN=... allure-testops-mcp
```

### Live-instance integration tests

An opt-in suite runs a real create → update → delete lifecycle against a live Allure project. It is
deselected by default and skips itself unless credentials are present, so a normal `pytest` stays green:

```bash
export ALLURE_URL=https://allure.example.com
export ALLURE_TOKEN=...                 # token from an account with write access
export ALLURE_ENABLE_WRITE=true
export ALLURE_TEST_PROJECT_ID=63        # a throwaway project you can write to
pytest -m integration tests/integration -v
```

## Contributing

Issues and PRs welcome. Keep the unit suite green (`pytest`) and the linter clean (`ruff check`,
`ruff format`); CI runs both on Python 3.10 / 3.11 / 3.12. See [`CHANGELOG.md`](./CHANGELOG.md) for the
release history.

## License

MIT © Mikhail Shchegolev
