"""Apply migration 0064 — CTK-209: Coral Stop vendors row (id=37).

INSERT ... ON CONFLICT (slug) DO NOTHING + a plain MAX(id) setval bump (fleet
idiom per 0059/0060/0061/0063's SQL body; not a GREATEST guard) — idempotent,
re-runnable, no DROP, no destructive write. Seeds the data-side prerequisite the
Coral Stop scraper reads at stage 1 (Config) via db.fetch_vendor.

Verification:
  - vendors row present for slug='coralstop'
  - id=37, platform='shopify', scrape_method='products_json', active=true
  - display_name="Coral Stop", base_url='https://coralstop.com'
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
    / "0064_add_coralstop_vendor.sql"
)

EXPECTED_SLUG = "coralstop"
EXPECTED = {
    "id": 37,
    "display_name": "Coral Stop",
    "base_url": "https://coralstop.com",
    "platform": "shopify",
    "scrape_method": "products_json",
    "cadence_label": "hourly",
    "image_strategy": "mirror",
    "active": True,
}


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

        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, slug, display_name, base_url, platform, scrape_method, "
                "cadence_label, image_strategy, active "
                "FROM vendors WHERE slug = %s",
                (EXPECTED_SLUG,),
            )
            row = cur.fetchone()

        if row is None:
            print(f"  VERIFY FAILED: vendors row for slug={EXPECTED_SLUG!r} missing after apply")
            return 1
        for key, want in EXPECTED.items():
            got = row[key]
            if got != want:
                print(f"  VERIFY FAILED: vendors.{key} = {got!r}, expected {want!r}")
                return 1
        print(f"  present: vendors id={row['id']} slug={row['slug']!r} "
              f"({row['platform']}/{row['scrape_method']}, active={row['active']})")

    print("0064 applied + verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
