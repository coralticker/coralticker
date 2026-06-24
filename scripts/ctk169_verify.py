"""CTK-169 — point-in-time /new-week vs F7-cover EVIDENCE (not a regression guard).

Captured 2026-06-17 to prove /new?window=week reconciled to the F7 IG cover count
at close (rendered week count == F7 true_count, 936==936, matched + unmatched both
present, uncapped). This script RECONSTRUCTS the week-branch SQL — it does NOT
import getRecentArrivals, so it never guarded the TS wrapper. It is evidence, not a
test; the durable record lives in CTK-169 results.md.

CTK-191 INTENTIONALLY RETIRED the feed==cover invariant (2026-06-24). The F7 cover
true_count is now the GUARDED honest count (cold-start backfill + bulk-relist
re-index excluded); the /new?window=week feed still serves the UNGUARDED population.
So the two counts now diverge BY DESIGN, and the gap equals the CTK-191 exclusion
total. This script is rewritten to REPORT that divergence (not fail on it) and to
sanity-check the one direction that must still hold: guarded cover <= unguarded feed.
The cross-surface reconciliation (whether the site week-feed should hide backfill
too, and the now-stale comment at lib/queries/listings.ts:905-907) is the routed
website-week-feed follow-up (/lead-frontend).

Run: PYTHONPATH=. .venv/bin/python scripts/ctk169_verify.py
"""

from scrapers.common import db
from scrapers.tools import content_queries as cq


def main() -> None:
    with db.get_conn() as conn:
        # The F7 cover's GUARDED honest count (CTK-191) — uncapped arrivals+restocks
        # over 168h, minus cold-start + bulk-relist artifacts.
        f7_true_count, composition, items = cq.select_f7_arrivals(conn)

        # The exact SQL getRecentArrivals('newest', null, 'week') issues — same RPC
        # args as the F7 population but UNGUARDED (no CTK-191 exclusion), uncapped.
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
    excluded = feed_count - f7_true_count

    print(f"F7 cover true_count (168h, GUARDED):    {f7_true_count}")
    print(f"/new?window=week rendered row count:    {feed_count}  (UNGUARDED)")
    print(f"  CTK-191 cover-vs-feed gap (excluded): {excluded}  (cold-start + bulk-relist)")
    print(f"  composition: {composition}  |  F7 sample items (capped<=9): {len(items)}")
    print(f"  matched (named_coral): {matched}   unmatched: {unmatched}")
    print(f"day-feed population (24h, all events):  {day_pop}  (contrast — not week)")

    ok = True
    # The retired invariant was feed == cover. The surviving sanity check: the
    # guarded cover can only ever be a SUBSET of the unguarded feed, never larger.
    if f7_true_count > feed_count:
        print(f"FAIL: guarded cover {f7_true_count} > unguarded feed {feed_count} — impossible.")
        ok = False
    if matched == 0 or unmatched == 0:
        print(
            f"FAIL: expected matched AND unmatched present in the feed "
            f"(matched={matched}, unmatched={unmatched})"
        )
        ok = False
    if excluded > 0:
        print(
            "NOTE: cover < feed by the exclusion total — the intended CTK-191 "
            "divergence. Cross-surface reconciliation is the routed /lead-frontend "
            "website-week-feed follow-up."
        )

    print("PASS — guarded cover is a subset of the feed; CTK-191 divergence reported."
          if ok else "VERIFY FAILED — see above.")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
