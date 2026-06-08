"""Apply migration 0036 — CTK-137 T-1: cohort flip-cap stateful convergence.

Adds cohort_absent_set_hash text + cohort_absent_count integer to scraper_runs
(additive, nullable, no backfill).

SEQUENCING GATE — apply-pre-push: run this BEFORE pushing the run.py change
that writes the two columns. Both are nullable and additive, so the currently-
deployed code (which does not write them) keeps working after the apply; and the
new code requires them to exist or finish_scraper_run's UPDATE errors. Migration
first, code second.

Uses scrapers.common.db.get_conn per the CTK-061 single-statement path. Mirrors
apply_migration_0035.py shape. Idempotent: ADD COLUMN IF NOT EXISTS.

Verification:
  - both columns present on scraper_runs with the expected types (text / integer)
    and nullable
  - get_recent_cohort_absent_hashes runs (exercises the new column in a SELECT)
"""

from __future__ import annotations

import sys
from pathlib import Path

from scrapers.common.db import get_conn

MIGRATION_PATH = (
    Path(__file__).resolve().parent.parent
    / "supabase"
    / "migrations"
    / "0036_cohort_absent_set_tracking.sql"
)

EXPECTED = {
    "cohort_absent_set_hash": "text",
    "cohort_absent_count": "integer",
}


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
        print("post-apply verification — columns on scraper_runs")
        print("=" * 70)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT column_name, data_type, is_nullable "
                "FROM information_schema.columns "
                "WHERE table_name = 'scraper_runs' "
                "  AND column_name = ANY(%s)",
                (list(EXPECTED.keys()),),
            )
            found = {r["column_name"]: r for r in cur.fetchall()}

        for col, dtype in EXPECTED.items():
            row = found.get(col)
            if row is None:
                print(f"  DEFECT: column {col} not present after apply")
                return 1
            if row["data_type"] != dtype:
                print(f"  DEFECT: {col} is {row['data_type']}, expected {dtype}")
                return 1
            if row["is_nullable"] != "YES":
                print(f"  DEFECT: {col} is NOT NULL — must be nullable (no backfill)")
                return 1
            print(f"  {col}: {row['data_type']} nullable=YES")

        print()
        print("=" * 70)
        print("smoke — get_recent_cohort_absent_hashes reads the new column")
        print("=" * 70)
        from scrapers.common import db  # local import: module already loaded

        with get_conn() as conn2:
            # vendor_id=1 (pacific_east); run_id=-1 never matches a real row, so
            # this just confirms the column is selectable end-to-end.
            hashes = db.get_recent_cohort_absent_hashes(conn2, 1, -1, 3)
        print(f"  get_recent_cohort_absent_hashes(vendor=1, k-1=3) -> {len(hashes)} rows")

        print()
        print("all checks passed")

    return 0


if __name__ == "__main__":
    sys.exit(main())
