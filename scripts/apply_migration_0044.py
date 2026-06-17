"""Apply migration 0044 — CTK-161 F9: get_cross_vendor_carriers() ORDER BY tiebreak.

CREATE OR REPLACE on the 0043 function with a `vl.id DESC` final tiebreak, so the
carrier order is a total order (retro /code-review finding #2, 2026-06-17). No
column-shape / WHERE / GRANT change — only the ORDER BY tail.

CREATE OR REPLACE FUNCTION — idempotent, re-runnable, no DROP, no table writes.
Mirrors apply_migration_0043.py shape.

Verification:
  - get_cross_vendor_carriers present in pg_proc after apply
  - callable + the two return-visible predicates hold per row
  - the ORDER BY is a total order: assert no two consecutive rows share
    (named_coral_id, first_seen_at) — i.e. the id tiebreak actually disambiguates.
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
    / "0044_get_cross_vendor_carriers_tiebreak.sql"
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

        # Smoke — callable + predicates + total-order proof.
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
            # Total-order proof: no adjacent pair shares (named_coral_id, event_at)
            # without the id tiebreak separating them — the returned order is stable.
            ambiguous = [
                rows[i]["id"]
                for i in range(1, len(rows))
                if rows[i]["named_coral_id"] == rows[i - 1]["named_coral_id"]
                and rows[i]["event_at"] == rows[i - 1]["event_at"]
                and not (rows[i]["id"] < rows[i - 1]["id"])  # must be strictly descending on the tie
            ]
            if ambiguous:
                print(
                    f"  VERIFY FAILED: {len(ambiguous)} tie(s) not id-DESC ordered: ids {sorted(ambiguous)}"
                )
                return 1
            vendors = len({r["vendor_id"] for r in rows})
            print(
                f"  get_cross_vendor_carriers(): {len(rows)} carrier row(s) across "
                f"{vendors} vendor(s); predicates hold; ties id-DESC ordered"
            )

    print("0044 applied + verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
