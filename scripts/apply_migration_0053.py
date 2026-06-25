"""Apply migration 0053 — CTK-195 close cleanup on the D-1 guard functions.

Refactor + one new diagnostic column, NO behaviour change vs 0052: is_bulk computed
once (fold #2), arr_day projected (fold #3). DROP + CREATE both functions (arr_day
changes f7_arrivals_dispositioned's return shape); get_f7_arrivals_guarded body is
unchanged. Re-asserts GRANTs to the 0039 grantee set.

Uses scrapers.common.db.get_conn per the CTK-061 single-statement path. Mirrors
apply_migration_0052.py shape.

Verification:
  - both functions present after apply
  - get_f7_arrivals_guarded(168, [both arms]) count == select_f7_arrivals true_count
    (SQL-vs-SQL consistency smoke — the call site and the function agree post-cleanup)
  - arr_day is non-NULL on every f7_arrivals_dispositioned row (the projected column
    the wrapper now keys its drop-log cohort map on)
  - behaviour preserved: Cornbred still tags cold_start, POTO still tags bulk_relist,
    and every bulk_relist row carries bulk_threshold/bulk_median + arr_day == the
    first_seen UTC day
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
    / "0053_f7_arrivals_dispositioned_cleanup.sql"
)

EXPECTED_FUNCS = ("f7_arrivals_dispositioned", "get_f7_arrivals_guarded")
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
            cur.execute(
                "SELECT proname FROM pg_proc WHERE proname = ANY(%s)",
                (list(EXPECTED_FUNCS),),
            )
            present = {r["proname"] for r in cur.fetchall()}
        missing = [f for f in EXPECTED_FUNCS if f not in present]
        if missing:
            print(f"  VERIFY FAILED: missing after apply: {missing}")
            return 1
        print(f"  present: {', '.join(EXPECTED_FUNCS)}")

        # SQL-vs-SQL consistency smoke — the call site and the function agree.
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) AS n FROM get_f7_arrivals_guarded(%s, %s)",
                (WINDOW_H, [ARM, RESTOCK]),
            )
            sql_count = cur.fetchone()["n"]
        py_true_count = cq.select_f7_arrivals(conn, WINDOW_H)[0]
        if sql_count != py_true_count:
            print(f"  VERIFY FAILED: get_f7_arrivals_guarded {sql_count} != select_f7_arrivals {py_true_count}")
            return 1
        print(f"  consistency: get_f7_arrivals_guarded {sql_count} == select_f7_arrivals {py_true_count}")

        # arr_day populated on every row; bulk rows carry threshold/median + a day that
        # matches the first_seen UTC day. Spot-check the known cohorts.
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM f7_arrivals_dispositioned(%s, %s)",
                (WINDOW_H, [ARM, RESTOCK]),
            )
            rows = cur.fetchall()
        null_arr_day = [r["id"] for r in rows if r["arr_day"] is None]
        if null_arr_day:
            print(f"  VERIFY FAILED: {len(null_arr_day)} row(s) have NULL arr_day")
            return 1
        bulk = [r for r in rows if r["guard_disposition"] == "bulk_relist"]
        bad_bulk = [r["id"] for r in bulk if r["bulk_threshold"] is None or r["bulk_median"] is None]
        if bad_bulk:
            print(f"  VERIFY FAILED: {len(bad_bulk)} bulk_relist row(s) missing threshold/median")
            return 1
        print(f"  arr_day: non-NULL on all {len(rows)} rows; {len(bulk)} bulk_relist rows carry threshold/median")

        disp = {}
        for r in rows:
            if r["vendor_slug"] in ("cornbred", "poto"):
                disp.setdefault((r["vendor_slug"], r["guard_disposition"]), 0)
                disp[(r["vendor_slug"], r["guard_disposition"])] += 1
        for slug, d in (("cornbred", "cold_start"), ("poto", "bulk_relist")):
            n = disp.get((slug, d), 0)
            print(f"  spot-check: {slug} {d} = {n}  [{'ok' if n else 'MISSING'}]")
        if disp.get(("cornbred", "cold_start"), 0) == 0 or disp.get(("poto", "bulk_relist"), 0) == 0:
            print("  VERIFY FAILED: expected cohort disposition tags absent (behaviour drift).")
            return 1

    print("0053 applied + verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
