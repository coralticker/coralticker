"""Apply migration 0054 — CTK-195 finding #1: equipment denylist in the shared guard.

Adds the CTK-186 step-2 predicate (vl.category IS DISTINCT FROM 'equipment') to
f7_arrivals_dispositioned's base CTE, so the IG cover + the web week-feed count ONE
coral-only population. CREATE OR REPLACE (shape unchanged); get_f7_arrivals_guarded
inherits the exclusion (it selects FROM the base function).

Uses scrapers.common.db.get_conn per the CTK-061 single-statement path.

Verification:
  - f7_arrivals_dispositioned present after apply
  - EQUIPMENT-FREE: zero rows in f7_arrivals_dispositioned(168, [both]) whose listing
    is category='equipment' (the structural exclusion landed)
  - STRUCTURAL equality: get_f7_arrivals_guarded count == that count with the web
    feed's redundant equipment filter re-applied (proves the function already excludes
    equipment, so the surfaces reconcile structurally, not empirically)
  - consistency smoke: get_f7_arrivals_guarded count == select_f7_arrivals true_count
  - re-base report: how many equipment lead-events the pre-0054 population carried (the
    over-count the ratified 788 included) + the new coral-only count
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from scrapers.common.db import get_conn
from scrapers.tools import content_queries as cq

MIGRATION_PATH = (
    Path(__file__).resolve().parent.parent
    / "supabase"
    / "migrations"
    / "0054_f7_arrivals_guard_equipment_denylist.sql"
)

ARM = cq._F7_ARRIVAL_EVENT       # "just-listed"
RESTOCK = cq._F7_RESTOCK_EVENT   # "back-in-stock"
WINDOW_H = 168


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
            print(f"  applied in {(time.monotonic() - t0) * 1000.0:.0f} ms")

        with conn.cursor() as cur:
            cur.execute("SELECT proname FROM pg_proc WHERE proname = 'f7_arrivals_dispositioned'")
            if not cur.fetchone():
                print("  VERIFY FAILED: f7_arrivals_dispositioned missing after apply")
                return 1
        print("  present: f7_arrivals_dispositioned")

        # Equipment-free: no equipment row survives into the dispositioned population.
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT count(*) AS n
                FROM f7_arrivals_dispositioned(%s, %s) d
                JOIN vendor_listings vl ON vl.id = d.id
                WHERE vl.category = 'equipment'
                """,
                (WINDOW_H, [ARM, RESTOCK]),
            )
            leak = cur.fetchone()["n"]
        if leak:
            print(f"  VERIFY FAILED: {leak} equipment row(s) leaked into the guarded population")
            return 1
        print("  equipment-free: 0 equipment rows in f7_arrivals_dispositioned")

        # Structural equality — re-applying the web feed's equipment filter changes
        # nothing (the function already excludes equipment), so the surfaces reconcile
        # structurally. Also the consistency smoke vs the Python cover call site.
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) AS n FROM get_f7_arrivals_guarded(%s, %s)", (WINDOW_H, [ARM, RESTOCK]))
            guarded = cur.fetchone()["n"]
            cur.execute(
                """
                SELECT count(*) AS n
                FROM get_f7_arrivals_guarded(%s, %s) g
                JOIN vendor_listings vl ON vl.id = g.id
                WHERE vl.category IS DISTINCT FROM 'equipment'
                """,
                (WINDOW_H, [ARM, RESTOCK]),
            )
            guarded_redundant = cur.fetchone()["n"]
        if guarded != guarded_redundant:
            print(f"  VERIFY FAILED: redundant equipment filter changed the count {guarded} -> {guarded_redundant}")
            return 1
        print(f"  structural: get_f7_arrivals_guarded {guarded} == with-redundant-equipment-filter {guarded_redundant}")

        py_true_count = cq.select_f7_arrivals(conn, WINDOW_H)[0]
        if guarded != py_true_count:
            print(f"  VERIFY FAILED: get_f7_arrivals_guarded {guarded} != select_f7_arrivals {py_true_count}")
            return 1
        print(f"  consistency: get_f7_arrivals_guarded {guarded} == select_f7_arrivals {py_true_count}")

        # Re-base report — equipment lead-events the pre-0054 population carried (the
        # over-count the ratified 788 included).
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT count(*) AS n
                FROM get_listing_lead_event(NULL, %s, %s, NULL) le
                JOIN vendor_listings vl ON vl.id = le.id
                WHERE vl.category = 'equipment'
                """,
                (WINDOW_H, [ARM, RESTOCK]),
            )
            equip_leadevents = cur.fetchone()["n"]
        print(f"  re-base: {equip_leadevents} equipment lead-event(s) in-window (pre-0054 over-count); "
              f"coral-only guarded count now {guarded}")

    print("0054 applied + verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
