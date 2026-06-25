"""Apply migration 0058 — CTK-198 item #4: exclude single-timestamp bulk-insert
cohorts (bulk_cluster = true) from get_aggregate_activity's headline count.

Stacks the `AND vl.bulk_cluster = false` predicate onto the SAME join-back WHERE that
migration 0055 added `category IS DISTINCT FROM 'equipment'` to. CREATE OR REPLACE, no
return-shape change, no DROP. Mirrors apply_migration_0055.py shape.

This is a LATENT fix — get_aggregate_activity has no live caller today (built but
unwired; _BUILDERS = f7/f8/f9), so the apply changes no live surface. The verify
therefore can't lean on a user-visible delta; it exercises the guarantee directly.

Verification (exercises the guarantee, not just the delta — the 0055 most_restocked
tautology lesson /code-review flagged):
  - get_aggregate_activity present after apply, and its live body carries BOTH the
    equipment AND the bulk_cluster predicates.
  - The function's event_count equals the count with BOTH predicates applied
    independently (raw lead-events minus equipment minus bulk_cluster cohorts). This
    assertion is fail-if-deleted: with only the equipment gate the function would
    return ~3634, not ~350, so the equality fails the instant the predicate is dropped.
  - The bulk_cluster guard has live teeth: the non-equipment bulk_cluster=true rows it
    uniquely removes are > 0 (unlike the equipment gate, which is ~1 and near-inert).
    Reported as the magnitude anchor (~3634 -> ~350, the ~90% bulk-dump inflation).
  - Accounting identity: gated + bulk_dropped + equipment_dropped == raw.
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
    / "0058_get_aggregate_activity_bulk_cluster.sql"
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

        # Presence + both predicates carried in the live body.
        with conn.cursor() as cur:
            cur.execute(
                "SELECT pg_get_functiondef(p.oid) AS def "
                "FROM pg_proc p WHERE p.proname = 'get_aggregate_activity'"
            )
            row = cur.fetchone()
            if row is None:
                print("  VERIFY FAILED: get_aggregate_activity missing after apply")
                return 1
            body = row["def"]
        has_equip = "IS DISTINCT FROM 'equipment'" in body
        has_bulk = "bulk_cluster = false" in body
        if not (has_equip and has_bulk):
            print(
                f"  VERIFY FAILED: live body predicates — equipment={has_equip}, "
                f"bulk_cluster={has_bulk} (both required)"
            )
            return 1
        print("  present: get_aggregate_activity (equipment + bulk_cluster predicates live)")

        # ── Exercise the guarantee on the live leak window ──
        # Independently derive raw / equipment-dropped / bulk-dropped / both-gated over
        # the same window, then assert the function returns the both-gated count and the
        # bulk guard has teeth. get_listing_lead_event does not project category or
        # bulk_cluster, so each subset re-joins vendor_listings on the returned id.
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*)::bigint AS raw "
                "FROM get_listing_lead_event(NULL, %s, NULL, NULL)",
                (SPOT_CHECK_WINDOW_HOURS,),
            )
            raw_count = cur.fetchone()["raw"]

            cur.execute(
                "SELECT COUNT(*)::bigint AS n "
                "FROM get_listing_lead_event(NULL, %s, NULL, NULL) le "
                "JOIN vendor_listings vl ON vl.id = le.id "
                "WHERE vl.category = 'equipment'",
                (SPOT_CHECK_WINDOW_HOURS,),
            )
            equipment_dropped = cur.fetchone()["n"]

            # Rows the NEW predicate uniquely removes: non-equipment bulk_cluster cohorts.
            cur.execute(
                "SELECT COUNT(*)::bigint AS n "
                "FROM get_listing_lead_event(NULL, %s, NULL, NULL) le "
                "JOIN vendor_listings vl ON vl.id = le.id "
                "WHERE vl.category IS DISTINCT FROM 'equipment' "
                "AND vl.bulk_cluster = true",
                (SPOT_CHECK_WINDOW_HOURS,),
            )
            bulk_dropped = cur.fetchone()["n"]

            # What the gated function should return.
            cur.execute(
                "SELECT COUNT(*)::bigint AS n "
                "FROM get_listing_lead_event(NULL, %s, NULL, NULL) le "
                "JOIN vendor_listings vl ON vl.id = le.id "
                "WHERE vl.category IS DISTINCT FROM 'equipment' "
                "AND vl.bulk_cluster = false",
                (SPOT_CHECK_WINDOW_HOURS,),
            )
            with_both = cur.fetchone()["n"]

            cur.execute(
                "SELECT event_count, vendor_count FROM get_aggregate_activity(%s)",
                (SPOT_CHECK_WINDOW_HOURS,),
            )
            agg = cur.fetchone()
            gated_count = agg["event_count"]

        # Fail-if-deleted: drop the bulk predicate and gated_count jumps to raw-equipment.
        if gated_count != with_both:
            print(
                f"  VERIFY FAILED: get_aggregate_activity({SPOT_CHECK_WINDOW_HOURS}) "
                f"event_count = {gated_count}, expected {with_both} "
                f"(raw {raw_count} - equipment {equipment_dropped} - bulk {bulk_dropped})"
            )
            return 1

        # The bulk guard must have live teeth — else this assertion is inert.
        if bulk_dropped <= 0:
            print(
                f"  VERIFY FAILED: bulk_cluster guard removed {bulk_dropped} non-equipment "
                f"rows — expected > 0 (the predicate would be unexercised)"
            )
            return 1

        # Accounting identity — the three buckets partition the raw count.
        if with_both + bulk_dropped + equipment_dropped != raw_count:
            print(
                f"  VERIFY FAILED: accounting mismatch — gated {with_both} + bulk "
                f"{bulk_dropped} + equipment {equipment_dropped} != raw {raw_count}"
            )
            return 1

        print(
            f"  get_aggregate_activity({SPOT_CHECK_WINDOW_HOURS}): "
            f"{raw_count} raw -> {gated_count} gated "
            f"({bulk_dropped} bulk-cluster + {equipment_dropped} equipment dropped); "
            f"{agg['vendor_count']} vendor(s). Both guards live; bulk guard has teeth."
        )

    print("0058 applied + verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
