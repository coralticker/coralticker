"""Apply migration 0025 — vendor_listings.compare_at_price column.

CTK-100 Wave-1 standalone (Jon-ratified 2026-05-31). Uses
scrapers.common.db.get_conn per CTK-061 amendment-2 single-statement path
(no migration runner). Reads the .sql file from disk and executes its two
statements (ALTER TABLE + COMMENT ON COLUMN) inside the autocommit
connection.

Idempotent on re-run: ADD COLUMN raises duplicate_column on a second
invocation, COMMENT ON is safe to re-execute. The script splits on the
semicolon-blank-line boundary the .sql file uses and runs each statement
under its own try-block so a partial-applied state (column landed,
comment failed mid-flight) re-applies cleanly without manual
intervention.

Verification: post-apply queries information_schema.columns for the
column row and prints it — paste-target for the engineer-wrap report.
"""

from __future__ import annotations

import sys
from pathlib import Path

from scrapers.common.db import get_conn

MIGRATION_PATH = Path(__file__).resolve().parent.parent / "supabase" / "migrations" / "0025_add_vendor_listings_compare_at_price.sql"


def main() -> int:
    sql = MIGRATION_PATH.read_text(encoding="utf-8")
    statements = [s.strip() for s in sql.split(";") if s.strip()]

    with get_conn() as conn:
        with conn.cursor() as cur:
            for stmt in statements:
                preview = stmt.replace("\n", " ")[:90]
                print(f"executing: {preview}...")
                try:
                    cur.execute(stmt)
                except Exception as exc:
                    msg = str(exc)
                    # idempotency: ADD COLUMN on second run raises duplicate_column.
                    if "already exists" in msg or "duplicate_column" in msg:
                        print(f"  skip (already applied): {type(exc).__name__}: {msg}")
                        continue
                    print(f"  FAILED: {type(exc).__name__}: {msg}")
                    return 1
                print("  ok")

        print()
        print("=" * 70)
        print("post-apply verification — information_schema.columns row")
        print("=" * 70)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT column_name, data_type, numeric_precision, numeric_scale,
                       is_nullable, column_default
                FROM information_schema.columns
                WHERE table_name = 'vendor_listings'
                  AND column_name = 'compare_at_price'
                """
            )
            rows = cur.fetchall()
        if not rows:
            print("  EXPECTED row not found — column did not land")
            return 1
        for row in rows:
            print(f"  {row}")

        print()
        print("=" * 70)
        print("column comment — pg_description")
        print("=" * 70)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT col_description(
                  ('vendor_listings'::regclass)::oid,
                  (SELECT ordinal_position FROM information_schema.columns
                   WHERE table_name = 'vendor_listings' AND column_name = 'compare_at_price')
                ) AS comment
                """
            )
            row = cur.fetchone()
        print(f"  {row}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
