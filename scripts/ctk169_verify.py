"""CTK-169 — point-in-time C2 reconciliation EVIDENCE (not a regression guard).

Captured 2026-06-17 to prove /new?window=week reconciles to the F7 IG cover
count at close: rendered week count == F7 true_count (936==936), matched +
unmatched both present, uncapped. This script RECONSTRUCTS the week-branch SQL
(get_listing_lead_event(NULL, 168, ['just-listed','back-in-stock'], NULL),
uncapped) — it does NOT import or exercise getRecentArrivals, so it will not
catch a future drift in the TS query wrapper. It is evidence, not a test; the
durable record lives in CTK-169 results.md + the index row. Counts move with the
live catalog, so re-runs return today's numbers, not the captured 936.

Run: PYTHONPATH=. .venv/bin/python scripts/ctk169_verify.py
"""

from scrapers.common import db
from scrapers.tools import content_queries as cq


def main() -> None:
    with db.get_conn() as conn:
        # The F7 cover's honest count — len of the UNCAPPED arrivals+restocks
        # population over 168h (content_queries.select_f7_arrivals).
        f7_true_count, composition, items = cq.select_f7_arrivals(conn)

        # The exact SQL getRecentArrivals('newest', null, 'week') issues through
        # orderedEventRows' bare branch (newest + no category): same RPC args as
        # F7, ladder-ordered, UNCAPPED (cap=undefined -> LIMIT NULL).
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT e.*
                FROM get_listing_lead_event(
                    NULL, 168, ARRAY['just-listed','back-in-stock']::text[], NULL
                ) e
                ORDER BY e.event_at DESC, e.id
                """
            )
            week_rows = cur.fetchall()

        # Day feed (bare /new, unchanged) for the contrast sanity check.
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) AS n FROM get_listing_lead_event(NULL, 24, NULL, NULL)"
            )
            day_pop = cur.fetchone()["n"]

    feed_count = len(week_rows)
    matched = sum(1 for r in week_rows if r["named_coral_id"] is not None)
    unmatched = feed_count - matched

    print(f"F7 cover true_count (168h, uncapped):   {f7_true_count}")
    print(f"/new?window=week rendered row count:    {feed_count}")
    print(f"  composition: {composition}  |  F7 sample items (capped<=9): {len(items)}")
    print(f"  matched (named_coral): {matched}   unmatched: {unmatched}")
    print(f"day-feed population (24h, all events):  {day_pop}  (contrast — not week)")

    ok = True
    if feed_count != f7_true_count:
        print(f"FAIL: feed count {feed_count} != F7 true_count {f7_true_count}")
        ok = False
    if matched == 0 or unmatched == 0:
        print(
            f"FAIL: expected matched AND unmatched present "
            f"(matched={matched}, unmatched={unmatched})"
        )
        ok = False
    if feed_count <= 9:
        print(
            "WARN: feed count <= F7 sample_cap (9) — reconciliation holds but the "
            "uncapped-vs-sample distinction is untested at this volume."
        )

    print("PASS — week feed reconciles to F7 cover, uncapped, both classes present."
          if ok else "VERIFY FAILED — see above.")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
