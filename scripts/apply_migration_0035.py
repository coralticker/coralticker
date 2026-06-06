"""Apply migration 0035 — CTK-124 Session 3b: get_recent_price_drops(integer)
body revision (ORDER BY tiebreak + LIMIT removal + markdown-arm 5% floor).

SEQUENCING GATE — run this only AFTER the frontend view-layer cap is
deployed (inverted from apply-pre-push; see the migration header).
Applying against a cap-less frontend uncaps /deals at ~1,794 rows for
the gap.

Uses scrapers.common.db.get_conn per CTK-061 amendment-2 single-statement
path. Mirrors apply_migration_0033.py shape.

Idempotent: CREATE OR REPLACE; re-running rebinds the same body.

Verification, per the Session 3b directive verify list:
  - signature + RETURNS unchanged; body carries the three changes
    (pg_get_functiondef: no LIMIT, '1.05' floor, listing_id tiebreak)
  - tiebreak determinism: two consecutive calls return the identical
    id sequence
  - floor boundary: no markdown-only output row sits below the 5% floor
    (the exactly-5%/4.9% boundary pin lives in
    scrapers/tests/test_price_drops_rpc_floor.py — run it post-apply)
  - arm-spanning live check: both arms present in output (no LIMIT now,
    so the seed cohort no longer truncates the drop arm out)
  - INV-05 spot-check: zero auction rows
  - EXECUTE grantees intact on the (integer) signature
"""

from __future__ import annotations

import sys
from pathlib import Path

from scrapers.common.db import get_conn

MIGRATION_PATH = Path(__file__).resolve().parent.parent / "supabase" / "migrations" / "0035_price_drops_tiebreak_uncap_floor.sql"

WINDOW_DAYS = 7  # smoke value — mirrors DEALS_WINDOW_DAYS (D-1, Jon-ratified 2026-06-04)


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
        print("post-apply verification — signature + body markers")
        print("=" * 70)

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT pg_get_function_identity_arguments(oid) AS args,
                       pg_get_functiondef(oid) AS body
                FROM pg_proc
                WHERE proname = 'get_recent_price_drops'
                  AND pronamespace = 'public'::regnamespace
                """
            )
            rows = cur.fetchall()
        if len(rows) != 1 or rows[0]["args"] != "p_window_days integer":
            print(f"  DEFECT: expected exactly the one-arg signature, got {[r['args'] for r in rows]}")
            return 1
        body = rows[0]["body"]
        if "LIMIT" in body.upper():
            print("  DEFECT: body still carries a LIMIT (change (b) missing)")
            return 1
        if "1.05" not in body:
            print("  DEFECT: body lacks the 5% floor (change (c) missing)")
            return 1
        if "listing_id" not in body.split("ORDER BY r.event_at DESC,")[-1][:30]:
            print("  DEFECT: final ORDER BY lacks the listing_id tiebreak (change (a) missing)")
            return 1
        print("  signature unchanged; body carries tiebreak + uncap + floor")

        print()
        print("=" * 70)
        print("tiebreak determinism — two consecutive calls, id sequences")
        print("=" * 70)
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM get_recent_price_drops(%s)", (WINDOW_DAYS,))
            seq_a = [r["id"] for r in cur.fetchall()]
            cur.execute("SELECT id FROM get_recent_price_drops(%s)", (WINDOW_DAYS,))
            seq_b = [r["id"] for r in cur.fetchall()]
        print(f"  call 1: {len(seq_a)} rows; call 2: {len(seq_b)} rows")
        if seq_a != seq_b:
            first_div = next((i for i, (a, b) in enumerate(zip(seq_a, seq_b)) if a != b), min(len(seq_a), len(seq_b)))
            print(f"  DEFECT: id sequences diverge at position {first_div}")
            return 1
        print("  identical id sequences — total order holds")

        print()
        print("=" * 70)
        print("arms + floor + INV-05 + grants")
        print("=" * 70)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS total, "
                "       COUNT(*) FILTER (WHERE prior_price IS NOT NULL) AS drop_rows, "
                "       COUNT(*) FILTER (WHERE prior_price IS NULL) AS markdown_only_rows, "
                "       COUNT(*) FILTER (WHERE prior_price IS NULL "
                "                        AND compare_at_price < current_price * 1.05) AS sub_floor_rows "
                "FROM get_recent_price_drops(%s)",
                (WINDOW_DAYS,),
            )
            union = cur.fetchone()
            cur.execute(
                "SELECT COUNT(*) AS c FROM get_recent_price_drops(%s) e "
                "JOIN vendor_listings vl ON vl.id = e.id "
                "WHERE vl.auction_end_time IS NOT NULL",
                (WINDOW_DAYS,),
            )
            auction_rows = cur.fetchone()["c"]
            # Per-signature grant check (overload-two-step template — see
            # apply_migration_0034.py).
            cur.execute(
                """
                SELECT grantee
                FROM information_schema.routine_privileges
                WHERE specific_name = (
                    SELECT proname || '_' || oid::text
                    FROM pg_proc
                    WHERE proname = 'get_recent_price_drops'
                      AND pronamespace = 'public'::regnamespace
                      AND pg_get_function_identity_arguments(oid) = 'p_window_days integer'
                )
                  AND privilege_type = 'EXECUTE'
                """
            )
            grantees = sorted({r["grantee"] for r in cur.fetchall()})

        print(f"  get_recent_price_drops({WINDOW_DAYS}): {union['total']} rows "
              f"({union['drop_rows']} drop-arm, {union['markdown_only_rows']} markdown-only)")
        print(f"  markdown-only rows below the 5% floor: {union['sub_floor_rows']}")
        print(f"  auction rows in output: {auction_rows}")
        print(f"  EXECUTE grantees on (integer): {grantees}")

        if union["drop_rows"] == 0:
            print("  MISSING: no drop-arm rows in output (uncapped output should span arms)")
            return 1
        if union["markdown_only_rows"] == 0:
            print("  MISSING: no markdown-only rows in output")
            return 1
        if union["sub_floor_rows"] > 0:
            print("  DEFECT: sub-floor markdown rows leaked past change (c)")
            return 1
        if auction_rows > 0:
            print("  DEFECT: auction rows leaked (INV-05 violation)")
            return 1
        if not grantees:
            print("  MISSING: no EXECUTE grants on the (integer) signature")
            return 1

        print()
        print("all checks passed — run test_price_drops_rpc_floor.py for the boundary pin")

    return 0


if __name__ == "__main__":
    sys.exit(main())
