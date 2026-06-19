"""Apply migration 0047 — CTK-158: email_signups.referrer_channel column.

ALTER TABLE ADD COLUMN IF NOT EXISTS — idempotent, re-runnable, no DROP, no data
writes. Additive nullable column, so no round-trip probe (existing rows land NULL,
which is the intended "no channel signal" state).

Verification:
  - referrer_channel present on email_signups after apply
  - column type is text and it is nullable (no NOT NULL, no default)
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
    / "0047_email_signups_referrer_channel.sql"
)

EXPECTED_TABLE = "email_signups"
EXPECTED_COLUMN = "referrer_channel"


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

        # Presence + shape: text, nullable, no default.
        with conn.cursor() as cur:
            cur.execute(
                "SELECT data_type, is_nullable, column_default "
                "FROM information_schema.columns "
                "WHERE table_name = %s AND column_name = %s",
                (EXPECTED_TABLE, EXPECTED_COLUMN),
            )
            row = cur.fetchone()
        if row is None:
            print(f"  VERIFY FAILED: {EXPECTED_TABLE}.{EXPECTED_COLUMN} missing after apply")
            return 1
        if row["data_type"] != "text":
            print(f"  VERIFY FAILED: {EXPECTED_COLUMN} is {row['data_type']}, expected text")
            return 1
        if row["is_nullable"] != "YES":
            print(f"  VERIFY FAILED: {EXPECTED_COLUMN} is NOT NULL, expected nullable")
            return 1
        if row["column_default"] is not None:
            print(f"  VERIFY FAILED: {EXPECTED_COLUMN} has a default, expected none")
            return 1
        print(f"  present: {EXPECTED_TABLE}.{EXPECTED_COLUMN} (text, nullable, no default)")

    print("0047 applied + verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
