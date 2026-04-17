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

- **Tool annotations** — every tool is marked `readOnlyHint: True` / `openWorldHint: True`. All 6 tools are read-only; MCP clients won't ask for confirmation.
- **Structured output on every tool** — each tool declares a `TypedDict` return type, so FastMCP auto-generates an `outputSchema` and every result carries both `structuredContent` (typed payload) and a pre-rendered markdown text block.
- **Structured errors** — auth, 404, 403, 429, 5xx, missing-env errors converted to actionable messages (e.g. _"Authentication failed — verify ALLURE_TOKEN has API scope"_).
- **Pydantic input validation** — every argument has typed constraints (ranges, lengths, literals) auto-exposed as JSON Schema.
- **Pagination** — list tools return a `pagination` block with `page`, `total`, `has_more`, `next_page`.
- **Progress reporting via MCP Context** — tools that make multiple API calls (`allure_get_project_statistics`, `allure_search_failed_tests`) and `allure_list_test_cases` emit `ctx.report_progress` + `ctx.info` events so compatible clients can render progress bars and step labels.

## Features

6 tools covering everyday Allure TestOps workflows:

**Discovery**
- `allure_list_projects` — all projects with ID, name, abbreviation
- `allure_get_project_statistics` — TC count, automation rate, last launch summary

**Launches & results**
- `allure_list_launches` — recent launches with pass/fail stats
- `allure_get_test_results` — test results in a launch (filter by status)
- `allure_search_failed_tests` — FAILED/BROKEN tests in last or specified launch

**Test cases**
- `allure_list_test_cases` — test cases with automated/manual filter (each result also carries its layer, e.g. `UNIT` / `API` / `E2E`)

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

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `ALLURE_URL` | yes | Allure TestOps URL (e.g. `https://allure.example.com`) |
| `ALLURE_TOKEN` | yes | API token from Allure TestOps (Profile → API tokens) |
| `ALLURE_SSL_VERIFY` | no | `true`/`false`. Set to `false` for self-signed corp certs. Default: `true`. |

## Example usage

In Claude Code:

- "List all Allure projects"
- "Show last 10 launches for project 63"
- "Failed tests in the last launch for project 175"
- "Automation rate for project 842"
- "Test results in launch 12345 with status FAILED"

## Security considerations

- **API token is read from `ALLURE_TOKEN` env var** — never passed on the command line and never written to logs.
- **Secrets are not echoed back** in tool responses (no `stat.request_headers` dumps, no `session.auth` reflection).
- **Self-signed SSL** is opt-in via `ALLURE_SSL_VERIFY=false` — the default is `true`. Disabling verification on a public network is a security risk; only use for trusted corporate instances.
- **Proxy discovery is disabled** (`session.trust_env = False`) — the MCP deliberately ignores `HTTP_PROXY`/`HTTPS_PROXY` env vars so the session cannot be silently routed through an unintended proxy. If your Allure instance is reachable only via proxy, run the MCP in an environment where `requests` can resolve directly.
- **No write operations exposed** — all 6 tools are read-only. Even if the API token has write scope, this MCP server cannot create, modify, or delete anything in Allure TestOps.
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

Run the server directly (stdio transport, waits on stdin for MCP messages):

```bash
ALLURE_URL=... ALLURE_TOKEN=... allure-testops-mcp
```

## License

MIT © Mikhail Shchegolev
