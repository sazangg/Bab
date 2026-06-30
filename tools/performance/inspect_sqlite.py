"""Report benchmark SQLite state and representative query plans."""

import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATABASE = ROOT / ".runtime" / "bab-performance.db"
TABLES = (
    "teams",
    "projects",
    "virtual_keys",
    "usage_records",
    "gateway_requests",
    "gateway_route_attempts",
    "policy_assignments",
    "limit_policy_reservations",
    "limit_policy_committed_usage",
)


def explain(connection: sqlite3.Connection, name: str, sql: str, parameters: tuple) -> None:
    print(f"\n[{name}]")
    for row in connection.execute(f"EXPLAIN QUERY PLAN {sql}", parameters):
        print(" | ".join(str(value) for value in row))


def main() -> None:
    if not DATABASE.exists():
        raise SystemExit(f"benchmark database does not exist: {DATABASE}")
    with sqlite3.connect(DATABASE) as connection:
        pragmas = {
            name: connection.execute(f"PRAGMA {name}").fetchone()[0]
            for name in (
                "page_count",
                "page_size",
                "freelist_count",
                "journal_mode",
                "synchronous",
                "busy_timeout",
            )
        }
        print(
            json.dumps(
                {
                    "sqlite_version": sqlite3.sqlite_version,
                    "database_bytes": DATABASE.stat().st_size,
                    "pragmas": pragmas,
                    "row_counts": {
                        table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                        for table in TABLES
                    },
                    "indexes": [
                        row[0]
                        for row in connection.execute(
                            """
                            SELECT name FROM sqlite_master
                            WHERE type = 'index' AND name NOT LIKE 'sqlite_%'
                            ORDER BY name
                            """
                        )
                    ],
                },
                indent=2,
            )
        )
        org_id = connection.execute("SELECT id FROM organizations LIMIT 1").fetchone()[0]
        team_id, project_id = connection.execute(
            "SELECT team_id, id FROM projects ORDER BY created_at LIMIT 1"
        ).fetchone()
        virtual_key_id = connection.execute(
            "SELECT id FROM virtual_keys ORDER BY created_at LIMIT 1"
        ).fetchone()[0]
        gateway_id = connection.execute("SELECT id FROM gateway_requests LIMIT 1").fetchone()[0]
        rule = connection.execute("SELECT id FROM limit_policy_rules LIMIT 1").fetchone()
        explain(
            connection,
            "usage time range",
            """
            SELECT * FROM usage_records
            WHERE org_id = ? AND created_at >= ? AND created_at < ?
            ORDER BY created_at DESC, id DESC LIMIT 101
            """,
            (org_id, "2020-01-01", "2030-01-01"),
        )
        explain(
            connection,
            "usage grouped report",
            """
            SELECT public_model_name, SUM(cost_micro_cents)
            FROM usage_records
            WHERE org_id = ? AND created_at >= ? AND created_at < ?
            GROUP BY public_model_name
            """,
            (org_id, "2020-01-01", "2030-01-01"),
        )
        explain(
            connection,
            "gateway history",
            """
            SELECT * FROM gateway_requests
            WHERE org_id = ? AND started_at >= ? AND started_at < ?
            ORDER BY started_at DESC, id DESC LIMIT 51 OFFSET 100
            """,
            (org_id, "2020-01-01", "2030-01-01"),
        )
        explain(
            connection,
            "gateway attempts",
            """
            SELECT * FROM gateway_route_attempts
            WHERE org_id = ? AND gateway_request_id = ?
            ORDER BY attempt_index, started_at, id
            """,
            (org_id, gateway_id),
        )
        explain(
            connection,
            "virtual key inventory",
            """
            SELECT * FROM virtual_keys
            WHERE org_id = ?
            ORDER BY created_at DESC, id DESC LIMIT 51 OFFSET 100
            """,
            (org_id,),
        )
        explain(
            connection,
            "policy assignments",
            """
            SELECT * FROM policy_assignments
            WHERE org_id = ? AND policy_type = ? AND is_active = 1
              AND (effective_from IS NULL OR effective_from <= ?)
              AND (effective_to IS NULL OR effective_to > ?)
              AND (
                scope_type = 'org'
                OR (scope_type = 'team' AND team_id = ?)
                OR (scope_type = 'project' AND project_id = ?)
                OR (scope_type = 'virtual_key' AND virtual_key_id = ?)
              )
            ORDER BY created_at
            """,
            (
                org_id,
                "access",
                "2026-06-30",
                "2026-06-30",
                team_id,
                project_id,
                virtual_key_id,
            ),
        )
        if rule:
            explain(
                connection,
                "active limit reservations",
                """
                SELECT * FROM limit_policy_reservations
                WHERE limit_policy_rule_id = ? AND counter_key = ?
                  AND status = 'active' AND expires_at > ?
                """,
                (rule[0], "benchmark", "2020-01-01"),
            )
            explain(
                connection,
                "committed limit usage",
                """
                SELECT SUM(total_tokens), SUM(cost_micro_cents)
                FROM limit_policy_committed_usage
                WHERE limit_policy_rule_id = ? AND counter_key = ?
                  AND window_descriptor = ? AND created_at >= ?
                """,
                (rule[0], "benchmark", "month:2026-06", "2026-06-01"),
            )


if __name__ == "__main__":
    main()
