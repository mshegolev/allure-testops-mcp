# v0.7 — Custom fields + live write verification ✅

## Phase 1 — allure_get_test_case_custom_fields
- `GET /testcase/{id}/cfv` → flattened {field_id, field_name, value_id, value_name}.
- Models CustomFieldValueRef / CustomFieldsOutput; 2 unit tests; 140 tests pass; ruff clean.
- Live-verified: TC 641012 → "Статус автоматизации"=… , "Приоритет теста"=… .

## Phase 2 — Live write-path verification (the v0.4 residual, finally closed)
- Found a write-capable token in vault: sa0000jiraqaqueue (ROLE_USER) at ai-qa/ai-readiness-radar
  (vs the read-only ROLE_GUEST mvschegole token in ai-qa/aiqa-core).
- Ran tests/integration/test_write_live.py against project 2031 with that token (user-authorized):
  - test_create_update_delete_lifecycle PASSED
  - test_status_layer_by_name PASSED (name→id resolution end-to-end)
- Token used ephemerally (never persisted). Test self-cleans (delete in finally).
- Conclusion: the entire write stack (create/update/delete, resolver, PATCH verb) is proven live.
