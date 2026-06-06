"""Apply migration 0033 — CTK-124: markdown_started_at column + cold-start
backfill + get_recent_price_drops(p_window_days integer) union RPC.

The one-arg union function lands ALONGSIDE the live zero-arg signature
(overload two-step per the migration header; 0028/0029 precedent). The
zero-arg function keeps serving /deals until the CTK-124 Session 2
frontend swap; migration 0034 drops it after a verify cycle.

Uses scrapers.common.db.get_conn per CTK-061 amendment-2 single-statement
path. Reads the .sql file from disk and executes it as a single batch
under the autocommit connection. Mirrors apply_migration_0028.py shape.

Idempotent: ADD COLUMN IF NOT EXISTS, IS NULL backfill guard, DROP IF
EXISTS scoped to the (integer) signature — re-running rebinds the union
function without resetting live onsets or touching the zero-arg overload.

Verification, per the CTK-124 Session 1 directive verify list:
  - column present (information_schema)
  - BOTH signatures present in pg_proc; one-arg projects event_at +
    compare_at_price, zero-arg untouched (still projects observed_at)
  - backfill landed (non-NULL onset count > 0)
  - live-row check spanning both arms: >= 1 LAG-window drop row +
    >= 1 markdown-only row (prior_price IS NULL) with seeded event_at
  - zero auction rows in the union output (INV-05 spot-check)
  - zero-arg smoke count (still serving)
"""

from __future__ import annotations

import sys
from pathlib import Path

from scrapers.common.db import get_conn

MIGRATION_PATH = Path(__file__).resolve().parent.parent / "supabase" / "migrations" / "0033_markdown_started_at_union_price_drops.sql"

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
        print("post-apply verification — column + pg_proc signatures")
        print("=" * 70)

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_name = 'vendor_listings'
                  AND column_name = 'markdown_started_at'
                """
            )
            col = cur.fetchall()
        if not col:
            print("  MISSING: vendor_listings.markdown_started_at not created")
            return 1
        print(f"  vendor_listings.markdown_started_at: {col[0]['data_type']} nullable={col[0]['is_nullable']}")

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT proname, pg_get_function_identity_arguments(oid) AS args,
                       pg_get_function_result(oid) AS result
                FROM pg_proc
                WHERE proname = 'get_recent_price_drops'
                  AND pronamespace = 'public'::regnamespace
                ORDER BY pronargs
                """
            )
            rows = cur.fetchall()
        sigs = {r["args"] for r in rows}
        for row in rows:
            print(f"  get_recent_price_drops({row['args']})")
        if "" not in sigs:
            print("  MISSING: zero-arg signature gone — 0033 must not touch it (live /deals caller)")
            return 1
        if "p_window_days integer" not in sigs:
            print("  MISSING: one-arg union signature not created")
            return 1
        one_arg = [r for r in rows if r["args"] == "p_window_days integer"][0]
        zero_arg = [r for r in rows if r["args"] == ""][0]
        if "event_at" not in one_arg["result"] or "compare_at_price" not in one_arg["result"]:
            print("  MISSING: one-arg result lacks event_at / compare_at_price")
            return 1
        if "observed_at" not in zero_arg["result"]:
            print("  CHANGED: zero-arg result no longer projects observed_at — overload isolation broken")
            return 1
        print("  signatures ok: one-arg projects event_at; zero-arg untouched")

        print()
        print("=" * 70)
        print("backfill + both-arms live-row check + INV-05 spot-check")
        print("=" * 70)

        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS c FROM vendor_listings WHERE markdown_started_at IS NOT NULL")
            seeded = cur.fetchone()["c"]
            cur.execute(
                "SELECT COUNT(*) AS total, "
                "       COUNT(*) FILTER (WHERE prior_price IS NOT NULL) AS drop_rows, "
                "       COUNT(*) FILTER (WHERE prior_price IS NULL) AS markdown_only_rows, "
                "       COUNT(*) FILTER (WHERE event_at IS NULL) AS null_event_at "
                "FROM get_recent_price_drops(%s)",
                (WINDOW_DAYS,),
            )
            union = cur.fetchone()
            # Drop-arm presence checked PRE-LIMIT via the arm's own
            # predicates. During the cold-start seed window every backfilled
            # onset shares the apply-moment timestamp and out-ranks all
            # historical drop events under ORDER BY event_at DESC LIMIT 250,
            # so the function output is legitimately markdown-only until the
            # seed cohort ages out (<= WINDOW_DAYS post-apply). The arm
            # itself must still have qualifying rows.
            cur.execute(
                "SELECT COUNT(*) AS c FROM ("
                "  SELECT ph.listing_id, ph.price AS new_price, "
                "         LAG(ph.price) OVER (PARTITION BY ph.listing_id ORDER BY ph.observed_at) AS prior_price, "
                "         ph.observed_at "
                "  FROM price_history ph"
                ") e "
                "JOIN vendor_listings vl ON vl.id = e.listing_id "
                "WHERE e.observed_at > now() - (%s * interval '1 day') "
                "  AND e.new_price IS NOT NULL AND e.prior_price IS NOT NULL "
                "  AND e.new_price < e.prior_price "
                "  AND vl.current_price IS NOT NULL "
                "  AND vl.in_stock = true AND vl.auction_end_time IS NULL",
                (WINDOW_DAYS,),
            )
            drop_arm_prelimit = cur.fetchone()["c"]
            cur.execute(
                "SELECT COUNT(*) AS c FROM get_recent_price_drops(%s) e "
                "JOIN vendor_listings vl ON vl.id = e.id "
                "WHERE vl.auction_end_time IS NOT NULL",
                (WINDOW_DAYS,),
            )
            auction_rows = cur.fetchone()["c"]
            cur.execute("SELECT COUNT(*) AS c FROM get_recent_price_drops()")
            zero_arg_count = cur.fetchone()["c"]

        print(f"  backfill: {seeded} rows carry markdown_started_at")
        print(f"  get_recent_price_drops({WINDOW_DAYS}): {union['total']} rows "
              f"({union['drop_rows']} drop-arm, {union['markdown_only_rows']} markdown-only, "
              f"{union['null_event_at']} NULL event_at)")
        print(f"  drop arm pre-LIMIT: {drop_arm_prelimit} qualifying event rows")
        print(f"  auction rows in union output: {auction_rows}")
        print(f"  get_recent_price_drops() zero-arg still serving: {zero_arg_count} rows")

        if seeded == 0:
            print("  MISSING: backfill seeded zero rows (probe said 1,785 markdown rows fleet-wide)")
            return 1
        if drop_arm_prelimit == 0:
            print("  MISSING: no LAG-window drop rows qualify pre-LIMIT (arm broken)")
            return 1
        if union["markdown_only_rows"] == 0:
            print("  MISSING: no markdown-only rows in union output")
            return 1
        if union["null_event_at"] > 0:
            print("  DEFECT: union rows with NULL event_at — both arms must carry an honest timestamp")
            return 1
        if auction_rows > 0:
            print("  DEFECT: auction rows leaked into union output (INV-05 violation)")
            return 1

        print()
        print("all checks passed")

    return 0


if __name__ == "__main__":
    sys.exit(main())
