"""Apply migration 0038 — CTK-042: vendor_listings.is_auction boolean
discriminator for end-time-less Shopify variant-pseudo-auctions.

ADD COLUMN IF NOT EXISTS is_auction boolean NOT NULL DEFAULT false. Every
existing row defaults false; the CTK-042 backfill sets true on the live
_is_auction set, and parse_shopify._normalize_product -> diff.py write the
value on new rows going forward.

APPLY ORDER: this migration, THEN scrapers/tools/ctk042_is_auction_backfill.py
--apply, THEN migration 0039 (the reader gate). 0039 before the backfill
gates on a column that is still all-false — it would exclude nothing.

Uses scrapers.common.db.get_conn (CTK-043 cut-1 single-statement path).
Reads the .sql file from disk and executes it as a single batch under the
autocommit connection. Mirrors apply_migration_0033.py shape.

Idempotent: ADD COLUMN IF NOT EXISTS — re-running is a no-op.

Verification:
  - column present in information_schema (boolean, NOT NULL, default false)
  - current is_auction=true count (0 pre-backfill; the backfill flips it)
"""

from __future__ import annotations

import sys
from pathlib import Path

from scrapers.common.db import get_conn

MIGRATION_PATH = (
    Path(__file__).resolve().parent.parent
    / "supabase" / "migrations" / "0038_add_vendor_listings_is_auction.sql"
)


def main() -> int:
    sql = MIGRATION_PATH.read_text(encoding="utf-8")

    with get_conn() as conn:
        with conn.cursor() as cur:
            print(f"executing: {MIGRATION_PATH.name} ({len(sql)} bytes)...")
            try:
                cur.execute(sql)
            except Exception as exc:
                print(f"  FAILED: {type(exc).__name__}: {exc}")
                return 1
            print("  ok")

        print()
        print("=" * 70)
        print("post-apply verification — column")
        print("=" * 70)

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT column_name, data_type, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_name = 'vendor_listings'
                  AND column_name = 'is_auction'
                """
            )
            col = cur.fetchall()
        if not col:
            print("  MISSING: vendor_listings.is_auction not created")
            return 1
        c = col[0]
        print(
            f"  vendor_listings.is_auction: {c['data_type']} "
            f"nullable={c['is_nullable']} default={c['column_default']}"
        )
        if c["is_nullable"] != "NO" or "false" not in (c["column_default"] or ""):
            print("  CHANGED: expected NOT NULL DEFAULT false")
            return 1

        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS c FROM vendor_listings WHERE is_auction = true")
            true_rows = cur.fetchone()["c"]
        print(f"  is_auction=true rows: {true_rows} (expect 0 pre-backfill)")

    print()
    print("APPLIED — run scrapers/tools/ctk042_is_auction_backfill.py --apply next, THEN migration 0039.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
