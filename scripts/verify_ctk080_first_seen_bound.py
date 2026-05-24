"""CTK-080 verify-pass — query-side first_seen_at > now() - 7d bound.

Seeds a sentinel row into vendor_listings with first_seen_at = now() - 10d,
in_stock = true, named_coral_id = NULL (NULL bypasses the JS-side dedup at
lib/queries/listings.ts:120-126 — keeps the seed-presence test deterministic
against population noise).

Then runs both query variants — pre-CTK-080 (WHERE in_stock=true only) and
post-CTK-080 (adds AND first_seen_at > $sevenDaysAgo) — and asserts:

  - sentinel present under pre-CTK-080 WHERE
  - sentinel absent under post-CTK-080 WHERE

Captures EXPLAIN ANALYZE of the post-CTK-080 query for results.md.

Cleans up the sentinel row at exit (try/finally — leaves DB unchanged on
failure too).
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone

from scrapers.common.db import get_conn

SENTINEL_TITLE = "CTK-080-VERIFY-SENTINEL do-not-display"
SENTINEL_PRODUCT_URL = "https://example.invalid/ctk-080-verify"


def main() -> int:
    seven_days_ago_iso = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    ten_days_ago = datetime.now(timezone.utc) - timedelta(days=10)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, slug FROM vendors ORDER BY id LIMIT 1")
            vendor_row = cur.fetchone()
            if vendor_row is None:
                print("FAIL — no vendors row to anchor seed against", file=sys.stderr)
                return 1
            vendor_id = vendor_row["id"]
            vendor_slug = vendor_row["slug"]

            cur.execute(
                """
                INSERT INTO vendor_listings (
                  vendor_id, raw_title, normalized_title, current_price, currency,
                  in_stock, lineage_flag,
                  image_url, product_url,
                  first_seen_at, last_seen_at,
                  match_confidence, named_coral_id
                )
                VALUES (
                  %s, %s, %s, NULL, 'USD',
                  true, 'unknown',
                  NULL, %s,
                  %s, NOW(),
                  NULL, NULL
                )
                RETURNING id
                """,
                (vendor_id, SENTINEL_TITLE, SENTINEL_TITLE.lower(),
                 SENTINEL_PRODUCT_URL, ten_days_ago),
            )
            sentinel_id = cur.fetchone()["id"]
            print(f"seeded sentinel id={sentinel_id} vendor={vendor_slug} "
                  f"first_seen_at={ten_days_ago.isoformat()}")

            try:
                # Pre-CTK-080 WHERE: in_stock only.
                cur.execute(
                    """
                    SELECT vl.id
                    FROM vendor_listings vl
                    JOIN vendors v ON v.id = vl.vendor_id
                    LEFT JOIN named_corals nc ON nc.id = vl.named_coral_id
                    WHERE vl.in_stock = true
                    ORDER BY vl.first_seen_at DESC
                    LIMIT 1000
                    """
                )
                pre_ids = {row["id"] for row in cur.fetchall()}
                pre_hit = sentinel_id in pre_ids
                print(f"pre-CTK-080 WHERE  (in_stock only)        sentinel present: {pre_hit}")

                # Post-CTK-080 WHERE: in_stock + 7d bound.
                cur.execute(
                    """
                    SELECT vl.id
                    FROM vendor_listings vl
                    JOIN vendors v ON v.id = vl.vendor_id
                    LEFT JOIN named_corals nc ON nc.id = vl.named_coral_id
                    WHERE vl.in_stock = true
                      AND vl.first_seen_at > %s
                    ORDER BY vl.first_seen_at DESC
                    LIMIT 1000
                    """,
                    (seven_days_ago_iso,),
                )
                post_ids = {row["id"] for row in cur.fetchall()}
                post_hit = sentinel_id in post_ids
                print(f"post-CTK-080 WHERE (in_stock + 7d bound)  sentinel present: {post_hit}")

                # EXPLAIN ANALYZE capture for results.md.
                print("\n--- EXPLAIN ANALYZE (post-CTK-080 query, overFetch=30 LIMIT) ---")
                cur.execute(
                    """
                    EXPLAIN ANALYZE
                    SELECT vl.id, vl.raw_title, vl.first_seen_at, vl.named_coral_id
                    FROM vendor_listings vl
                    JOIN vendors v ON v.id = vl.vendor_id
                    LEFT JOIN named_corals nc ON nc.id = vl.named_coral_id
                    WHERE vl.in_stock = true
                      AND vl.first_seen_at > %s
                    ORDER BY vl.first_seen_at DESC
                    LIMIT 30
                    """,
                    (seven_days_ago_iso,),
                )
                for row in cur.fetchall():
                    line = next(iter(row.values()))
                    print(line)
                print("--- end EXPLAIN ANALYZE ---\n")

                if not pre_hit:
                    print("FAIL — seed missing from pre-CTK-080 baseline; test setup invalid",
                          file=sys.stderr)
                    return 1
                if post_hit:
                    print("FAIL — sentinel surfaced under post-CTK-080 WHERE; bound not effective",
                          file=sys.stderr)
                    return 1
                print("PASS — sentinel present pre-bound, absent post-bound")
                return 0

            finally:
                cur.execute("DELETE FROM vendor_listings WHERE id = %s", (sentinel_id,))
                print(f"cleaned up sentinel id={sentinel_id}")


if __name__ == "__main__":
    sys.exit(main())
