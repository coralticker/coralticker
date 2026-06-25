"""Apply migration 0056 — CTK-198 (Tier 1B): add the persisted `bulk_cluster`
boolean to vendor_listings.

ADD COLUMN ... NOT NULL DEFAULT false is metadata-only on Neon/PG15 (no table
rewrite, no per-row backfill for the column add). The ~15,779-row historical
backfill of `true` values is a SEPARATE one-shot
(scripts/ctk198_bulk_cluster_backfill.py), gated behind a dry-run eyeball — NOT
this DDL.

APPLY-ORDER (load-bearing): this column must be applied to prod BEFORE the
diff.py write-time hook deploys — the hook's UPDATE errors if the column is
absent. This script is therefore the first prod step of CTK-198.

Uses scrapers.common.db.get_conn per the CTK-061 single-statement path. Mirrors
apply_migration_0055.py shape.

Verification:
  - column bulk_cluster present on vendor_listings (information_schema)
  - it is boolean, NOT NULL, DEFAULT false
  - every existing row reads false (the metadata default — backfill is separate)
  - the COMMENT is attached (self-healing contract is documented in-DB)
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from scrapers.common.db import get_conn

MIGRATION_PATH = (
    Path(__file__).resolve().parent.parent
    / "supabase"
    / "migrations"
    / "0056_add_bulk_cluster_column.sql"
)


def main() -> int:
    sql = MIGRATION_PATH.read_text(encoding="utf-8")

    with get_conn() as conn:
        with conn.cursor() as cur:
            print(f"executing: {MIGRATION_PATH.name} ({len(sql)} bytes)...")
            t0 = time.monotonic()
            try:
                cur.execute(sql)
            except Exception as exc:  # noqa: BLE001 — surface loudly, exit 1
                print(f"  FAILED: {type(exc).__name__}: {exc}")
                return 1
            elapsed_ms = (time.monotonic() - t0) * 1000.0
            print(f"  applied in {elapsed_ms:.0f} ms")

        # Column presence + shape.
        with conn.cursor() as cur:
            cur.execute(
                "SELECT data_type, is_nullable, column_default "
                "FROM information_schema.columns "
                "WHERE table_name = 'vendor_listings' AND column_name = 'bulk_cluster'"
            )
            row = cur.fetchone()
        if row is None:
            print("  VERIFY FAILED: bulk_cluster column not present after apply")
            return 1
        if row["data_type"] != "boolean":
            print(f"  VERIFY FAILED: bulk_cluster data_type = {row['data_type']}, expected boolean")
            return 1
        if row["is_nullable"] != "NO":
            print(f"  VERIFY FAILED: bulk_cluster is_nullable = {row['is_nullable']}, expected NO")
            return 1
        if "false" not in (row["column_default"] or "").lower():
            print(f"  VERIFY FAILED: bulk_cluster default = {row['column_default']!r}, expected false")
            return 1
        print(
            f"  present: bulk_cluster {row['data_type']} "
            f"NOT NULL DEFAULT {row['column_default']}"
        )

        # All existing rows read false (metadata default; backfill is separate).
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FILTER (WHERE bulk_cluster) AS t, count(*) AS n "
                "FROM vendor_listings"
            )
            counts = cur.fetchone()
        print(f"  rows: {counts['n']} total, {counts['t']} bulk_cluster=true (expect 0 pre-backfill)")

        # COMMENT attached (self-healing contract documented in-DB).
        with conn.cursor() as cur:
            cur.execute(
                "SELECT col_description("
                "  'vendor_listings'::regclass, "
                "  (SELECT attnum FROM pg_attribute "
                "   WHERE attrelid = 'vendor_listings'::regclass AND attname = 'bulk_cluster')"
                ") AS comment"
            )
            comment = cur.fetchone()["comment"]
        if not comment or "CTK-198" not in comment:
            print("  VERIFY FAILED: bulk_cluster COMMENT missing or unexpected")
            return 1
        print("  COMMENT attached (self-healing contract documented).")

    print("0056 applied + verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
