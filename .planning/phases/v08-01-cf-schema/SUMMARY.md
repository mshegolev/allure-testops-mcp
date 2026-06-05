# v0.8 — Custom-field schema discovery

## Phase 1 — allure_list_custom_fields ✅
- `GET /api/rs/cf?projectId=` → [{customField.id, name, singleSelect, required}].
- Model CustomFieldDef/CustomFieldDefsOutput; 1 unit test; 141 pass; ruff clean.
- Live-verified: project 1664 → 18 fields (Приоритет теста=87, Платформа=90, Команда=94, …); project 2031 → 5 built-ins.

## Phase 2 — set custom-field value (write) ⛔ NOT SHIPPED (quality gate)
Live-probed with the write token on a throwaway TC in 2031:
- POST /testcase/{id}/cfv [{id:valueId}] -> HTTP 500.
- POST /testcase/{id}/cfv [{id,name,customField:{id:168}}] -> HTTP 400 "custom field 168 not available for this project"
  (field 168 belongs to project 1664, not 2031 — custom fields are project-scoped).
Conclusion: POST contract + replace/add semantics + per-project field resolution not yet confirmed.
Refused to ship unverified write code to a published package. Candidate for a future release after the
POST shape is confirmed (needs a project where a writable select-field exists + the SA token's membership there).
