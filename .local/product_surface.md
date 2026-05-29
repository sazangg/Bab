# Bab Product Surface

Last updated: 2026-05-29

Bab is currently a business-oriented AI gateway for organization admins. The product surface is optimized around one super-admin view first, with scoped roles now partially enforced for team users.

## Shell and Operations

- Dashboard shell exposes organization and workspace navigation with route protection.
- Home summarizes provider readiness, teams, projects, and gateway state.
- API Docs provide practical curl/Postman examples using the configured public base URL.
- Playground lets key managers test virtual keys against `/v1/models` and `/v1/chat/completions`, including streaming.
- Health/readiness endpoints validate app, database, migration, and operational status.

Deferred:
- Generated API reference.
- First-run onboarding checklist.
- Deeper gateway playground history and saved examples.

## Auth and Users

- Local auth adapter supports login, session refresh, logout, user creation, role assignment, team memberships, and soft deletion.
- Roles currently include `org_owner`, `org_admin`, `org_viewer`, and `org_member`.
- Team memberships grant `team_admin` or `team_member` scoped access.
- Sidebar and routes hide or forbid unavailable surfaces.

Deferred:
- External OIDC/auth sidecar integration.
- Password reset and email verification beyond the minimal local adapter.
- More refined scoped dashboards for non-admin users.

## Providers, Credentials, Pools, Models

- Provider catalog is backend-owned and currently focused on OpenAI-compatible adapters.
- Providers can be default or custom.
- Secrets live only as provider credentials.
- Credential pools group credentials for routing; pool membership owns contextual priority and weight.
- Model offerings belong to a provider and can be synced or managed manually.
- Provider readiness checks the chain: provider active, credential, pool, pool credential, model.

Deferred:
- Native OpenAI and Anthropic adapters beyond OpenAI-compatible behavior.
- Provider-aware model metadata/pricing catalogs.
- Cross-provider failover policies and latency/cost routing.

## Teams, Projects, Allocations, Virtual Keys

- Teams own projects.
- Allocations can target teams or projects and include pools, model offerings, budget/request/token limits, active/default flags, and windows.
- Allocation enforcement is hierarchical: higher-level team limits cap project/key behavior at runtime.
- Virtual keys belong to projects, inherit defaults, can narrow allowed models, and can use custom project allocations.
- Keys are hashed at rest; secret value is shown only when created.

Deferred:
- Allocation hierarchy editor with effective policy preview.
- Cost simulator before creating keys or allocations.
- Reservation/commit ledger for concurrent budget enforcement.

## Proxy API

- Implemented OpenAI-compatible surfaces: `/v1/models`, `/v1/chat/completions`, `/v1/responses`, `/v1/completions`.
- Chat streaming is supported.
- `/v1/embeddings` exists and returns `501 Not Implemented`.
- Proxy requests enforce virtual-key auth, allocation limits, guardrails, provider body limits, provider routing, retries, fallback, circuit breaker, and usage recording.
- Usage now records the selected provider credential where available.

Deferred:
- Full embeddings support with adapter coverage.
- OpenAI compatibility test suite.
- More complete streaming fallback parity.

## Usage, Activity, Audit

- Usage supports summaries, records, timeseries, spend insights, breakdowns, CSV export, and scoped team/project/key/provider views.
- Spend insights inherit active usage filters.
- Usage records show provider credential attribution when recorded.
- Activity lists admin/runtime events with category, severity, entity filters, local search, and URL deep links.
- Audit list exists for admin actions.

Deferred:
- Signed append-only audit chain.
- Exportable audit and usage reports.
- Cost anomaly detection and budget forecasting.

## Guardrails

- Guardrails support policies, rules, assignments, simulation, delete flows, and event lists.
- Rules currently cover model/provider/pool allow-deny, prompt contains, prompt regex, and local PII detection.
- PII detection is adapter/registry-based but only local detectors are wired.
- Assignments can run in `enforce` or `dry_run` mode.
- Dry-run matches are logged and do not block.
- Project and key detail pages surface recent guardrail events.
- Blocked requests record usage rows with `guardrail_denied`.

Deferred:
- Output/response guardrails.
- External PII detector adapters.
- Policy versioning and approval workflows.
- Strong linking between guardrail events and usage rows beyond shared request scope metadata.

## Settings

- Organization settings persist name, logo, public base URL, runtime defaults, and key defaults.
- Header organization name/logo are wired to settings.
- Provider override fields exist for runtime settings with inherited defaults.

Deferred:
- Clearer inherited/override controls per provider setting.
- More explicit production boundaries around key copying once alternative retrieval flows exist.

## Suggested Next Steps

1. Provider override polish: make inherited versus overridden values explicit in the UI.
2. Usage spend dashboards: top spend drivers, burn rate, forecast, and team/project comparisons.
3. Provider metadata/pricing depth: provider-specific pricing catalogs and manual overrides.
4. Output guardrails: non-streaming response checks first, then streaming strategy.
5. Signed audit chain: hash-linked audit events with verification and export.
