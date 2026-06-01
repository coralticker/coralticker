"""Apply migration 0026 — add in_stock=true filter to get_recent_price_drops().

CTK-099 standalone (Jon-ratified 2026-06-01; fold-vs-CTK-094 window passed
2026-05-31). Uses scrapers.common.db.get_conn per CTK-061 amendment-2
single-statement path (no migration runner). Reads the .sql file from
disk and executes it as a single batch under the autocommit connection.

Diverges from apply_migration_0025.py's split-on-semicolon shape because
0026 contains semicolons inside a dollar-quoted function body AND inside
'--' line comments in the header. Both statements (CREATE OR REPLACE
FUNCTION + GRANT EXECUTE) are inherently idempotent — re-running rebinds
the function body with no error and re-asserts existing privileges — so
there is no need to isolate each statement under its own try-block. A
single cursor.execute() with the full file is the simplest correct shape.

Verification: post-apply queries pg_proc for the function's prosrc body
and confirms the new in_stock predicate is present — paste-target for
the engineer-wrap report.
"""

from __future__ import annotations

import sys
from pathlib import Path

from scrapers.common.db import get_conn

MIGRATION_PATH = Path(__file__).resolve().parent.parent / "supabase" / "migrations" / "0026_get_recent_price_drops_in_stock_filter.sql"


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
        print("post-apply verification — pg_proc.prosrc contains in_stock predicate")
        print("=" * 70)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT prosrc
                FROM pg_proc
                WHERE proname = 'get_recent_price_drops'
                  AND pronamespace = 'public'::regnamespace
                """
            )
            rows = cur.fetchall()
        if not rows:
            print("  EXPECTED function not found")
            return 1
        body = rows[0]["prosrc"]
        marker = "AND vl.in_stock = true"
        if marker in body:
            print(f"  found marker: '{marker}'")
        else:
            print(f"  MARKER MISSING: '{marker}' not in function body")
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
