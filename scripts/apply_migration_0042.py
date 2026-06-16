"""Apply migration 0042 — CTK-161: velocity (listed-and-gone) query.

Creates one STABLE Postgres function (the fifth content-engine function, after
velocity cleared publish-now-safe 2026-06-16):
  - get_velocity_listings(int)   still-OOS matched listings whose first lifecycle
                                 we observed, with the three raw timestamps the
                                 render derives its window from.

CREATE OR REPLACE FUNCTION — idempotent, re-runnable, no DROP. No table writes,
no return-type widen, so no apply-pre-push sequencing gate: net-new surface with
no live caller until the CTK-164 velocity render ships. Applying early is safe.

Uses scrapers.common.db.get_conn per the CTK-061 single-statement path. Mirrors
apply_migration_0041.py shape.

Verification:
  - get_velocity_listings present in pg_proc after apply
  - callable + column shape (smoke SELECT), and the per-row lifecycle invariant
    first_seen_at <= last_in_stock_at < first_oos_at holds across all returned rows
    (the claim-honesty guarantee — a violation would mean a malformed lifespan)
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
    / "0042_velocity_listings.sql"
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
                    r["first_seen_at"] is not None
                    and r["last_in_stock_at"] is not None
                    and r["first_oos_at"] is not None
                    and r["first_seen_at"] <= r["last_in_stock_at"] < r["first_oos_at"]
                )
            ]
            if violations:
                print(
                    f"  VERIFY FAILED: {len(violations)} row(s) violate "
                    f"first_seen <= last_in_stock < first_oos: ids {sorted(violations)}"
                )
                return 1
            print(f"  get_velocity_listings(): {len(rows)} gone listing(s), invariant holds")

    print("0042 applied + verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
