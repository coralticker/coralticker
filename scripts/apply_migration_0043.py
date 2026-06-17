"""Apply migration 0043 — CTK-161 F9: get_cross_vendor_carriers().

Creates one STABLE Postgres function (sibling to get_cross_vendor_cheapest in
0041, but never price-ranked — F9 inners are recency-ordered):
  - get_cross_vendor_carriers()   every in-stock, non-auction, matched carrying
                                  listing of every named coral, with the 'listed'
                                  event time (first_seen_at) the F9 render orders on.

CREATE OR REPLACE FUNCTION — idempotent, re-runnable, no DROP, no table writes.
Net-new surface; select_f9_lineage is the first (and only) caller, and the F9
content-card driver (scrapers/tools/content_cards.py) is GATED on this apply:
until 0043 lands on prod Neon the F9 path raises UndefinedFunction (42883).

CRON-WINDOW RACE (migration-state hazard): apply this BEFORE deploying / scheduling
any content-card run that includes F9. F7/F8 do not depend on 0043.

Uses scrapers.common.db.get_conn per the CTK-061 single-statement path. Mirrors
apply_migration_0042.py shape.

Verification:
  - get_cross_vendor_carriers present in pg_proc after apply
  - callable + column shape (smoke SELECT), and the two return-visible predicates
    hold across every row (named_coral_id IS NOT NULL AND in_stock IS true) — a
    cheap proof the WHERE guard is intact. (The auction gates filter rows OUT, so
    they are not re-verifiable from the returned columns.)
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
    / "0043_get_cross_vendor_carriers.sql"
)

EXPECTED_FUNC = "get_cross_vendor_carriers"


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

        # Smoke — callable + the two return-visible WHERE predicates hold per row.
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM get_cross_vendor_carriers()")
            rows = cur.fetchall()
            violations = [
                r["id"]
                for r in rows
                if not (r["named_coral_id"] is not None and r["in_stock"] is True)
            ]
            if violations:
                print(
                    f"  VERIFY FAILED: {len(violations)} row(s) violate "
                    f"named_coral_id NOT NULL AND in_stock: ids {sorted(violations)}"
                )
                return 1
            vendors = len({r["vendor_id"] for r in rows})
            print(f"  get_cross_vendor_carriers(): {len(rows)} carrier row(s) across {vendors} vendor(s), predicates hold")

    print("0043 applied + verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
