"""Apply migration 0030 — get_listing_lead_event() row_limit parameter.

CTK-011 session 1 pre-step. Adds row_limit int DEFAULT 100 as the fourth
parameter; body otherwise unchanged from 0028 (LIMIT 100 -> LIMIT
row_limit; LIMIT NULL = uncapped). Existing 3-arg callers
(lib/queries/listings.ts:134,642) keep current behavior via the default.

Uses scrapers.common.db.get_conn per CTK-061 amendment-2 single-statement
path. DROP + CREATE (parameter-list change rejects CREATE OR REPLACE);
GRANT re-asserted in the migration against the 4-arg signature.

Smoke per directive:
  (1) baseline capture BEFORE apply — 3-arg call (id, event) ordered set
  (2) post-apply 3-arg call returns identical rows to baseline
  (3) 4-arg with row_limit=5 returns 5 rows
  (4) 4-arg with row_limit=NULL returns the full window (>= default-path
      count; uncapped)

Baseline and post-apply run seconds apart against now()-anchored windows;
a window-edge event sliding out between the two reads as a diff — the
comparison prints both sets on mismatch so edge-drift is distinguishable
from a real shape change.
"""

from __future__ import annotations

import sys
from pathlib import Path

from scrapers.common.db import get_conn

MIGRATION_PATH = Path(__file__).resolve().parent.parent / "supabase" / "migrations" / "0030_get_listing_lead_event_row_limit.sql"

THREE_ARG = "SELECT id, event FROM get_listing_lead_event(NULL, 24, NULL) ORDER BY id"


def main() -> int:
    sql = MIGRATION_PATH.read_text(encoding="utf-8")

    with get_conn() as conn:
        print("=" * 70)
        print("baseline — pre-apply get_listing_lead_event(NULL, 24, NULL)")
        print("=" * 70)
        with conn.cursor() as cur:
            cur.execute(THREE_ARG)
            baseline = [(r["id"], r["event"]) for r in cur.fetchall()]
        print(f"  {len(baseline)} rows")

        with conn.cursor() as cur:
            print(f"executing: {MIGRATION_PATH.name} ({len(sql)} bytes)...")
            try:
                cur.execute(sql)
            except Exception as exc:
                print(f"  FAILED: {type(exc).__name__}: {exc}")
                return 1
            print("  ok")

        print()
        print("=" * 70)
        print("post-apply verification — signature")
        print("=" * 70)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT proname, pg_get_function_identity_arguments(oid) AS args
                FROM pg_proc
                WHERE proname = 'get_listing_lead_event'
                  AND pronamespace = 'public'::regnamespace
                """
            )
            rows = cur.fetchall()
        if len(rows) != 1:
            print(f"  EXPECTED exactly 1 signature, found {len(rows)}: {rows}")
            return 1
        args = rows[0]["args"]
        print(f"  get_listing_lead_event({args})")
        if "row_limit" not in args:
            print("  MISSING: row_limit parameter not in signature")
            return 1

        print()
        print("=" * 70)
        print("smoke — default-path parity + row_limit behavior")
        print("=" * 70)
        with conn.cursor() as cur:
            # (2) 3-arg default path: identical rows to pre-migration.
            cur.execute(THREE_ARG)
            post = [(r["id"], r["event"]) for r in cur.fetchall()]
            if post == baseline:
                print(f"  3-arg parity: PASS ({len(post)} rows identical to baseline)")
            else:
                only_pre = set(baseline) - set(post)
                only_post = set(post) - set(baseline)
                print(f"  3-arg parity: MISMATCH (baseline {len(baseline)} vs post {len(post)})")
                print(f"    baseline-only: {sorted(only_pre)}")
                print(f"    post-only:     {sorted(only_post)}")
                return 1

            # (3) row_limit=5 caps at 5.
            cur.execute("SELECT COUNT(*) AS c FROM get_listing_lead_event(NULL, 24, NULL, 5)")
            c5 = cur.fetchone()["c"]
            print(f"  row_limit=5:    {c5} rows {'PASS' if c5 == 5 else 'FAIL (expected 5)'}")
            if c5 != 5:
                return 1

            # (4) row_limit=NULL uncapped — full window, >= default-path count.
            cur.execute("SELECT COUNT(*) AS c FROM get_listing_lead_event(NULL, 24, NULL, NULL)")
            cnull = cur.fetchone()["c"]
            print(f"  row_limit=NULL: {cnull} rows {'PASS' if cnull >= len(post) else 'FAIL (uncapped < default-path count)'}")
            if cnull < len(post):
                return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
