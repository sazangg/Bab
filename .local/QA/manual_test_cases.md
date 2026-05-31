# Bab QA Manual Test Cases

Use these cases to validate the current product surface as a user. Run them against a fresh migrated database when possible, then repeat selected cases with existing data after upgrades.

## 1. Startup And Health

Preconditions: backend and frontend are running.

Steps:
1. Open the dashboard and log in as the default super admin.
2. Open `/health` and `/readyz` from the browser or Postman.
3. Check the shell footer status.

Expected:
- Login succeeds.
- Health returns OK.
- Readiness reports database and migration status.
- The shell status reflects real health, not static placeholder text.

## 2. Users And Role Scope

Preconditions: logged in as super admin.

Steps:
1. Create users with roles `org_admin`, `org_viewer`, and `org_member`.
2. Create a team and add the `org_member` as `team_admin`.
3. Log in as each user.
4. Try direct URLs for Providers, Users, Teams, Projects, Allocations, Virtual Keys, Usage, Audit, Settings, and Playground.

Expected:
- Org admin can administer organization surfaces.
- Org viewer can view org-wide read-only surfaces and cannot mutate.
- Org member without team membership has no broad workspace access.
- Team admin sees and manages only assigned team/project/key/allocation surfaces.
- Forbidden direct URLs show the dashboard 403 page.

## 3. Provider Readiness

Preconditions: logged in as super admin, `OPENAI_API_KEY` available if testing live traffic.

Steps:
1. Open Providers.
2. Confirm providers are sorted alphabetically, favorites appear first, and default/custom labels are clear.
3. Open OpenAI.
4. Add a credential.
5. Create a credential pool.
6. Add the credential to the pool.
7. Sync models and activate at least one model offering.
8. Check provider readiness/status details.

Expected:
- Credential is created without a 500.
- Credential can belong to a pool.
- Pool membership can be edited or removed.
- Provider readiness shows the credential, pool, model, and allocation readiness chain clearly.
- Operational status shows circuit breaker or upstream failures when present.

## 4. Provider Pricing Metadata

Preconditions: at least one provider model offering exists.

Steps:
1. Open a provider model offering.
2. Review catalog price, manual override price, effective price, and freshness/version fields.
3. Set manual input/output price overrides.
4. Send a request through a key using that model.
5. Open Usage and inspect spend.

Expected:
- Effective price uses manual override when provided.
- Usage spend reflects provider-specific effective pricing.
- Pricing fields remain provider-scoped even when model names overlap across providers.

## 5. Teams, Projects, Allocations

Preconditions: provider has active credential, pool, and model offering.

Steps:
1. Create a team.
2. Create a team allocation with multiple model offerings.
3. Create a project inside the team.
4. Create a project allocation with a subset or different caps.
5. Edit both allocations from their detail surfaces and the global Allocations page.
6. Deactivate and reactivate an allocation if available.

Expected:
- Multiple models can be selected without clearing unrelated fields.
- Budget is entered/displayed in dollars.
- Max requests and window fields are grouped together.
- Project allocations can exceed team caps in configuration, but runtime enforcement still respects the full hierarchy.
- Labels describe current inherited/default behavior clearly.

## 6. Virtual Keys And Key-Level Limits

Preconditions: project has an effective allocation.

Steps:
1. Create a virtual key with no custom allocation.
2. Create another key with a project custom allocation.
3. Set key-level limits: requests/min, tokens/min, and tokens/request.
4. Use Postman or Playground to send requests until limits are reached.
5. Edit the key name and limits from key detail and the global Virtual Keys page.
6. Revoke a key.

Expected:
- Keys inherit the current project/team default unless a project allocation override is selected.
- Team allocations are not offered as custom key overrides.
- Requests beyond direct key limits return a clear 403 message.
- Revoked keys stop authenticating.
- Usage still records allowed and denied attempts where expected.

## 7. Gateway API And Playground

Preconditions: virtual key exists.

Steps:
1. Open API Docs and confirm the base URL matches organization settings.
2. Open Playground.
3. Select or paste a virtual key.
4. Use `/v1/models` to populate/select a model.
5. Test Chat, Responses, Completions, and Embeddings tabs.
6. Enable streaming for chat where output guardrails are not enforced.
7. Send equivalent requests from Postman.

Expected:
- Chat, Responses, and Completions return compatible responses for supported routes.
- Embeddings returns the explicit 501 response until implemented.
- Streaming renders incrementally when allowed.
- Playground shows response/error and the latest usage record.

## 8. Usage Analytics And Exports

Preconditions: at least one successful and one failed proxy request exist.

Steps:
1. Open org Usage.
2. Filter by date, team, project, provider, model, and virtual key.
3. Check spend insights, charts, raw records, and CSV export.
4. Open team, project, provider, allocation, and key detail pages.
5. Review scoped usage sections and drilldowns.

Expected:
- Filters affect totals, spend insights, charts, raw rows, and export.
- Provider credential, provider, pool, model, allocation, project, team, and key attribution are visible where relevant.
- Scoped detail pages show usage even when usage is inherited through a higher allocation.

## 9. Audit Chain And Export

Preconditions: perform several admin mutations such as creating a provider credential, user, team, and allocation.

Steps:
1. Open Audit.
2. Search/filter for recent mutations.
3. Click Verify chain.
4. Export audit CSV.

Expected:
- Audit rows include actor, action, entity, metadata, and timestamps.
- Verification succeeds for an untampered chain.
- CSV includes previous hash, event hash, and signature algorithm.
- The export contains all filtered events, not only the loaded UI rows.

## 10. Activity Feed

Preconditions: admin and proxy activity exists.

Steps:
1. Open Activity.
2. Filter by category, severity, entity type, entity ID, and text.
3. Follow deep links from related pages when available.

Expected:
- Settings, guardrail, provider, workspace, allocation, and proxy events are discoverable.
- Entity filters narrow the backend result set.

## 11. Guardrails Request And Output

Preconditions: at least one virtual key exists.

Steps:
1. Create a guardrail policy with request-phase prompt contains or regex rule.
2. Assign it to a project or virtual key in enforce mode.
3. Send a matching request.
4. Create a response-phase rule that matches model output.
5. Send a non-streaming request that triggers the response rule.
6. Try streaming with enforced response guardrails active.
7. Repeat with dry-run/log-only mode.

Expected:
- Request guardrails deny matching prompts before provider execution.
- Output guardrails deny matching non-streaming responses after provider execution.
- Streaming is rejected clearly when enforced output guardrails apply.
- Dry-run records events without blocking.
- Recent denials appear on project/key detail pages and link back to usage when available.

## 12. Settings And Organization Branding

Preconditions: logged in as super admin.

Steps:
1. Change organization name and upload an optional logo.
2. Confirm the header updates.
3. Change gateway public base URL and key defaults.
4. Review provider override controls.

Expected:
- Organization name and logo are reflected in the shell.
- Public base URL affects docs/playground display.
- Provider runtime settings clearly show inherited versus overridden values.

