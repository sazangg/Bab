"""Create deterministic benchmark scale data in the isolated SQLite database."""

import argparse
import hashlib
import json
import sqlite3
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid5

NAMESPACE = UUID("22222222-2222-4222-8222-222222222222")
ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / ".runtime"
DEFAULT_DB = RUNTIME / "bab-performance.db"
DEFAULT_CONTEXT = RUNTIME / "context.json"


def deterministic_uuid(kind: str, index: int) -> str:
    return uuid5(NAMESPACE, f"{kind}:{index}").hex


def api_request(
    base_url: str,
    method: str,
    path: str,
    payload: dict | None = None,
    token: str | None = None,
) -> dict:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        f"{base_url}{path}",
        data=json.dumps(payload).encode() if payload is not None else None,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode()
        raise RuntimeError(f"{method} {path} failed ({exc.code}): {detail}") from exc
    return json.loads(body) if body else {}


def require_benchmark_path(path: Path) -> Path:
    resolved = path.resolve()
    runtime = RUNTIME.resolve()
    if runtime not in resolved.parents or resolved.name != "bab-performance.db":
        raise ValueError(f"refusing non-benchmark database path: {resolved}")
    if not resolved.exists():
        raise FileNotFoundError(f"migrate the benchmark database first: {resolved}")
    return resolved


def setup_runtime(args: argparse.Namespace) -> dict:
    login = api_request(
        args.base_url,
        "POST",
        "/api/v1/auth/login",
        {"email": args.admin_email, "password": args.admin_password},
    )
    token = login["access_token"]
    provider = api_request(
        args.base_url,
        "POST",
        "/api/v1/providers",
        {
            "name": "Benchmark Provider",
            "base_url": args.provider_url,
        },
        token,
    )
    provider_id = provider["id"]
    credential = api_request(
        args.base_url,
        "POST",
        f"/api/v1/providers/{provider_id}/credentials",
        {"name": "Benchmark credential", "api_key": "benchmark-local-placeholder"},
        token,
    )
    pool = api_request(
        args.base_url,
        "POST",
        f"/api/v1/providers/{provider_id}/pools",
        {"name": "Benchmark pool", "selection_policy": "priority"},
        token,
    )
    api_request(
        args.base_url,
        "POST",
        f"/api/v1/providers/{provider_id}/pools/{pool['id']}/credentials",
        {"provider_credential_id": credential["id"], "priority": 100, "weight": 1},
        token,
    )
    offering = api_request(
        args.base_url,
        "POST",
        f"/api/v1/providers/{provider_id}/offerings",
        {
            "provider_model_name": "benchmark-chat",
            "input_modalities": ["text"],
            "output_modalities": ["text"],
            "capabilities": {"chat": True, "streaming": False},
            "input_price_per_million_tokens": 100,
            "output_price_per_million_tokens": 200,
        },
        token,
    )
    access = api_request(
        args.base_url,
        "POST",
        "/api/v1/policies/access",
        {
            "name": "Benchmark access",
            "public_models": [
                {
                    "public_model_name": "benchmark-chat",
                    "routing_mode": "single_route",
                    "candidates": [
                        {
                            "provider_id": provider_id,
                            "credential_pool_id": pool["id"],
                            "model_offering_id": offering["id"],
                        }
                    ],
                }
            ],
        },
        token,
    )
    api_request(
        args.base_url,
        "POST",
        "/api/v1/policies/assignments",
        {
            "policy_type": "access",
            "policy_id": access["policy_id"],
            "scope_type": "org",
        },
        token,
    )
    limit = api_request(
        args.base_url,
        "POST",
        "/api/v1/policies/limits",
        {
            "name": "Benchmark limits",
            "rules": [
                {
                    "name": "Request ceiling",
                    "limit_type": "requests",
                    "limit_value": 1_000_000_000,
                    "interval_unit": "month",
                }
            ],
        },
        token,
    )
    api_request(
        args.base_url,
        "POST",
        "/api/v1/policies/assignments",
        {
            "policy_type": "limit",
            "policy_id": limit["policy_id"],
            "scope_type": "org",
        },
        token,
    )
    teams = []
    projects = []
    for team_index in range(args.teams):
        team = api_request(
            args.base_url,
            "POST",
            "/api/v1/teams",
            {
                "name": f"Benchmark Team {team_index:02d}",
                "slug": f"benchmark-team-{team_index:02d}",
            },
            token,
        )
        teams.append(team)
        for project_index in range(args.projects // args.teams):
            project = api_request(
                args.base_url,
                "POST",
                f"/api/v1/teams/{team['id']}/projects",
                {"name": f"Benchmark Project {team_index:02d}-{project_index:02d}"},
                token,
            )
            projects.append(project)
    gateway_key = api_request(
        args.base_url,
        "POST",
        f"/api/v1/projects/{projects[0]['id']}/keys",
        {"name": "Benchmark gateway key"},
        token,
    )
    return {
        "provider_id": provider_id,
        "credential_id": credential["id"],
        "pool_id": pool["id"],
        "offering_id": offering["id"],
        "access_policy_id": access["policy_id"],
        "limit_policy_id": limit["policy_id"],
        "teams": teams,
        "projects": projects,
        "virtual_key": gateway_key["key"],
        "gateway_key_id": gateway_key["id"],
    }


def bulk_seed(connection: sqlite3.Connection, runtime: dict, args: argparse.Namespace) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    org_id = connection.execute("SELECT id FROM organizations LIMIT 1").fetchone()[0]
    admin_id = connection.execute("SELECT id FROM users LIMIT 1").fetchone()[0]
    projects = [
        (UUID(item["id"]).hex, UUID(item["team_id"]).hex) for item in runtime["projects"]
    ]
    gateway_key_id = UUID(runtime["gateway_key_id"]).hex
    key_rows = []
    for index in range(1, args.virtual_keys):
        raw_key = f"bab_benchmark_{index:08d}"
        project_id, _team_id = projects[index % len(projects)]
        key_rows.append(
            (
                deterministic_uuid("virtual-key", index),
                org_id,
                project_id,
                f"Benchmark Key {index:04d}",
                hashlib.sha256(raw_key.encode()).hexdigest(),
                raw_key[:16],
                admin_id,
                (now - timedelta(minutes=index)).isoformat(),
                (now - timedelta(minutes=index)).isoformat(),
            )
        )
    connection.executemany(
        """
        INSERT INTO virtual_keys (
            id, org_id, project_id, name, key_hash, key_prefix, created_by, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        key_rows,
    )
    provider_id = UUID(runtime["provider_id"]).hex
    credential_id = UUID(runtime["credential_id"]).hex
    pool_id = UUID(runtime["pool_id"]).hex
    access_policy_id = UUID(runtime["access_policy_id"]).hex
    public_model = connection.execute(
        "SELECT id FROM access_policy_public_models LIMIT 1"
    ).fetchone()[0]
    candidate = connection.execute(
        "SELECT id FROM access_policy_route_candidates LIMIT 1"
    ).fetchone()[0]
    offering_id = UUID(runtime["offering_id"]).hex
    gateway_rows = []
    attempt_rows = []
    usage_rows = []
    all_key_ids = [gateway_key_id, *[row[0] for row in key_rows]]
    for index in range(args.gateway_requests):
        gateway_id = deterministic_uuid("gateway", index)
        attempt_id = deterministic_uuid("attempt", index)
        project_id, team_id = projects[index % len(projects)]
        key_id = all_key_ids[index % len(all_key_ids)]
        created_at = now - timedelta(seconds=index * 200)
        timestamp = created_at.isoformat()
        gateway_rows.append(
            (
                gateway_id,
                org_id,
                team_id,
                project_id,
                key_id,
                f"seed-request-{index}",
                "chat_completions",
                "benchmark-chat",
                public_model,
                "benchmark-chat",
                "single_route",
                200,
                access_policy_id,
                public_model,
                candidate,
                provider_id,
                pool_id,
                offering_id,
                "benchmark-chat",
                1,
                0,
                timestamp,
                (created_at + timedelta(days=30)).isoformat(),
                (created_at + timedelta(milliseconds=25)).isoformat(),
            )
        )
        attempt_rows.append(
            (
                attempt_id,
                org_id,
                gateway_id,
                0,
                access_policy_id,
                public_model,
                candidate,
                candidate,
                provider_id,
                "Benchmark Provider",
                "benchmark-provider",
                pool_id,
                "Benchmark pool",
                credential_id,
                "Benchmark credential",
                offering_id,
                "benchmark-chat",
                "benchmark-chat",
                "succeeded",
                200,
                25,
                4,
                2,
                6,
                1,
                100_000,
                "provider",
                "{}",
                "{}",
                "{}",
                timestamp,
                (created_at + timedelta(milliseconds=25)).isoformat(),
            )
        )
        if index < args.usage_records:
            usage_rows.append(
                (
                    deterministic_uuid("usage", index),
                    org_id,
                    team_id,
                    project_id,
                    access_policy_id,
                    gateway_id,
                    attempt_id,
                    public_model,
                    candidate,
                    "logical_request",
                    key_id,
                    pool_id,
                    provider_id,
                    credential_id,
                    f"seed-request-{index}",
                    "benchmark-chat",
                    "benchmark-chat",
                    "benchmark-chat",
                    "single_route",
                    0,
                    1,
                    candidate,
                    "chat_completions",
                    200,
                    25,
                    4,
                    2,
                    6,
                    1,
                    100_000,
                    "provider",
                    "{}",
                    timestamp,
                )
            )
    connection.executemany(
        """
        INSERT INTO gateway_requests (
            id, org_id, team_id, project_id, virtual_key_id, request_id, gateway_endpoint,
            requested_model, public_model_id, public_model_name, routing_mode,
            final_http_status, final_access_policy_id, final_public_model_id,
            final_candidate_id, final_provider_id, final_credential_pool_id,
            final_model_offering_id, final_provider_model, attempt_count, fallback_attempted,
            started_at, trace_expires_at, completed_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        gateway_rows,
    )
    connection.executemany(
        """
        INSERT INTO gateway_route_attempts (
            id, org_id, gateway_request_id, attempt_index, access_policy_id,
            access_public_model_id, route_candidate_id, primary_route_candidate_id,
            provider_id, provider_name, provider_slug, credential_pool_id,
            credential_pool_name, provider_credential_id, provider_credential_name,
            provider_model_offering_id, provider_model, public_model_name, status,
            http_status, latency_ms, prompt_tokens, completion_tokens, total_tokens,
            cost_cents, cost_micro_cents, usage_source, pricing_snapshot,
            capability_snapshot, route_snapshot, started_at, completed_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        attempt_rows,
    )
    connection.executemany(
        """
        INSERT INTO usage_records (
            id, org_id, team_id, project_id, access_policy_id, gateway_request_id,
            route_attempt_id, public_model_id, route_candidate_id, limit_counting_unit,
            virtual_key_id,
            pool_id, provider_id, provider_credential_id, request_id, requested_model,
            provider_model, public_model_name, routing_mode, routing_attempt_index,
            is_final_attempt, primary_route_candidate_id, gateway_endpoint, http_status,
            latency_ms, prompt_tokens, completion_tokens, total_tokens, cost_cents,
            cost_micro_cents, usage_source, dimension_snapshot, created_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        usage_rows,
    )
    connection.execute(
        """
        UPDATE gateway_requests
        SET final_route_attempt_id = (
            SELECT id FROM gateway_route_attempts
            WHERE gateway_route_attempts.gateway_request_id = gateway_requests.id
            LIMIT 1
        )
        """
    )
    connection.commit()


def print_counts(connection: sqlite3.Connection) -> None:
    tables = (
        "organizations",
        "teams",
        "projects",
        "virtual_keys",
        "providers",
        "provider_credentials",
        "credential_pools",
        "provider_model_offerings",
        "policies",
        "policy_assignments",
        "usage_records",
        "gateway_requests",
        "gateway_route_attempts",
    )
    for table in tables:
        count = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"{table}: {count}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--provider-url", default="http://127.0.0.1:8080/v1")
    parser.add_argument("--admin-email", default="benchmark-admin@example.com")
    parser.add_argument("--admin-password", default="benchmark-admin-password")
    parser.add_argument("--teams", type=int, default=10)
    parser.add_argument("--projects", type=int, default=30)
    parser.add_argument("--virtual-keys", type=int, default=500)
    parser.add_argument("--usage-records", type=int, default=10_000)
    parser.add_argument("--gateway-requests", type=int, default=10_000)
    args = parser.parse_args()
    if args.projects % args.teams:
        parser.error("--projects must be divisible by --teams")
    database = require_benchmark_path(args.database)
    runtime = setup_runtime(args)
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        bulk_seed(connection, runtime, args)
        print_counts(connection)
    RUNTIME.mkdir(parents=True, exist_ok=True)
    DEFAULT_CONTEXT.write_text(
        json.dumps(
            {
                "admin_email": args.admin_email,
                "admin_password": args.admin_password,
                "virtual_key": runtime["virtual_key"],
            },
            indent=2,
        )
        + "\n"
    )
    print(f"runtime context: {DEFAULT_CONTEXT}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"seed failed: {exc}", file=sys.stderr)
        raise
