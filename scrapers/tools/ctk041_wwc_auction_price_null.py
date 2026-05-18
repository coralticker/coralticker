"""CTK-041 Session 1 — WWC auction price-null one-shot cleanup.

UPDATE vendor_listings SET current_price = NULL WHERE vendor_id = 2 AND
product_url ILIKE '%-auc'. Covers the 4 known WWC auction rows (ids 16177,
16190, 51944, 51945 per CTK-041 plan body) at ship-time. Idempotent —
re-running is safe (NULL stays NULL); the new auction_detection block in
wwc.yaml (CTK-041 D-1 lean (b)) handles forward-write null-out so the next
WWC cron firing maintains the cleaned state without needing this script.

Per /lead-backend lean 2026-05-14 + Jon 2026-05-14 directive: parser-side
null-out is the forward-write fix; this script is the one-shot backfill for
the 4 already-persisted rows that wrote placeholder $X prices before the
auction_detection block landed. After this script runs + the parser ships,
frontend renders "price on request" via formatPrice(null) at
components/listing-card.tsx:39-42.

Run via:
  python -m scrapers.tools.ctk041_wwc_auction_price_null

Exit codes: 0 on success (UPDATE applied + row count printed), 1 on DB
error. Reads NEON_DATABASE_URL from .env via scrapers.common.db's
load_dotenv() side effect.
"""

from __future__ import annotations

import sys

from scrapers.common import db


WWC_VENDOR_ID = 2
URL_PATTERN = "%-auc"


def main() -> int:
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            # Pre-flight: show the rows we're about to touch + their current price.
            cur.execute(
                "SELECT id, product_url, current_price FROM vendor_listings "
                "WHERE vendor_id = %s AND product_url ILIKE %s "
                "ORDER BY id",
                (WWC_VENDOR_ID, URL_PATTERN),
            )
            pre_rows = cur.fetchall()
            print(f"pre-UPDATE rows ({len(pre_rows)}):")
            for r in pre_rows:
                print(f"  id={r['id']:6d}  current_price={r['current_price']}  url={r['product_url']}")

            # One-shot UPDATE. Idempotent — rows already NULL stay NULL.
            cur.execute(
                "UPDATE vendor_listings SET current_price = NULL "
                "WHERE vendor_id = %s AND product_url ILIKE %s",
                (WWC_VENDOR_ID, URL_PATTERN),
            )
            affected = cur.rowcount
            print(f"UPDATE affected: {affected} rows")

            # Post-verify.
            cur.execute(
                "SELECT id, product_url, current_price FROM vendor_listings "
                "WHERE vendor_id = %s AND product_url ILIKE %s "
                "ORDER BY id",
                (WWC_VENDOR_ID, URL_PATTERN),
            )
            post_rows = cur.fetchall()
            non_null = [r for r in post_rows if r["current_price"] is not None]
            if non_null:
                print(f"WARN: {len(non_null)} rows still hold non-NULL current_price post-UPDATE:")
                for r in non_null:
                    print(f"  id={r['id']:6d}  current_price={r['current_price']}  url={r['product_url']}")
                return 1
            print(f"post-UPDATE verify: {len(post_rows)} rows match pattern, all current_price IS NULL")
    return 0


if __name__ == "__main__":
    sys.exit(main())
