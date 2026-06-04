"""Apply migration 0029 — DROP FUNCTION get_recent_arrivals().

CTK-011 session 1 pre-step, step 3 of the 0028-header sequencing: the
verify cycle completed at CTK-109 close 2026-06-03 (deploy + Jon eyeball
PASS on /new), so the predecessor function retires. Residual-caller grep
at write time: lib/ + app/ comment-only; scripts/diag_neon_data_plane.py
section (4) is the lone live invocation and is try/except-wrapped
(degrades to a printed EXCEPTION line, re-point on next touch).

Uses scrapers.common.db.get_conn per CTK-061 amendment-2 single-statement
path. DROP IF EXISTS keeps re-runs no-op-safe, same idempotency posture
as 0027/0028.

Verification: post-apply queries pg_proc — get_recent_arrivals absent,
get_listing_lead_event + get_recent_price_drops still present.
"""

from __future__ import annotations

import sys
from pathlib import Path

from scrapers.common.db import get_conn

MIGRATION_PATH = Path(__file__).resolve().parent.parent / "supabase" / "migrations" / "0029_drop_get_recent_arrivals.sql"


def main() -> int:
    sql = MIGRATION_PATH.read_text(encoding="utf-8")

    with get_conn() as conn:
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
        print("post-apply verification — pg_proc presence")
        print("=" * 70)

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT proname, pg_get_function_identity_arguments(oid) AS args
                FROM pg_proc
                WHERE proname IN ('get_recent_arrivals', 'get_listing_lead_event',
                                  'get_recent_price_drops')
                  AND pronamespace = 'public'::regnamespace
                ORDER BY proname
                """
            )
            rows = cur.fetchall()
        present = {r["proname"] for r in rows}
        for row in rows:
            print(f"  {row['proname']}({row['args']})")

        if "get_recent_arrivals" in present:
            print("  EXPECTED ABSENT: get_recent_arrivals still present after 0029 DROP")
            return 1
        if "get_listing_lead_event" not in present:
            print("  MISSING: get_listing_lead_event collateral-dropped (0029 should not touch it)")
            return 1
        if "get_recent_price_drops" not in present:
            print("  MISSING: get_recent_price_drops collateral-dropped (0029 should not touch it)")
            return 1
        print("  get_recent_arrivals absent; siblings intact")

    return 0


if __name__ == "__main__":
    sys.exit(main())
