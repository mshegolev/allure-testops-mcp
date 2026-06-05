# v0.5 Phase 1 — List statuses & layers ✅

**One-liner:** Two read tools exposing a project's status/layer reference lists.

## Accomplishments
- `allure_list_statuses(project_id)` → {id, name, color}; `allure_list_layers(project_id)` → {id, name}.
- `_fetch_all_refs` pages through all results; reuses confirmed endpoints `/status`, `/testlayer`.
- Models: StatusRef/StatusesListOutput, LayerRef/LayersListOutput. Read-only, always registered (6→8 tools).

## Verification
- 4 new unit tests (shape, paging, empty, layers). 133 tests pass, ruff clean.
- **Live-verified** against allure.services.mts.ru project 2031: 23 statuses (w/ colors), 19 layers, paging pulled full sets.

## Notes
Fully verifiable with a read-scoped token — no write access needed. Complements the v0.4.2 name→id resolver.
