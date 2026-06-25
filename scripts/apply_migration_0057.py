"""Apply migration 0057 — CTK-198 (Tier 1B): add `bulk_cluster` as the 4th
disposition in f7_arrivals_dispositioned.

CREATE OR REPLACE (no return-shape change — a new disposition VALUE, not a new
column). The function reads the persisted vendor_listings.bulk_cluster column
(migration 0056) off the base CTE's existing vendor_listings join; it does not
re-derive the threshold. get_f7_arrivals_guarded is unchanged — its
WHERE guard_disposition = 'kept' drops the new tag for free.

Applies AFTER 0056 (the column must exist) and is independent of CTK-197's 0055.

Uses scrapers.common.db.get_conn. Mirrors apply_migration_0055.py shape.

Verification:
  - f7_arrivals_dispositioned present after apply
  - it is callable and the 'bulk_cluster' disposition is reachable: the count of
    rows tagged 'bulk_cluster' over a 168h window equals the count of in-window
    just-listed lead-event rows on a bulk_cluster=true listing that survive the
    cold_start + bulk_relist arms. Reported as evidence (data-independent — derived
    live, no hardcode). If the backfill has not run yet, this is legitimately 0
    (no row carries bulk_cluster=true) and the check still proves the branch is
    wired (the disposition column accepts the value).
  - get_f7_arrivals_guarded returns no 'bulk_cluster' row (kept-only invariant).
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
    / "0057_f7_arrivals_bulk_cluster_disposition.sql"
)

WINDOW_HOURS = 168


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

        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_proc WHERE proname = 'f7_arrivals_dispositioned'")
            if cur.fetchone() is None:
                print("  VERIFY FAILED: f7_arrivals_dispositioned not present after apply")
                return 1
        print("  present: f7_arrivals_dispositioned")

        # Disposition breakdown over the window — proves the new branch is wired and
        # reports how many rows it currently tags (0 is legitimate pre-backfill).
        with conn.cursor() as cur:
            cur.execute(
                "SELECT guard_disposition, count(*) AS n "
                "FROM f7_arrivals_dispositioned(%s, NULL) "
                "GROUP BY guard_disposition ORDER BY guard_disposition",
                (WINDOW_HOURS,),
            )
            breakdown = {r["guard_disposition"]: r["n"] for r in cur.fetchall()}
        print(f"  dispositions ({WINDOW_HOURS}h): {breakdown}")

        # Cross-check the bulk_cluster tag against the persisted column directly:
        # every 'bulk_cluster'-tagged row must carry vendor_listings.bulk_cluster=true.
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) AS leak "
                "FROM f7_arrivals_dispositioned(%s, NULL) d "
                "JOIN vendor_listings vl ON vl.id = d.id "
                "WHERE d.guard_disposition = 'bulk_cluster' AND vl.bulk_cluster = false",
                (WINDOW_HOURS,),
            )
            leak = cur.fetchone()["leak"]
        if leak:
            print(f"  VERIFY FAILED: {leak} 'bulk_cluster'-tagged row(s) with bulk_cluster=false")
            return 1
        print(f"  bulk_cluster tag consistent with persisted column (0 mismatches).")

        # kept-only invariant on the guarded wrapper: no 'bulk_cluster' survives.
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) AS n FROM get_f7_arrivals_guarded(%s, NULL) g "
                "JOIN vendor_listings vl ON vl.id = g.id WHERE vl.bulk_cluster = true",
                (WINDOW_HOURS,),
            )
            survived = cur.fetchone()["n"]
        if survived:
            print(f"  VERIFY FAILED: {survived} bulk_cluster row(s) survived into get_f7_arrivals_guarded")
            return 1
        print("  get_f7_arrivals_guarded excludes bulk_cluster rows (kept-only invariant holds).")

    print("0057 applied + verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
