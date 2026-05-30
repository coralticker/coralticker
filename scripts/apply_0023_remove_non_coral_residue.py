"""Apply supabase/migrations/0023_remove_non_coral_residue_5_vendors.sql.

CTK-095 Axis 2 cleanup. Canonical path per CLAUDE.md. Logs per-vendor
in_stock count before/after to confirm row-count delta matches the migration.
Idempotent (re-running after first apply is a no-op — IDs already deleted).
"""

from __future__ import annotations

from pathlib import Path

from scrapers.common.db import get_conn

MIGRATION = (
    Path(__file__).parent.parent
    / "supabase"
    / "migrations"
    / "0023_remove_non_coral_residue_5_vendors.sql"
)
VENDOR_IDS = [1, 3, 4, 5, 6]


def main() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT vendor_id, COUNT(*) AS c FROM vendor_listings "
                "WHERE vendor_id = ANY(%s) AND in_stock = true "
                "GROUP BY vendor_id ORDER BY vendor_id",
                (VENDOR_IDS,),
            )
            before = {r["vendor_id"]: r["c"] for r in cur.fetchall()}
            print(f"before (in_stock=true counts): {before}")

            cur.execute(sql)
            # Last statement's rowcount only; per-vendor split is in the SQL.
            print(f"last-DELETE rowcount: {cur.rowcount}")

            cur.execute(
                "SELECT vendor_id, COUNT(*) AS c FROM vendor_listings "
                "WHERE vendor_id = ANY(%s) AND in_stock = true "
                "GROUP BY vendor_id ORDER BY vendor_id",
                (VENDOR_IDS,),
            )
            after = {r["vendor_id"]: r["c"] for r in cur.fetchall()}
            print(f"after  (in_stock=true counts): {after}")

            for vid in VENDOR_IDS:
                delta = before.get(vid, 0) - after.get(vid, 0)
                print(f"  vendor_id={vid}: delta = {delta}")

        conn.commit()
        print("committed")


if __name__ == "__main__":
    main()
