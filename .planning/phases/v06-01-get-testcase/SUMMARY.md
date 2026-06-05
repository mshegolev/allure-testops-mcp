# v0.6 Phase 1 — Get test-case detail ✅

**One-liner:** `allure_get_test_case` returns one TC's full content + flattened scenario steps.

## Accomplishments
- Endpoints confirmed: detail `GET /testcase/{id}`, scenario `GET /testcase/{id}/scenario` → {steps:[TestCaseStep]}.
  Step shape grounded in the eroshenkoam `TestCaseStep` DTO (name, keyword, expectedResult, nested steps, attachments).
- `_flatten_steps` walks the recursive step tree depth-first with a `depth` marker (schema-safe, no recursion in TypedDict).
- Models: `TestCaseStepFlat`, `TestCaseDetail`. Read-only tool; 8→9 read tools.

## Verification
- 5 new unit tests (flatten depth/nesting, none-handling, detail+steps assembly, include_scenario=false skips call, empty collapse). 138 tests pass, ruff clean.
- **Live-verified** against real TC 641012 (project 1664): detail fields + markdown rendered (empty-draft scenario → steps=[]).
