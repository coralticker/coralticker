"""CTK-191 verify — the F7 arrivals honest-count guard against live data.

Read-only. Establishes the corrected cover count and attributes the gap from the
raw (unguarded) population to a named cause:
  - COLD-START backfill — a newly-onboarded vendor's whole catalog first-seen on its
    onboarding day (no successful run finished before first_seen). Catches Cornbred.
  - BULK RE-INDEX — a vendor WITH prior runs dumping a single-day cohort over
    max(ABS_FLOOR, K x trailing-median). Catches POTO.

CTK-195: the guard is the shared SQL source now (migration 0052). This script reads
f7_arrivals_dispositioned — every row carries its guard_disposition tag
('kept'|'cold_start'|'bulk_relist') + the bulk threshold/median — so the matrix and
the corrected count come straight off the function, no parallel Python computation.
Prints the (vendor x calendar-day) just-listed matrix with each cohort's tag, then the
guarded true_count + count-up N vs the raw population. The corrected count is the
figure Jon eyeballs before any reel re-render/push (the live count rolls with the 168h
window; 788 on 2026-06-24 -> drifts since — the shape, not the absolute, is the read).

Run:  python scripts/ctk191_verify_f7_guard.py
"""

from __future__ import annotations

from scrapers.common.db import get_conn
from scrapers.tools import content_queries as cq

_ARM = cq._F7_ARRIVAL_EVENT       # "just-listed"
_RESTOCK = cq._F7_RESTOCK_EVENT   # "back-in-stock"
WINDOW_H = 168


def main() -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            # The disposition-tagged base — the single guarded source (migration 0052).
            cur.execute(
                "SELECT * FROM f7_arrivals_dispositioned(%s, %s)",
                (WINDOW_H, [_ARM, _RESTOCK]),
            )
            rows = cur.fetchall()

        arr = [r for r in rows if r["event"] == _ARM]
        res = [r for r in rows if r["event"] == _RESTOCK]
        kept = [r for r in rows if r["guard_disposition"] == "kept"]
        cold = [r for r in arr if r["guard_disposition"] == "cold_start"]
        bulk = [r for r in arr if r["guard_disposition"] == "bulk_relist"]

        print(f"=== RAW {WINDOW_H}h lead-event population (pre-guard) ===")
        print(f"  total={len(rows)}  just-listed={len(arr)}  back-in-stock={len(res)}")

        # Per (vendor, day) just-listed matrix, tagged by the function's disposition.
        slugs = {r["vendor_id"]: r["vendor_slug"] for r in rows}
        cohorts: dict = {}
        for r in arr:
            cohorts.setdefault((r["vendor_id"], cq._arrival_day(r)), []).append(r)

        def _verdict(group):
            tags = {r["guard_disposition"] for r in group}
            if tags == {"cold_start"}:
                return "COLD-START"
            if "bulk_relist" in tags:
                ex = next(r for r in group if r["guard_disposition"] == "bulk_relist")
                return f"RE-INDEX (>{ex['bulk_threshold']:.0f}, med={ex['bulk_median']:.1f})"
            return "ok"

        print(f"\n=== just-listed (vendor x calendar-day) matrix — {len(cohorts)} cohorts ===")
        for key, group in sorted(cohorts.items(), key=lambda kv: -len(kv[1])):
            vid, day = key
            print(f"  {slugs.get(vid, vid):<22} {str(day):<12} {len(group):>5}   {_verdict(group)}")

        # Bulk cohorts (the function's bulk_relist tags), grouped for the operator view.
        bulk_cohorts: dict = {}
        for r in bulk:
            k = (r["vendor_id"], cq._arrival_day(r))
            bulk_cohorts.setdefault(k, 0)
            bulk_cohorts[k] += 1
        cold_by_vendor: dict = {}
        for r in cold:
            cold_by_vendor[r["vendor_id"]] = cold_by_vendor.get(r["vendor_id"], 0) + 1

        # The guarded outcome (the production path both call-sites take).
        true_count, composition, items = cq.select_f7_arrivals(conn)
        count_n = cq.count_new_arrivals(conn)

        print("\n=== GUARD OUTCOME ===")
        print(f"  cold-start dropped : {len(cold)}  {dict(sorted(cold_by_vendor.items()))}")
        print(f"  re-index cohorts   : {len(bulk_cohorts)}")
        for key, n in sorted(bulk_cohorts.items(), key=lambda kv: -kv[1]):
            vid, day = key
            print(f"    - {slugs.get(vid, vid):<20} {str(day):<12} {n} dropped")
        print(f"\n  RAW population (pre-guard)            : {len(rows)}")
        print(f"  GUARDED true_count (cover headline)   : {true_count}   composition={composition}")
        print(f"  GUARDED count_new_arrivals (count-up N): {count_n}")
        print(f"  surviving just-listed                 : {sum(1 for r in kept if r['event'] == _ARM)}   (raw just-listed {len(arr)})")
        print(f"  surviving back-in-stock (passthrough) : {len(res)}")
        print(f"  sample items rendered                 : {len(items)} (cap 9)")

    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
