# SQLite Performance Baseline

Date: 2026-06-29. These workstation-specific numbers are a relative local comparison
baseline, not hardware-independent SLOs.

## Environment

- Host: Windows 11 Pro N 10.0.26200; Intel Core i9-10900X, 10 cores/20 logical processors;
  31.7 GiB RAM.
- Docker Desktop engine 29.5.2; Compose 5.1.4; Docker allocation reported 20 CPUs and
  15.5 GiB memory.
- Backend: one Uvicorn process/worker on the host.
- Python 3.13.3; SQLite 3.47.1; aiosqlite 0.22.1; SQLAlchemy 2.0.49; FastAPI 0.136.1.
- Load generator: `grafana/k6:1.0.0`.
- Provider stub: `python:3.13.5-slim`, one threaded process, fixed 20 ms delay, failures
  disabled.
- SQLite: 4 KiB pages, `journal_mode=delete`, `synchronous=2` (FULL),
  `busy_timeout=5000`, no pragma tuning.
- Database size after all runs: 60,874,752 bytes; 14,862 pages; zero freelist pages.

## Dataset

Initial deterministic seed counts:

| Entity | Rows |
| --- | ---: |
| Organizations | 1 |
| Teams | 10 |
| Projects | 30 |
| Virtual keys | 500 |
| Providers | 4 (three bootstrap catalog entries plus benchmark provider) |
| Provider credentials / pools / offerings | 1 / 1 / 1 |
| Policies / assignments | 2 / 2 |
| Usage records | 10,000 |
| Gateway requests / route attempts | 10,000 / 10,000 |

Measured gateway traffic added 508 completed usage/request/attempt/limit-accounting rows.
Three additional failed requests, including warm-up traffic, did not complete accounting.

## Scenarios

Each measured profile followed a 15-second warm-up and ran for 60 seconds. Authentication
occurred in k6 `setup()` outside steady-state iteration timing.

| Scenario | VUs | Requests | req/s | p50 ms | p95 ms | p99 ms | Failure rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Control plane | 1 | 685 | 11.33 | 46.36 | 234.54 | 247.88 | 0% |
| Control plane | 10 | 1,597 | 26.04 | 314.55 | 830.68 | 1,086.60 | 0% |
| Gateway | 1 | 190 | 3.14 | 303.01 | 624.19 | 641.89 | 0% |
| Gateway | 10 | 196 | 3.11 | 2,699.97 | 8,432.63 | 12,151.74 | 0.51% |
| Mixed 80/20 | 1 | 116 | 1.89 | 584.57 | 622.63 | 641.75 | 0% |
| Mixed 80/20 | 10 | 141 | 1.90 | 4,916.80 | 9,803.48 | 13,044.83 | 0.71% |

Smoke covered health, readiness, metrics, authenticated identity, and one provider-backed
gateway request with six of six checks passing.

Control-plane iterations call usage summary, usage daily time series, usage filter options,
gateway-history page at offset 100, virtual-key inventory at offset 100, and organization
access-planning options. Gateway iterations call model listing and non-streaming chat.

## SQLite Evidence

- Usage time-range/list: `ix_usage_records_org_created_at_id`.
- Usage grouped report: the same range index, plus a temporary B-tree for `GROUP BY`.
- Gateway-history list: `ix_gateway_requests_org_started_id`.
- Route-attempt loading: `ix_gateway_route_attempts_org_request_attempt`.
- Virtual-key inventory: `ix_virtual_keys_org_created_id`.
- Policy assignment read: `ix_policy_assignments_org_id`.
- Active reservations: `ix_limit_reservations_rule_counter_status_expires`.
- Committed usage: `ix_limit_committed_rule_counter_window_created`.

No important list/range family fell back to a full table scan. The temporary grouping sort is
real but did not produce failures in the measured read profiles.

## Contention And Observability

At 1 VU, gateway and mixed traffic had no failures. At 10 VUs, backend logs repeatedly showed
`sqlite3.OperationalError: database is locked` during gateway request-resolution updates and
gateway policy-decision inserts. The measured 10-VU gateway and mixed profiles each observed
one failed request; one additional lock failure occurred during warm-up. Throughput remained
near the 1-VU rate while tail latency increased by more than an order of magnitude. This is a
`P1` moderate-load reliability finding.

Prometheus scraped 25 `bab_http_requests_total` series, one gateway-request series, and one
provider-attempt series. Final samples included 508 successful and three failed
`POST /v1/chat/completions` HTTP requests; gateway/provider success counters were 508.

Tempo returned representative traces for both paths:

- gateway trace `194c0642d9b51191aae4ad801e6c6fee`, 583 ms;
- usage-summary trace `b11c950dea7a11d04993ca1fefb3d5b`, 208 ms.

No prompts, request bodies, authorization values, or provider credentials were added to metric
labels or trace attributes by this harness.

## Ranked Findings

1. **P1: SQLite gateway write contention at 10 VUs.** Proven lock errors, request failures,
   flat throughput, and 8.4-9.8 second p95 latency under moderate local concurrency.
2. **P3: Usage grouping uses a temporary B-tree.** Measurable plan behavior, but read profiles
   stayed error-free and it does not justify an index/query change before the P1 issue.
3. **No action: provider overhead.** The fixed 20 ms stub is small relative to observed
   gateway latency and cannot explain the concurrency cliff.
4. **No action: indexed list/read paths.** Representative plans use intended indexes.

## Recommendation

Run exactly one follow-up optimization pass: reduce or serialize SQLite gateway write
contention under 10-VU gateway/mixed load, then rerun this baseline unchanged. Do not pursue
the usage grouping temporary B-tree until reliability is restored and remeasured.

## WAL And Serialization Follow-up

Date: 2026-06-30. Same host, Docker allocation, dataset shape, one Uvicorn worker, k6 1.0.0,
20 ms provider delay, 15-second warm-up, and 60-second measured duration as the original
baseline.

### Changes

- Every application SQLite connection now sets `foreign_keys=ON`, `journal_mode=WAL`, and
  `busy_timeout=5000` centrally. `synchronous=FULL` remains unchanged.
- WAL alone did not meet the reliability gate.
- A process-local, SQLite-only async coordinator was therefore added around short gateway
  persistence units: key-use timestamp, gateway history/decisions, guardrail events, limit
  reservation/commit/release, usage/accounting/activity, and post-provider credential status.
- Provider/network calls, policy and guardrail evaluation, and read-only reporting remain
  outside the coordinator.
- The coordinator is reentrant for nested gateway persistence calls and releases after
  exceptions. Non-SQLite sessions bypass it.

The post-provider credential-status update now commits as its own short persistence unit after
the provider call. This prevents that update from holding a SQLite write transaction through
later accounting work.

### WAL-only results

WAL was measured first on a fresh identical seed. One-VU results were clean:

| Scenario | VUs | req/s | p50 ms | p95 ms | p99 ms | Failure rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Gateway | 1 | 4.36 | 219.98 | 457.97 | 490.81 | 0% |
| Mixed 80/20 | 1 | 2.58 | 411.29 | 457.89 | 475.23 | 0% |

Three measured 10-VU repetitions were run for each scenario:

| Scenario | Runs | Avg req/s | Avg p95 ms | Avg p99 ms | Avg failure rate |
| --- | ---: | ---: | ---: | ---: | ---: |
| Gateway | 3 | 4.85 | 7,064.04 | 10,308.31 | 4.01% |
| Mixed 80/20 | 3 | 3.18 | 8,514.81 | 10,841.42 | 4.06% |

The WAL-only stderr contained 159 textual `database is locked` matches. Across the measured
10-VU runs, gateway had 36 failed checks and mixed had 27. WAL improved throughput but did not
fix moderate-concurrency reliability, so this result was rejected.

### Final accepted results

The database was reset, migrated, and reseeded before the final comparison. Smoke passed, and
all three 10-VU repetitions per scenario completed with zero failed checks.

| Scenario | Run | req/s | p50 ms | p95 ms | p99 ms | Failure rate |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Gateway | 1 VU | 4.21 | 231.89 | 467.71 | 480.68 | 0% |
| Gateway | 10 VU r1 | 4.76 | 2,022.21 | 3,949.30 | 4,119.62 | 0% |
| Gateway | 10 VU r2 | 4.72 | 1,860.06 | 3,966.16 | 4,137.28 | 0% |
| Gateway | 10 VU r3 | 4.81 | 2,051.59 | 3,871.97 | 4,038.59 | 0% |
| Mixed 80/20 | 1 VU | 2.50 | 429.81 | 475.30 | 483.17 | 0% |
| Mixed 80/20 | 10 VU r1 | 3.02 | 3,930.44 | 4,333.05 | 5,538.09 | 0% |
| Mixed 80/20 | 10 VU r2 | 3.02 | 3,946.79 | 4,236.36 | 5,519.79 | 0% |
| Mixed 80/20 | 10 VU r3 | 3.01 | 3,933.93 | 4,321.94 | 5,439.86 | 0% |

The accepted averages and original-baseline comparison:

| Scenario | Original req/s | Final avg req/s | Original p95 | Final avg p95 | Final avg p99 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Gateway 10 VU | 3.11 | 4.76 | 8,432.63 ms | 3,929.14 ms | 4,098.50 ms |
| Mixed 10 VU | 1.90 | 3.02 | 9,803.48 ms | 4,297.12 ms | 5,499.25 ms |

Accepted-run stderr contained zero `database is locked` matches. Final Prometheus samples
recorded 1,317 successful chat requests and no 5xx chat series. Tempo contained a
representative gateway trace (`358f90ea7f78c6bc5e7df5646fca79`, 3,276 ms) and usage-summary
trace (`b3dad2713e962743d1d847e949057e47`, 431 ms).

Final SQLite state remained `journal_mode=wal`, `synchronous=2`, `busy_timeout=5000`, with
18,203 4-KiB pages. The measured runs added 1,317 completed gateway, route-attempt, usage,
reservation, and committed-usage rows to the original 10,000-row seed.

### Conclusion

Contention is sufficiently mitigated for the current single-process SQLite build phase.
The coordinator does not provide multi-process write coordination; PostgreSQL remains the
appropriate next infrastructure step if multi-worker or higher-throughput deployment becomes
necessary.
