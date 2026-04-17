# allure-testops-mcp

<!-- mcp-name: io.github.mshegolev/allure-testops-mcp -->

[![PyPI](https://img.shields.io/pypi/v/allure-testops-mcp.svg?logo=pypi&logoColor=white)](https://pypi.org/project/allure-testops-mcp/)
[![Python](https://img.shields.io/pypi/pyversions/allure-testops-mcp.svg?logo=python&logoColor=white)](https://pypi.org/project/allure-testops-mcp/)
[![License: MIT](https://img.shields.io/pypi/l/allure-testops-mcp.svg)](LICENSE)

MCP server for [Allure TestOps](https://qameta.io/). Lets an LLM agent (Claude Code, Cursor, OpenCode, etc.) query projects, launches, test cases and test results through the Allure REST API.

Python, [FastMCP](https://github.com/modelcontextprotocol/python-sdk), stdio transport.

Works with any Allure TestOps instance — SaaS `qameta.io` or self-hosted / on-prem. Designed with corporate networks in mind: configurable proxy bypass, optional SSL-verify toggle, API-token auth.

## Design highlights

- **Tool annotations** — every tool is marked `readOnlyHint: True` / `openWorldHint: True`. All 6 tools are read-only; MCP clients won't ask for confirmation.
- **Structured output on every tool** — each tool declares a `TypedDict` return type, so FastMCP auto-generates an `outputSchema` and every result carries both `structuredContent` (typed payload) and a pre-rendered markdown text block.
- **Structured errors** — auth, 404, 403, 429, 5xx, missing-env errors converted to actionable messages (e.g. _"Authentication failed — verify ALLURE_TOKEN has API scope"_).
- **Pydantic input validation** — every argument has typed constraints (ranges, lengths, literals) auto-exposed as JSON Schema.
- **Pagination** — list tools return a `pagination` block with `page`, `total`, `has_more`, `next_page`.

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
- `allure_list_test_cases` — test cases with manual/auto/layer filters

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
