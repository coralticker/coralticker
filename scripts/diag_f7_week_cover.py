"""Read-only diagnostic — verify the F7 week-cover organic count (CTK-169 / CTK-161).

Reef-lead flagged the /new?window=week C2 run rendered ~936 rows vs a ~196 linear
extrapolation from the 28-row day feed (~4.8x over expected). Before the F7 IG
cover publishes "{count} new this week", confirm the count is organic — not
inflated by the CTK-042 dead-auction leak, CTK-160 cohort re-entry, or a
first_seen_at backfill/cold-start sweep inside the 168h window.

The honest-count canon means an inflated-but-reconciling count is still a
published falsehood, so this establishes the true organic count + attributes any
gap to a named cause.

Read-only via scrapers.common.db.get_conn. No writes.
"""

from __future__ import annotations

from scrapers.common.db import get_conn

F7_ARMS = ["just-listed", "back-in-stock"]


def _rows(cur, sql, params=None):
    cur.execute(sql, params or ())
    return cur.fetchall()


def main() -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            print("=== 168h (week) lead-events, UNCAPPED (row_limit NULL) ===")
            for label, arms in (("F7 arms (just-listed+back-in-stock)", F7_ARMS),
                                ("ALL arms (event_filter NULL)", None)):
                by_arm = _rows(
                    cur,
                    "SELECT event, count(*) AS n "
                    "FROM get_listing_lead_event(NULL, 168, %s, NULL) GROUP BY event ORDER BY n DESC",
                    (arms,),
                )
                total = sum(r["n"] for r in by_arm)
                print(f"  {label}: total={total}  " + " ".join(f"{r['event']}={r['n']}" for r in by_arm))

            print("\n=== 24h (day) lead-events, UNCAPPED, for the day-vs-week ratio ===")
            for label, arms in (("F7 arms", F7_ARMS), ("ALL arms", None)):
                by_arm = _rows(
                    cur,
                    "SELECT event, count(*) AS n "
                    "FROM get_listing_lead_event(NULL, 24, %s, NULL) GROUP BY event ORDER BY n DESC",
                    (arms,),
                )
                total = sum(r["n"] for r in by_arm)
                print(f"  {label}: total={total}  " + " ".join(f"{r['event']}={r['n']}" for r in by_arm))

            print("\n=== 168h F7-arm count by vendor (a single vendor flooding = cold-start/re-scrape) ===")
            per_vendor = _rows(
                cur,
                "SELECT vendor_slug, event, count(*) AS n "
                "FROM get_listing_lead_event(NULL, 168, %s, NULL) "
                "GROUP BY vendor_slug, event ORDER BY n DESC LIMIT 25",
                (F7_ARMS,),
            )
            for r in per_vendor:
                print(f"  {r['vendor_slug']:<22} {r['event']:<14} {r['n']}")

            print("\n=== 168h just-listed: first_seen_at by DAY (a backfill/cold-start shows as one big day) ===")
            hist = _rows(
                cur,
                "SELECT date_trunc('day', first_seen_at)::date AS day, count(*) AS n "
                "FROM get_listing_lead_event(NULL, 168, ARRAY['just-listed'], NULL) "
                "GROUP BY day ORDER BY day",
            )
            for r in hist:
                print(f"  {r['day']}  {r['n']}")

            print("\n=== auction-gate sanity (0039 is_auction gate; should be 0 in the result) ===")
            leaked = _rows(
                cur,
                "SELECT count(*) AS n FROM get_listing_lead_event(NULL, 168, %s, NULL) le "
                "JOIN vendor_listings vl ON vl.id = le.id "
                "WHERE vl.is_auction = true OR vl.auction_end_time IS NOT NULL",
                (F7_ARMS,),
            )
            excluded = _rows(
                cur,
                "SELECT count(*) AS n FROM vendor_listings "
                "WHERE first_seen_at > now() - interval '168 hours' AND in_stock = true "
                "AND (is_auction = true OR auction_end_time IS NOT NULL)",
            )
            print(f"  auction rows IN the F7 result (want 0): {leaked[0]['n']}")
            print(f"  in-stock auction rows first-seen in 168h the gate EXCLUDES: {excluded[0]['n']}")

    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
