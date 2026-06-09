"""Apply migration 0037 — CTK-016 Leg 1 (D-1): email_signups.token column.

Adds email_signups.token text NOT NULL DEFAULT gen_random_uuid()::text + a
unique index idx_es_token. The volatile default backfills every existing row
with a distinct non-null token in one ADD COLUMN statement (a table rewrite,
not the PG11 constant-default fast-path) — no separate UPDATE.

SEQUENCING GATE — apply-pre-push: run this BEFORE Leg 3 deploys the actions.ts
change that mints tokens app-side. The NOT NULL DEFAULT keeps any signup landing
in the apply->Leg-3 deploy gap tokened (without it, those rows write NULL token
on a Tier-1B surface). Migration first, code later. Additive + defaulted, so the
currently-deployed code (which never references token) keeps working after apply.

Uses scrapers.common.db.get_conn per the CTK-061 single-statement path. Mirrors
apply_migration_0036.py shape. Idempotent: ADD COLUMN / CREATE INDEX IF NOT EXISTS.

Verification:
  - column present on email_signups, type text, NOT NULL (is_nullable = NO)
  - unique index idx_es_token present
  - row count unchanged across the rewrite (no row loss)
  - every existing row has a distinct, non-null token (count == distinct == non-null)
  - ADD COLUMN elapsed wall-time reported (confirms the rewrite was instant at
    this table size)
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from scrapers.common.db import get_conn

MIGRATION_PATH = (
    Path(__file__).resolve().parent.parent
    / "supabase"
    / "migrations"
    / "0037_add_email_signups_token.sql"
)


def main() -> int:
    sql = MIGRATION_PATH.read_text(encoding="utf-8")

    with get_conn() as conn:
        # Pre-apply row count — the rewrite must not lose or duplicate rows.
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) AS n FROM email_signups")
            rows_before = cur.fetchone()["n"]
        print(f"email_signups rows before apply: {rows_before}")

        with conn.cursor() as cur:
            print(f"executing: {MIGRATION_PATH.name} ({len(sql)} bytes)...")
            t0 = time.monotonic()
            try:
                cur.execute(sql)
            except Exception as exc:
                print(f"  FAILED: {type(exc).__name__}: {exc}")
                return 1
            elapsed_ms = (time.monotonic() - t0) * 1000.0
            print(f"  ok ({elapsed_ms:.1f} ms — ADD COLUMN rewrite + index + comment)")

        print()
        print("=" * 70)
        print("post-apply verification — token column on email_signups")
        print("=" * 70)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT data_type, is_nullable "
                "FROM information_schema.columns "
                "WHERE table_name = 'email_signups' AND column_name = 'token'"
            )
            col = cur.fetchone()

        if col is None:
            print("  DEFECT: column token not present after apply")
            return 1
        if col["data_type"] != "text":
            print(f"  DEFECT: token is {col['data_type']}, expected text")
            return 1
        if col["is_nullable"] != "NO":
            print(f"  DEFECT: token is_nullable={col['is_nullable']}, expected NO")
            return 1
        print(f"  token: {col['data_type']} NOT NULL (is_nullable=NO)")

        print()
        print("=" * 70)
        print("post-apply verification — unique index idx_es_token")
        print("=" * 70)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT indexdef FROM pg_indexes "
                "WHERE tablename = 'email_signups' AND indexname = 'idx_es_token'"
            )
            idx = cur.fetchone()

        if idx is None:
            print("  DEFECT: idx_es_token not present after apply")
            return 1
        if "UNIQUE" not in idx["indexdef"].upper():
            print(f"  DEFECT: idx_es_token is not UNIQUE — {idx['indexdef']}")
            return 1
        print(f"  {idx['indexdef']}")

        print()
        print("=" * 70)
        print("post-apply verification — backfill: every row distinct + non-null")
        print("=" * 70)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) AS n, "
                "       count(token) AS non_null, "
                "       count(DISTINCT token) AS distinct_tok "
                "FROM email_signups"
            )
            r = cur.fetchone()

        if r["n"] != rows_before:
            print(f"  DEFECT: row count changed {rows_before} -> {r['n']} across rewrite")
            return 1
        if r["non_null"] != r["n"]:
            print(f"  DEFECT: {r['n'] - r['non_null']} rows have NULL token")
            return 1
        if r["distinct_tok"] != r["n"]:
            print(f"  DEFECT: {r['n'] - r['distinct_tok']} duplicate tokens (n={r['n']})")
            return 1
        print(
            f"  rows={r['n']}  non_null={r['non_null']}  distinct={r['distinct_tok']} "
            f"-> all rows carry a distinct, non-null token"
        )

        print()
        print("all checks passed")

    return 0


if __name__ == "__main__":
    sys.exit(main())
