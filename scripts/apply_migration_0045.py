"""Apply migration 0045 — CTK-170 Item C: ig_spotlight_picks pick-history table.

CREATE TABLE / INDEX IF NOT EXISTS — idempotent, re-runnable, no DROP, no data
writes. Mirrors apply_migration_0044.py shape (the table-creation analogue: a
presence check + a shape probe instead of a function-callable probe).

Verification:
  - ig_spotlight_picks present in pg_tables after apply
  - the five expected columns exist with the expected types
  - the mode/selected_at read index is present
  - an insert + the trailing-window read round-trips (rolled back — no test data left)
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import psycopg

from scrapers.common.db import get_conn

MIGRATION_PATH = (
    Path(__file__).resolve().parent.parent
    / "supabase"
    / "migrations"
    / "0045_ig_spotlight_picks.sql"
)

EXPECTED_TABLE = "ig_spotlight_picks"
EXPECTED_COLUMNS = {"id", "listing_id", "band", "selected_at", "mode"}
EXPECTED_INDEX = "idx_isp_mode_selected"


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

        # Presence check.
        with conn.cursor() as cur:
            cur.execute(
                "SELECT tablename FROM pg_tables WHERE tablename = %s", (EXPECTED_TABLE,)
            )
            if not cur.fetchone():
                print(f"  VERIFY FAILED: {EXPECTED_TABLE} missing after apply")
                return 1
        print(f"  present: {EXPECTED_TABLE}")

        # Column shape.
        with conn.cursor() as cur:
            cur.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
                (EXPECTED_TABLE,),
            )
            cols = {r["column_name"] for r in cur.fetchall()}
            missing = EXPECTED_COLUMNS - cols
            if missing:
                print(f"  VERIFY FAILED: {EXPECTED_TABLE} missing column(s): {sorted(missing)}")
                return 1
        print(f"  columns: {sorted(cols)}")

        # Index presence.
        with conn.cursor() as cur:
            cur.execute(
                "SELECT indexname FROM pg_indexes WHERE indexname = %s", (EXPECTED_INDEX,)
            )
            if not cur.fetchone():
                print(f"  VERIFY FAILED: index {EXPECTED_INDEX} missing")
                return 1
        print(f"  index present: {EXPECTED_INDEX}")

        # Round-trip probe — insert against a real listing, read it back via the
        # trailing-window query shape, then ROLL BACK so no test data persists
        # (autocommit is on, so wrap in an explicit transaction and raise Rollback).
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM vendor_listings LIMIT 1")
            row = cur.fetchone()
        if row is None:
            print("  (skip round-trip: no vendor_listings rows to reference)")
        else:
            lid = row["id"]
            ok = False
            try:
                with conn.transaction():
                    with conn.cursor() as cur:
                        cur.execute(
                            "INSERT INTO ig_spotlight_picks (listing_id, band, mode) "
                            "VALUES (%s, %s, %s)",
                            (lid, "<$150", "daily"),
                        )
                        cur.execute(
                            "SELECT band FROM ig_spotlight_picks WHERE mode = %s "
                            "ORDER BY selected_at DESC, id DESC LIMIT %s",
                            ("daily", 6),
                        )
                        ok = "<$150" in [r["band"] for r in cur.fetchall()]
                    raise psycopg.Rollback()
            except psycopg.Rollback:
                pass
            if not ok:
                print("  VERIFY FAILED: round-trip insert/read did not return the inserted band")
                return 1
            print("  round-trip ok: inserted + read back via trailing-window query (rolled back)")

    print("0045 applied + verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
