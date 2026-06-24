"""CTK-169/195 — point-in-time /new-week vs F7-cover EVIDENCE (not a regression guard).

Captured 2026-06-17 to prove /new?window=week reconciled to the F7 IG cover count
at close (rendered week count == F7 true_count, 936==936, matched + unmatched both
present, uncapped). This script RECONSTRUCTS the week-branch SQL — it does NOT
import getRecentArrivals, so it never guarded the TS wrapper. It is evidence, not a
test; the durable record lives in CTK-169 results.md.

CTK-191 temporarily diverged the two counts: the F7 cover true_count became the
GUARDED honest count (cold-start backfill + bulk-relist re-index excluded) while the
/new?window=week feed still served the UNGUARDED population, so the cover read ~788
against a ~2050 feed. CTK-195 (2026-06-24) CLOSED that divergence: the website week
feed now reads the SAME shared guarded source (get_f7_arrivals_guarded, migration
0052) the cover counts through. The script is reframed accordingly — it now asserts
RECONCILIATION (both surfaces guarded → cover-vs-feed gap ~0), not divergence. It
reconstructs the post-CTK-195 week SQL (the guarded function the TS feed now issues),
so the surviving evidence claim is the original CTK-169 one again: feed == cover.

Run: PYTHONPATH=. .venv/bin/python scripts/ctk169_verify.py
"""

from scrapers.common import db
from scrapers.tools import content_queries as cq


def main() -> None:
    with db.get_conn() as conn:
        # The F7 cover's GUARDED honest count (CTK-191) — uncapped arrivals+restocks
        # over 168h, minus cold-start + bulk-relist artifacts.
        f7_true_count, composition, items = cq.select_f7_arrivals(conn)

        # The exact SQL getRecentArrivals('newest', null, 'week') issues post-CTK-195
        # — the GUARDED shared source (migration 0052), same population the F7 cover
        # counts through. Uncapped; cold-start + bulk-relist excluded.
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT e.*
                FROM get_f7_arrivals_guarded(
                    168, ARRAY['just-listed','back-in-stock']::text[]
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
    gap = feed_count - f7_true_count

    print(f"F7 cover true_count (168h, GUARDED):    {f7_true_count}")
    print(f"/new?window=week rendered row count:    {feed_count}  (GUARDED, CTK-195)")
    print(f"  cover-vs-feed gap:                    {gap}  (expect ~0 — both guarded)")
    print(f"  composition: {composition}  |  F7 sample items (capped<=9): {len(items)}")
    print(f"  matched (named_coral): {matched}   unmatched: {unmatched}")
    print(f"day-feed population (24h, all events):  {day_pop}  (contrast — not week)")

    ok = True
    # Post-CTK-195 both surfaces route through get_f7_arrivals_guarded, so the
    # CTK-169 reconciliation holds again: the gap should collapse to ~0. A tiny
    # nonzero gap is tolerated (separate statements can straddle a now()-edge if the
    # connection isn't single-transaction); a large gap means the surfaces diverged.
    GAP_TOLERANCE = 2
    if abs(gap) > GAP_TOLERANCE:
        print(
            f"FAIL: cover-vs-feed gap {gap} exceeds tolerance {GAP_TOLERANCE} — the "
            f"week feed and the F7 cover no longer reconcile (one guarded, one not?)."
        )
        ok = False
    if matched == 0 or unmatched == 0:
        print(
            f"FAIL: expected matched AND unmatched present in the feed "
            f"(matched={matched}, unmatched={unmatched})"
        )
        ok = False

    print("PASS — week feed reconciles to the guarded F7 cover (gap ~0)."
          if ok else "VERIFY FAILED — see above.")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
