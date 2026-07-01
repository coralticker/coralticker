"""CTK-225 acute backfill — flip the two Cherry dev-SKU rows OOS to stop the
live leak NOW, ahead of the durable title_denylist_exact axis.

id=245469: raw_title='TEST', in_stock=true, is_auction=false, current_price=100
  — the live $100 leak rendering on /vendor/cherry + /new + search.
id=245461: raw_title='test' — OOS/$1 already, flipped too for symmetry.

Single-column, id-scoped UPDATE (in_stock only). This backfill is REQUIRED, not
optional: the durable title_denylist_exact axis does NOT retroactively flip an
already-persisted in_stock=true row OOS. Once the axis ships, a denied row's URL
enters filtered_urls, which diff.classify EXCLUDES from the cohort absent-set
(parse_shopify fetch_and_parse note + diff.classify) — so no OOS decision is ever
emitted for it. The axis prevents RECURRENCE (the row is filtered at parse and
never re-processed, so this backfilled in_stock=false value persists untouched),
but only this one-off write clears the existing leak. Deploy-order matters: land
the axis before the next Cherry scrape, else that scrape re-parses 'TEST' as
in_stock=true (Cherry still lists it available) and diff flips it back to true —
re-run this script if a scrape beats the deploy (feedback_yaml_state_cron_window_risk).

Run: python -m scripts.backfill_ctk225_cherry_test_oos
"""

from __future__ import annotations

from scrapers.common.db import get_conn

TARGET_IDS = (245469, 245461)


def main() -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            # Pre-state (C2 before).
            cur.execute(
                "SELECT id, raw_title, in_stock, is_auction, current_price, category "
                "FROM vendor_listings WHERE id = ANY(%s) ORDER BY id",
                (list(TARGET_IDS),),
            )
            before = cur.fetchall()
            print("before:")
            for row in before:
                print("  ", row)

            # Single-column, id-scoped write.
            cur.execute(
                "UPDATE vendor_listings SET in_stock = false WHERE id = ANY(%s)",
                (list(TARGET_IDS),),
            )
            print(f"rows updated: {cur.rowcount}")

            # C2 after — confirm in_stock=false on both ids.
            cur.execute(
                "SELECT id, raw_title, in_stock FROM vendor_listings "
                "WHERE id = ANY(%s) ORDER BY id",
                (list(TARGET_IDS),),
            )
            after = cur.fetchall()
            print("after:")
            for row in after:
                print("  ", row)
        conn.commit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
