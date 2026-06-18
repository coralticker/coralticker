"""Apply migration 0046 — CTK-161: velocity auction double-gate + window anchor.

REVISES get_velocity_listings (0042), folding two changes into one DDL (0042 is the
unapplied head, so no 0047 is stacked on it):
  1. the auction double-gate — drops auction-format listings: an auction's OOS is its
     scheduled close (or bidding mechanics for end-time-less pseudo-auctions), not
     demand-driven speed, so it cannot carry a velocity claim. Resolves the
     /lead-backend-flagged INV-05 residual (0042 had EXEMPTED velocity). Mirrors the
     get_cross_vendor_carriers (0043) double-gate.
  2. a new returned column, prior_run_finished_at — the last successful scrape that
     completed before the first in-stock sighting. Doubles as the cold-start gate
     (replaces the old EXISTS, identical predicate) AND the render's lifespan anchor
     (window = first_oos_at - prior_run_finished_at).

DROP FUNCTION IF EXISTS + CREATE (NOT CREATE OR REPLACE): adding the column changes
the RETURNS TABLE type, which REPLACE cannot do. The DROP IF EXISTS makes apply
correct whether 0042's 14-column version is live (dropped, recreated at 15) or absent
(no-op drop). Re-runnable to the same end state. No live caller (the velocity render
is not built — the driver is pre-req-blocked on a /designer velocity frame), so
applying early is safe and there is no apply-pre-push sequencing gate.

Uses scrapers.common.db.get_conn per the CTK-061 single-statement path. Mirrors
apply_migration_0042.py shape.

Verification:
  - get_velocity_listings present in pg_proc after apply
  - callable + the per-row lifecycle invariant
    prior_run_finished_at < first_seen_at <= last_in_stock_at < first_oos_at holds
    across all returned rows (tightened from 0042 by the new anchor)
  - auction gate landed: no returned id is an auction row (auction_end_time IS NOT
    NULL OR is_auction = true) — checked by re-joining vendor_listings, since the
    function does not project the auction columns
  - GRANT is in the migration body; a missing GRANT surfaces on the first wrapper
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
    / "0046_velocity_gate_and_window_anchor.sql"
)

EXPECTED_FUNC = "get_velocity_listings"


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

        # Presence check.
        with conn.cursor() as cur:
            cur.execute(
                "SELECT proname FROM pg_proc WHERE proname = %s", (EXPECTED_FUNC,)
            )
            if not cur.fetchone():
                print(f"  VERIFY FAILED: {EXPECTED_FUNC} missing after apply")
                return 1
        print(f"  present: {EXPECTED_FUNC}")

        # Smoke — callable + lifecycle invariant across every returned row.
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM get_velocity_listings()")
            rows = cur.fetchall()
            violations = [
                r["id"]
                for r in rows
                if not (
                    r["prior_run_finished_at"] is not None
                    and r["first_seen_at"] is not None
                    and r["last_in_stock_at"] is not None
                    and r["first_oos_at"] is not None
                    and r["prior_run_finished_at"] < r["first_seen_at"]
                    and r["first_seen_at"] <= r["last_in_stock_at"] < r["first_oos_at"]
                )
            ]
            if violations:
                print(
                    f"  VERIFY FAILED: {len(violations)} row(s) violate "
                    f"prior_run_finished < first_seen <= last_in_stock < first_oos: "
                    f"ids {sorted(violations)}"
                )
                return 1
            print(f"  get_velocity_listings(): {len(rows)} gone listing(s), invariant holds")

        # Auction gate — no returned row is an auction (the function does not project
        # the auction columns, so re-join vendor_listings to assert the gate landed).
        if rows:
            ids = [r["id"] for r in rows]
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM vendor_listings "
                    "WHERE id = ANY(%s) "
                    "AND (auction_end_time IS NOT NULL OR is_auction = true)",
                    (ids,),
                )
                leaked = [r["id"] for r in cur.fetchall()]
            if leaked:
                print(
                    f"  VERIFY FAILED: {len(leaked)} auction row(s) crowned by "
                    f"velocity: ids {sorted(leaked)}"
                )
                return 1
            print(f"  auction gate: 0 auction rows in {len(rows)} crowned listing(s)")
        else:
            print("  auction gate: no rows to check (empty velocity set)")

    print("0046 applied + verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
