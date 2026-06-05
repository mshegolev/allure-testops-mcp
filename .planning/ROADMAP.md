# ROADMAP — Milestone v0.5 (Reference-data discovery tools)

Builds on v0.4.2's name→id resolver: expose the project status/layer lists as
read tools so an agent can discover valid names/ids before setting them.

| # | Phase | Status | One-liner |
|---|-------|--------|-----------|
| 1 | List statuses & layers | ✅ complete | `allure_list_statuses` / `allure_list_layers` read tools (project-scoped) |

## Phase 1 — List statuses & layers
**Goal:** Two read-only tools returning a project's test-case statuses (id, name, color)
and layers (id, name), paging through all results. Fully live-verifiable with a read token.
Endpoints confirmed live: `GET /api/rs/status?projectId=…`, `GET /api/rs/testlayer?projectId=…`.
