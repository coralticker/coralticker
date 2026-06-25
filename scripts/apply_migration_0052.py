"""Apply migration 0052 — CTK-195 D-1: the shared guarded F7-arrivals SQL source.

Creates f7_arrivals_dispositioned + get_f7_arrivals_guarded (both new names — no
DROP, zero blast radius on the live get_listing_lead_event). Re-asserts GRANTs to
migration 0039's grantee set. Re-runnable only after a manual DROP (CREATE, not
CREATE OR REPLACE) — a second apply errors on the existing function, which is the
intended loud signal that the function already exists.

Uses scrapers.common.db.get_conn per the CTK-061 single-statement path. Mirrors
apply_migration_0046.py shape.

Verification:
  - both functions present in pg_proc after apply
  - get_f7_arrivals_guarded(168, ['just-listed','back-in-stock']) count vs the
    ratified 788
  - CONSISTENCY SMOKE (crash + agreement): SQL guarded count == cq.select_f7_arrivals
    true_count. NOTE: this was a true faithful-port gate ONLY at the original apply,
    when select_f7_arrivals still computed the guard in Python — equality then proved
    the SQL port reproduced the Python computation. Post-swap select_f7_arrivals
    consumes the SQL function, so re-running this is SQL-vs-SQL (tautological): it
    catches a crash / a broken call site, not a port-fidelity regression. The
    one-time port-fidelity proof was the transient pre-swap differential
    (count_new_arrivals 718 == sql 718; select_f7_arrivals 749 == sql 749), recorded
    in CTK-195/results.md — not reproducible from this script post-merge. (The bare
    788 also drifts with live data; neither is a frozen number.)
  - disposition spot-check: Cornbred (cold-start onboarding backfill) tags
    cold_start; POTO (2026-06-21 re-index) tags bulk_relist.
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
    / "0052_f7_arrivals_guarded_function.sql"
)

EXPECTED_FUNCS = ("f7_arrivals_dispositioned", "get_f7_arrivals_guarded")
RATIFIED_788 = 788
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

        # Presence.
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

        # Acceptance #1 — guarded count vs ratified 788.
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) AS n FROM get_f7_arrivals_guarded(%s, %s)",
                (WINDOW_H, [ARM, RESTOCK]),
            )
            sql_count = cur.fetchone()["n"]
        flag = "" if sql_count == RATIFIED_788 else f"  (ratified {RATIFIED_788}; live data moved)"
        print(f"  get_f7_arrivals_guarded(168, [just-listed,back-in-stock]) = {sql_count}{flag}")

        # CONSISTENCY SMOKE — SQL guarded count == cq.select_f7_arrivals true_count.
        # This was a faithful-port gate at the ORIGINAL apply (select_f7_arrivals still
        # computed the guard in Python then); post-swap it consumes the SQL function, so
        # this is SQL-vs-SQL — it catches a crash / broken call site, NOT a port-fidelity
        # regression. The one-time port proof was the transient pre-swap differential
        # (718==718, 749==749), recorded in CTK-195/results.md.
        py_count = cq.select_f7_arrivals(conn)[0]
        if sql_count != py_count:
            print(
                f"  VERIFY FAILED: SQL guarded count {sql_count} != select_f7_arrivals "
                f"count {py_count} — crash or broken call site."
            )
            return 1
        print(f"  consistency smoke: SQL {sql_count} == select_f7_arrivals {py_count}")

        # Disposition spot-check — Cornbred cold_start, POTO bulk_relist.
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT vendor_slug, guard_disposition, count(*) AS n
                FROM f7_arrivals_dispositioned(%s, %s)
                WHERE vendor_slug IN ('cornbred', 'poto')
                GROUP BY vendor_slug, guard_disposition
                ORDER BY vendor_slug, guard_disposition
                """,
                (WINDOW_H, [ARM, RESTOCK]),
            )
            spot = {(r["vendor_slug"], r["guard_disposition"]): r["n"] for r in cur.fetchall()}
        for row, disp in (("cornbred", "cold_start"), ("poto", "bulk_relist")):
            n = spot.get((row, disp), 0)
            tag = "ok" if n > 0 else "MISSING"
            print(f"  spot-check: {row} {disp} = {n}  [{tag}]")
        if spot.get(("cornbred", "cold_start"), 0) == 0 or spot.get(("poto", "bulk_relist"), 0) == 0:
            print("  VERIFY FAILED: expected cohort disposition tags absent.")
            return 1

    print("0052 applied + verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
