"""Apply migration 0027 — generalized get_listing_drop_context() RPC +
get_recent_arrivals() widen to project compare_at_price.

CTK-047 B-1 (generalized RPC) + CTK-109 (compare_at_price widen) + INV-05
obligation #4 (auction_end_time IS NULL first-enforce) bundle at migration
boundary per Jon directive 2026-06-02. Uses scrapers.common.db.get_conn per
CTK-061 amendment-2 single-statement path (no migration runner); reads the
.sql file from disk and executes it as a single batch under the autocommit
connection.

Diverges from apply_migration_0025.py's split-on-semicolon shape because
0027 contains semicolons inside dollar-quoted function bodies AND inside
'--' line comments in the header. Both function definitions
(CREATE OR REPLACE for get_listing_drop_context, DROP+CREATE for
get_recent_arrivals) plus their GRANT statements are inherently idempotent
under re-run — the DROP IF EXISTS makes the get_recent_arrivals signature
swap re-runnable, and CREATE OR REPLACE on get_listing_drop_context rebinds
without error. Single cursor.execute() with the full file is the simplest
correct shape, mirroring apply_migration_0026.py.

Verification: post-apply queries pg_proc for both function bodies and
confirms the new shape — get_listing_drop_context present + take a smoke
count of the NULL-args call to confirm executable. get_recent_arrivals
return type includes compare_at_price column.
"""

from __future__ import annotations

import sys
from pathlib import Path

from scrapers.common.db import get_conn

MIGRATION_PATH = Path(__file__).resolve().parent.parent / "supabase" / "migrations" / "0027_get_listing_drop_context.sql"


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
        print("post-apply verification — pg_proc presence + signature")
        print("=" * 70)

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT proname, pg_get_function_identity_arguments(oid) AS args,
                       pg_get_function_result(oid) AS result
                FROM pg_proc
                WHERE proname IN ('get_listing_drop_context', 'get_recent_arrivals',
                                  'get_recent_price_drops')
                  AND pronamespace = 'public'::regnamespace
                ORDER BY proname
                """
            )
            rows = cur.fetchall()
        if not rows:
            print("  EXPECTED functions not found")
            return 1
        for row in rows:
            print(f"  {row['proname']}({row['args']})")
            result_str = row["result"].replace("\n", " ")
            has_compare = "compare_at_price" in result_str
            marker = "compare_at_price ✓" if has_compare else "compare_at_price ✗"
            print(f"    returns: {marker}")

        present = {r["proname"] for r in rows}
        if "get_listing_drop_context" not in present:
            print("  MISSING: get_listing_drop_context not created")
            return 1
        gra = [r for r in rows if r["proname"] == "get_recent_arrivals"]
        if not gra or "compare_at_price" not in gra[0]["result"]:
            print("  MISSING: get_recent_arrivals does not project compare_at_price")
            return 1

        print()
        print("=" * 70)
        print("smoke — get_listing_drop_context(NULL, 24) row count")
        print("=" * 70)
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS c FROM get_listing_drop_context(NULL, 24)")
            new_count = cur.fetchone()["c"]
            cur.execute("SELECT COUNT(*) AS c FROM get_recent_price_drops()")
            old_count = cur.fetchone()["c"]
        print(f"  get_listing_drop_context(NULL, 24): {new_count} rows")
        print(f"  get_recent_price_drops():           {old_count} rows  (legacy, unused post-CTK-109 frontend swap)")
        if new_count > old_count:
            print(
                f"  NOTE: new returns more rows than old — unexpected (auction predicate is "
                f"additive-restrict, not additive-permit). Investigate."
            )
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
