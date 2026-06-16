"""Apply migration 0039 — CTK-042: gate auction rows out of
get_listing_lead_event() across all three arms (is_auction = false).

CREATE OR REPLACE on the existing 4-arg signature (0030) — body unchanged
except the three arm WHERE clauses. No DROP (signature + RETURNS shape are
byte-identical to 0030).

LOAD-BEARING APPLY ORDER: migration 0038 (column) -> the backfill
(scrapers/tools/ctk042_is_auction_backfill.py --apply, sets is_auction=true on
the live auction set) -> THIS migration. Applying this before the backfill
gates on an all-false column and excludes nothing — the leak would continue.

Uses scrapers.common.db.get_conn. Reads the .sql file and executes it as a
single batch under the autocommit connection. Mirrors apply_migration_0033.py.

Idempotent: CREATE OR REPLACE — re-running rebinds the function.

Verification:
  - function present in pg_proc with the 4-arg signature
  - all three arms gate on is_auction = false (pg_get_functiondef text scan)
  - INV-05 spot-check: 0 is_auction=true rows in get_listing_lead_event(
    NULL, 24, NULL) output (the digest caller's shape)
"""

from __future__ import annotations

import sys
from pathlib import Path

from scrapers.common.db import get_conn

MIGRATION_PATH = (
    Path(__file__).resolve().parent.parent
    / "supabase" / "migrations" / "0039_get_listing_lead_event_is_auction_gate.sql"
)


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
        print("post-apply verification — signature + arm predicates")
        print("=" * 70)

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT pg_get_function_identity_arguments(oid) AS args,
                       pg_get_functiondef(oid) AS def
                FROM pg_proc
                WHERE proname = 'get_listing_lead_event'
                  AND pronamespace = 'public'::regnamespace
                """
            )
            rows = cur.fetchall()
        if not rows:
            print("  MISSING: get_listing_lead_event not found")
            return 1
        fn = rows[0]
        print(f"  get_listing_lead_event({fn['args']})")
        # All three arms must carry is_auction = false. Each arm references
        # is_auction = false once; expect 3 occurrences in the function body.
        gate_count = fn["def"].count("is_auction = false")
        print(f"  is_auction = false occurrences in body: {gate_count} (expect 3 — one per arm)")
        if gate_count < 3:
            print("  MISSING: not every arm gates on is_auction = false")
            return 1

        print()
        print("=" * 70)
        print("INV-05 spot-check — 0 auction rows in the digest-shape call")
        print("=" * 70)

        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS c "
                "FROM get_listing_lead_event(NULL, 24, NULL) e "
                "JOIN vendor_listings vl ON vl.id = e.id "
                "WHERE vl.is_auction = true"
            )
            leaked = cur.fetchone()["c"]
        print(f"  is_auction=true rows in get_listing_lead_event(NULL,24,NULL): {leaked} (expect 0)")
        if leaked != 0:
            print("  LEAK: auction rows still present — did the backfill run before this migration?")
            return 1

    print()
    print("APPLIED — auction rows gated off all three lead-event arms.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
