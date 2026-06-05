# ROADMAP — Milestone v0.6 (Single test-case detail)

| # | Phase | Status | One-liner |
|---|-------|--------|-----------|
| 1 | Get test-case detail | ✅ complete | `allure_get_test_case` — full detail + flattened scenario steps |

## Phase 1 — Get test-case detail
`allure_get_test_case(test_case_id, include_scenario=True)` returns the body of one test case
(description, precondition, expected result, status/layer, tags) plus the manual scenario steps
flattened depth-first. Endpoints: `GET /api/rs/testcase/{id}` + `GET /api/rs/testcase/{id}/scenario`.
Read-only; live-verifiable with a read token.
