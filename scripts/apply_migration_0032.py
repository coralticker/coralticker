"""Apply migration 0032 — CTK-058 pg_trgm GIN index on normalized_title.

Additive index migration (no data mutation), so the smoke is shape-only per
the 0030/0031 apply-script precedent, trimmed to what an index can break:
  (1) pre-apply — extension present + index absent/present report.
  (2) apply — migration file verbatim (carries its own BEGIN/COMMIT).
  (3) post-apply — index exists on the right column with gin_trgm_ops.
  (4) probe — one EXPLAIN over a representative per-token ILIKE predicate
      pair (ESCAPE '!' composed shape per plan D-058-1) to confirm the
      statement at least plans against the live table. Planner MAY still
      pick a seq scan at current corpus scale — that is fine; the index is
      a growth hedge, so this probe asserts execution, not index usage.

Uses scrapers.common.db.get_conn per architecture #65.
"""

from __future__ import annotations

import sys
from pathlib import Path

from scrapers.common.db import get_conn

MIGRATION_PATH = (
    Path(__file__).resolve().parent.parent
    / "supabase"
    / "migrations"
    / "0032_pg_trgm_search_index.sql"
)

INDEX_NAME = "idx_vl_normalized_title_trgm"


def index_row(cur):
    cur.execute(
        "SELECT indexdef FROM pg_indexes "
        "WHERE tablename = 'vendor_listings' AND indexname = %s",
        (INDEX_NAME,),
    )
    return cur.fetchone()


def main() -> int:
    sql = MIGRATION_PATH.read_text(encoding="utf-8")

    with get_conn() as conn:
        with conn.cursor() as cur:
            print("=" * 70)
            print("pre-apply")
            print("=" * 70)
            cur.execute("SELECT extversion FROM pg_extension WHERE extname = 'pg_trgm'")
            ext = cur.fetchone()
            print(f"  pg_trgm: {ext['extversion'] if ext else 'NOT INSTALLED'}")
            print(f"  {INDEX_NAME}: {'present' if index_row(cur) else 'absent'}")

            print(f"executing: {MIGRATION_PATH.name} ({len(sql)} bytes)...")
            try:
                cur.execute(sql)
            except Exception as exc:
                print(f"  FAILED: {type(exc).__name__}: {exc}")
                return 1
            print("  ok")

            print()
            print("=" * 70)
            print("post-apply — index shape")
            print("=" * 70)
            row = index_row(cur)
            if not row:
                print(f"  FAIL  {INDEX_NAME} missing")
                return 1
            indexdef = row["indexdef"]
            print(f"  {indexdef}")
            if "gin" not in indexdef.lower() or "gin_trgm_ops" not in indexdef:
                print("  FAIL  index is not GIN/gin_trgm_ops")
                return 1
            print("  PASS  GIN + gin_trgm_ops on normalized_title")

            print()
            print("=" * 70)
            print("probe — composed per-token ILIKE plans + executes")
            print("=" * 70)
            cur.execute(
                """
                EXPLAIN (COSTS OFF)
                SELECT id FROM vendor_listings
                WHERE normalized_title ILIKE %s ESCAPE '!'
                  AND normalized_title ILIKE %s ESCAPE '!'
                """,
                ("%rainbow%", "%tenuis%"),
            )
            for r in cur.fetchall():
                print(f"  {list(r.values())[0]}")
            cur.execute(
                """
                SELECT count(*) AS n FROM vendor_listings
                WHERE normalized_title ILIKE %s ESCAPE '!'
                  AND normalized_title ILIKE %s ESCAPE '!'
                """,
                ("%rainbow%", "%tenuis%"),
            )
            print(f"  PASS  executes; 'rainbow tenuis' matches: {cur.fetchone()['n']}")

    print()
    print("all smoke checks PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
