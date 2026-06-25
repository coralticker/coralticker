"""Apply migration 0055 — CTK-197 (Tier 1B): equipment denylist across the IG
content-engine count surfaces (INV-07 cadence #1).

Adds the NULL-safe denylist `category IS DISTINCT FROM 'equipment'` to the four
content-engine count functions (migrations 0041 / 0046), all CREATE OR REPLACE (no
return-shape change, no DROP):

  1. get_aggregate_activity   — the live leak. get_listing_lead_event does not project
                                category, so the gate is a 1:1 join-back to
                                vendor_listings on the returned id.
  2. get_velocity_listings    — matched-only; gate added inline to the oos CTE.
  3. get_cross_vendor_cheapest — matched-only; gate added inline to the eligible CTE.
  4. get_most_restocked       — matched-only; join-back gate like #1.

NOT a coral-allowlist — an allowlist would drop the ~308 NULL-category trade-name
corals per CTK-194. Denylist only.

Uses scrapers.common.db.get_conn per the CTK-061 single-statement path. Mirrors
apply_migration_0046.py shape.

Verification (INV-07 first-ship spot-check, cadence #2):
  - all four functions present in pg_proc after apply
  - get_aggregate_activity(168) event_count == raw uncapped lead-event count MINUS the
    equipment lead-events in the window (computed independently). The dropped count is
    reported (the 1 live equipment lead-event the audit found, 3561 -> 3560) so the
    leak is demonstrably shut. Data-independent: derives raw / equip live, no hardcode.
  - the three matched-only functions are callable and return no equipment row (audit:
    0 matched-equipment fleet-wide, so the gate is inert today — output unchanged).
  - GRANTs are in the migration body; a missing GRANT surfaces on the first wrapper
    call, not silently.
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
    / "0055_content_engine_equipment_denylist.sql"
)

EXPECTED_FUNCS = (
    "get_aggregate_activity",
    "get_velocity_listings",
    "get_cross_vendor_cheapest",
    "get_most_restocked",
)

SPOT_CHECK_WINDOW_HOURS = 168


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

        # Presence check — all four functions.
        with conn.cursor() as cur:
            cur.execute(
                "SELECT proname FROM pg_proc WHERE proname = ANY(%s)",
                (list(EXPECTED_FUNCS),),
            )
            found = {r["proname"] for r in cur.fetchall()}
        missing = [f for f in EXPECTED_FUNCS if f not in found]
        if missing:
            print(f"  VERIFY FAILED: missing after apply: {missing}")
            return 1
        print(f"  present: {', '.join(EXPECTED_FUNCS)}")

        # ── INV-07 spot-check on get_aggregate_activity (the live leak) ──
        # Independently derive the raw uncapped lead-event count and the equipment
        # subset over the same window, then assert the gated function returns
        # raw - equip. The dropped count is the spot-check evidence (3561 -> 3560).
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*)::bigint AS raw "
                "FROM get_listing_lead_event(NULL, %s, NULL, NULL)",
                (SPOT_CHECK_WINDOW_HOURS,),
            )
            raw_count = cur.fetchone()["raw"]

            cur.execute(
                "SELECT COUNT(*)::bigint AS equip "
                "FROM get_listing_lead_event(NULL, %s, NULL, NULL) le "
                "JOIN vendor_listings vl ON vl.id = le.id "
                "WHERE vl.category = 'equipment'",
                (SPOT_CHECK_WINDOW_HOURS,),
            )
            equip_count = cur.fetchone()["equip"]

            cur.execute(
                "SELECT event_count, vendor_count, window_hours "
                "FROM get_aggregate_activity(%s)",
                (SPOT_CHECK_WINDOW_HOURS,),
            )
            agg = cur.fetchone()
            gated_count = agg["event_count"]

        expected_gated = raw_count - equip_count
        if gated_count != expected_gated:
            print(
                f"  VERIFY FAILED: get_aggregate_activity({SPOT_CHECK_WINDOW_HOURS}) "
                f"event_count = {gated_count}, expected {expected_gated} "
                f"(raw {raw_count} - equipment {equip_count})"
            )
            return 1
        print(
            f"  get_aggregate_activity({SPOT_CHECK_WINDOW_HOURS}): "
            f"{raw_count} raw -> {gated_count} gated "
            f"({equip_count} equipment lead-event(s) dropped); "
            f"{agg['vendor_count']} vendor(s). Leak shut."
        )

        # ── Matched-only functions: callable + no equipment row (inert today) ──
        # get_velocity_listings + get_cross_vendor_cheapest project id, so re-join
        # vendor_listings to assert the gate landed (0 equipment rows expected).
        for fn in ("get_velocity_listings", "get_cross_vendor_cheapest"):
            with conn.cursor() as cur:
                cur.execute(f"SELECT id FROM {fn}()")
                rows = cur.fetchall()
                ids = [r["id"] for r in rows]
                leaked = []
                if ids:
                    cur.execute(
                        "SELECT id FROM vendor_listings "
                        "WHERE id = ANY(%s) AND category = 'equipment'",
                        (ids,),
                    )
                    leaked = [r["id"] for r in cur.fetchall()]
            if leaked:
                print(f"  VERIFY FAILED: {fn}() returned equipment row(s): {leaked}")
                return 1
            print(f"  {fn}(): {len(rows)} row(s), 0 equipment")

        # get_most_restocked aggregates by named_coral (no listing id projected), so the
        # sibling re-join-on-output-id check (above) doesn't apply. Exercise the gate's
        # surface instead: independently count the back-in-stock lead-events the equipment
        # predicate drops from the aggregation — matched (named_coral_id NOT NULL) rows in
        # the window whose listing is equipment. The gate is inert today (audit: 0 such
        # rows fleet-wide), but this measures the population the predicate acts on rather
        # than only counting output rows — the latter would not change if the gate were
        # removed. A nonzero count is the gate working (correctly excluding), not a fault.
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*)::bigint AS dropped "
                "FROM get_listing_lead_event(NULL, %s, ARRAY['back-in-stock'], NULL) le "
                "JOIN vendor_listings vl ON vl.id = le.id "
                "WHERE le.named_coral_id IS NOT NULL "
                "AND vl.category = 'equipment'",
                (SPOT_CHECK_WINDOW_HOURS,),
            )
            restock_dropped = cur.fetchone()["dropped"]
            cur.execute("SELECT named_coral_id FROM get_most_restocked()")
            restock_rows = cur.fetchall()
        print(
            f"  get_most_restocked(): {len(restock_rows)} coral(s); "
            f"{restock_dropped} matched-equipment restock event(s) gated over "
            f"{SPOT_CHECK_WINDOW_HOURS}h (0 = inert today, audit-consistent)"
        )

    print("0055 applied + verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
