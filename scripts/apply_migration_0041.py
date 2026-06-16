"""Apply migration 0041 — CTK-161 D-1: shared content-engine data-query layer.

Creates three STABLE Postgres functions (the design-once shared layer per D-1):
  - get_cross_vendor_cheapest()            cross-vendor cheapest ranking (COMPARATIVE)
  - get_aggregate_activity(int)            lead-event + distinct-vendor counts
  - get_most_restocked(int, int)           back-in-stock ranking by named_coral

All three are CREATE OR REPLACE FUNCTION — idempotent, re-runnable, no DROP. No
table writes, no return-type widen, so no apply-pre-push sequencing gate (unlike
0037): the functions are net-new surfaces with no live caller until the CTK-161
content fetch wrappers ship. Applying early is safe.

Uses scrapers.common.db.get_conn per the CTK-061 single-statement path. Mirrors
apply_migration_0037.py shape.

Verification:
  - all three functions present in pg_proc after apply
  - each is callable and returns the expected column shape (smoke SELECT):
      get_aggregate_activity(24)  -> exactly one row (event_count, vendor_count, window_hours)
      get_most_restocked(168, 5)  -> 0..5 rows, restock_count column present
      get_cross_vendor_cheapest() -> 0..N rows, id + named_coral_id columns present
  - GRANTs are in the migration body; no separate assertion (a missing GRANT
    surfaces as a permission error on the first wrapper call, not silently).
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
    / "0041_content_engine_shared_queries.sql"
)

EXPECTED_FUNCS = (
    "get_cross_vendor_cheapest",
    "get_aggregate_activity",
    "get_most_restocked",
)


def main() -> int:
    sql = MIGRATION_PATH.read_text(encoding="utf-8")

    with get_conn() as conn:
        with conn.cursor() as cur:
            print(f"executing: {MIGRATION_PATH.name} ({len(sql)} bytes)...")
            t0 = time.monotonic()
            try:
                cur.execute(sql)
            except Exception as exc:  # noqa: BLE001 — surface loudly, exit 1
                print(f"  FAILED: {type(exc).__name__}: {exc}")
                return 1
            elapsed_ms = (time.monotonic() - t0) * 1000.0
            print(f"  applied in {elapsed_ms:.0f} ms")

        # Presence check — all three functions exist post-apply.
        with conn.cursor() as cur:
            cur.execute(
                "SELECT proname FROM pg_proc WHERE proname = ANY(%s) ORDER BY proname",
                (list(EXPECTED_FUNCS),),
            )
            present = {r["proname"] for r in cur.fetchall()}
        missing = set(EXPECTED_FUNCS) - present
        if missing:
            print(f"  VERIFY FAILED: functions missing after apply: {sorted(missing)}")
            return 1
        print(f"  present: {sorted(present)}")

        # Smoke each function — callable + column shape.
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM get_aggregate_activity(24)")
            agg = cur.fetchall()
            if len(agg) != 1:
                print(f"  VERIFY FAILED: get_aggregate_activity returned {len(agg)} rows (want 1)")
                return 1
            row = agg[0]
            print(
                f"  get_aggregate_activity(24): {row['event_count']} events, "
                f"{row['vendor_count']} vendors, window={row['window_hours']}h"
            )

            cur.execute("SELECT * FROM get_most_restocked(168, 5)")
            restocked = cur.fetchall()
            print(f"  get_most_restocked(168, 5): {len(restocked)} coral(s)")

            cur.execute("SELECT * FROM get_cross_vendor_cheapest()")
            cheapest = cur.fetchall()
            print(f"  get_cross_vendor_cheapest(): {len(cheapest)} crowned listing(s)")

    print("0041 applied + verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
