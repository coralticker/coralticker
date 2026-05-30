"""Apply supabase/migrations/0022_normalize_phase2_vendor_slugs.sql to Neon.

CTK-095 Axis 1 one-shot. Canonical agent path per CLAUDE.md Database access.
Idempotent: re-running after first apply is a no-op (the UPDATE WHERE clauses
won't match snake_case slugs).
"""

from __future__ import annotations

from pathlib import Path

from scrapers.common.db import get_conn

MIGRATION = (
    Path(__file__).parent.parent
    / "supabase"
    / "migrations"
    / "0022_normalize_phase2_vendor_slugs.sql"
)


def main() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT slug FROM vendors ORDER BY id")
            before = [r["slug"] for r in cur.fetchall()]
            print(f"vendors.slug before: {before}")

            cur.execute(sql)
            print(f"UPDATE rowcount (last statement only): {cur.rowcount}")

            cur.execute("SELECT slug FROM vendors ORDER BY id")
            after = [r["slug"] for r in cur.fetchall()]
            print(f"vendors.slug after:  {after}")

        conn.commit()
        print("committed")


if __name__ == "__main__":
    main()
