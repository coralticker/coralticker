"""CTK-191 verify — the F7 arrivals honest-count guard against live data.

Read-only. Establishes the corrected cover count and attributes the gap from the
raw (unguarded) population to a named cause:
  - COLD-START backfill — a newly-onboarded vendor's whole catalog first-seen on its
    onboarding day (no successful run finished before first_seen). Catches Cornbred.
  - BULK RE-INDEX — a vendor WITH prior runs dumping a single-day cohort over
    max(ABS_FLOOR, K x trailing-median). Catches POTO.

Prints the (vendor x calendar-day) just-listed matrix with each cohort tagged
COLD-START / RE-INDEX / ok, then the guarded true_count + count-up N vs the raw
2080 the cover rendered 2026-06-24. The corrected count is the figure Jon eyeballs
before any reel re-render/push.

Run:  python scripts/ctk191_verify_f7_guard.py
"""

from __future__ import annotations

from scrapers.common.db import get_conn
from scrapers.tools import content_queries as cq

_ARM = cq._F7_ARRIVAL_EVENT       # "just-listed"
_RESTOCK = cq._F7_RESTOCK_EVENT   # "back-in-stock"
WINDOW_H = 168


def _rows(cur, sql, params=None):
    cur.execute(sql, params or ())
    return cur.fetchall()


def main() -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            # Raw (unguarded) lead-event population — the basis the cover counted.
            raw = _rows(
                cur,
                "SELECT * FROM get_listing_lead_event(%s, %s, %s, %s)",
                (None, WINDOW_H, [_ARM, _RESTOCK], None),
            )
            raw_arr = [r for r in raw if r["event"] == _ARM]
            raw_res = [r for r in raw if r["event"] == _RESTOCK]
            print(f"=== RAW {WINDOW_H}h lead-event population (unguarded) ===")
            print(f"  total={len(raw)}  just-listed={len(raw_arr)}  back-in-stock={len(raw_res)}")

            # Per (vendor, day) just-listed matrix, with the guard's verdict per cohort.
            anchors = cq.fetch_arrival_anchors(conn, [r["id"] for r in raw_arr])
            warm = [r for r in raw_arr if anchors.get(r["id"]) is not None]
            cold = [r for r in raw_arr if anchors.get(r["id"]) is None]
            medians = {v: cq._median(c) for v, c in cq.fetch_trailing_daily_arrivals(conn).items()}
            excluded = cq._bulk_spike_excluded_cohorts(warm, medians)

            # Vendor slug lookup for legible output.
            slugs = {r["vendor_id"]: r["vendor_slug"] for r in raw}
            cold_by_vendor: dict = {}
            for r in cold:
                cold_by_vendor[r["vendor_id"]] = cold_by_vendor.get(r["vendor_id"], 0) + 1

            # Full cohort matrix (warm cohorts by size + the cold-start vendors).
            cohorts: dict = {}
            for r in raw_arr:
                cohorts.setdefault((r["vendor_id"], cq._arrival_day(r)), []).append(r)

            def _verdict(key, group):
                vid, _day = key
                n_cold = sum(1 for r in group if anchors.get(r["id"]) is None)
                if n_cold == len(group):
                    return "COLD-START"
                if key in excluded:
                    info = excluded[key]
                    return f"RE-INDEX (>{info['threshold']:.0f}, med={info['median']:.1f})"
                return "ok"

            print(f"\n=== just-listed (vendor x calendar-day) matrix — {len(cohorts)} cohorts ===")
            for key, group in sorted(cohorts.items(), key=lambda kv: -len(kv[1])):
                vid, day = key
                print(f"  {slugs.get(vid, vid):<22} {str(day):<12} {len(group):>5}   {_verdict(key, group)}")

            # The guarded outcome (the production path both call-sites take).
            report = cq._guard_arrivals(conn, raw, WINDOW_H)
            guarded_arr = sum(1 for r in report.kept if r["event"] == _ARM)
            true_count, composition, items = cq.select_f7_arrivals(conn)
            count_n = cq.count_new_arrivals(conn)

            print("\n=== GUARD OUTCOME ===")
            print(f"  cold-start dropped : {len(cold)}  {dict(sorted(cold_by_vendor.items()))}")
            print(f"  re-index cohorts   : {len(excluded)}")
            for key, info in sorted(excluded.items(), key=lambda kv: -kv[1]["count"]):
                vid, day = key
                print(f"    - {slugs.get(vid, vid):<20} {str(day):<12} {info['count']} dropped")
            print(f"\n  RAW cover count (the live 2080 shape) : {len(raw)}")
            print(f"  GUARDED true_count (cover headline)   : {true_count}   composition={composition}")
            print(f"  GUARDED count_new_arrivals (count-up N): {count_n}")
            print(f"  surviving just-listed                 : {guarded_arr}   (raw just-listed {len(raw_arr)})")
            print(f"  surviving back-in-stock (passthrough) : {len(raw_res)}")
            print(f"  sample items rendered                 : {len(items)} (cap 9)")

    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
