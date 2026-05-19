"""Diagnostic — read-only probe of Neon DB state post CTK-043 cutover.

Retained as canonical agent-path reference per CLAUDE.md §Database access —
illustrates the `from scrapers.common.db import get_conn` + `with get_conn() as conn:`
pattern for agent-side Neon queries.

Probes:
  (1) vendors table contents (slug / active / display_name)
  (2) PE vendor_listings count + in-stock vs. last_seen_at window
  (3) Whether get_recent_arrivals() + get_recent_price_drops() exist
  (4) Whether get_recent_arrivals() returns any rows
  (5) PE scraper_runs head — most recent runs
  (6) Per-vendor recent vendor_listings.last_seen_at distribution

Reads .env via scrapers.common.db's load_dotenv() side effect.
"""

from __future__ import annotations

import os
import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv

load_dotenv()

NEON_DATABASE_URL = os.environ["NEON_DATABASE_URL"]


def main() -> None:
    with psycopg.connect(NEON_DATABASE_URL, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            print("=" * 70)
            print("(1) vendors table — all rows")
            print("=" * 70)
            cur.execute(
                "SELECT id, slug, active, display_name FROM vendors ORDER BY id"
            )
            for row in cur.fetchall():
                print(f"  {row}")

            print()
            print("=" * 70)
            print("(2) PE vendor_listings count + last_seen_at distribution")
            print("=" * 70)
            cur.execute(
                """
                SELECT
                  v.slug,
                  COUNT(*) AS total,
                  COUNT(*) FILTER (WHERE vl.in_stock = true) AS in_stock,
                  COUNT(*) FILTER (WHERE vl.last_seen_at > NOW() - INTERVAL '14 days') AS last_seen_le_14d,
                  COUNT(*) FILTER (WHERE vl.last_seen_at > NOW() - INTERVAL '24 hours') AS last_seen_le_24h,
                  MAX(vl.last_seen_at) AS max_last_seen,
                  MIN(vl.last_seen_at) AS min_last_seen,
                  MAX(vl.first_seen_at) AS max_first_seen
                FROM vendor_listings vl
                JOIN vendors v ON v.id = vl.vendor_id
                GROUP BY v.slug
                ORDER BY v.slug
                """
            )
            for row in cur.fetchall():
                print(f"  {row}")

            print()
            print("=" * 70)
            print("(3) RPC presence — pg_proc lookup")
            print("=" * 70)
            cur.execute(
                """
                SELECT proname, pronargs, prorettype::regtype AS rettype
                FROM pg_proc
                WHERE proname IN ('get_recent_arrivals', 'get_recent_price_drops')
                ORDER BY proname
                """
            )
            rows = cur.fetchall()
            if not rows:
                print("  NONE FOUND")
            for row in rows:
                print(f"  {row}")

            print()
            print("=" * 70)
            print("(4) RPC invocation — get_recent_arrivals() row count + sample")
            print("=" * 70)
            try:
                cur.execute("SELECT COUNT(*) AS n FROM get_recent_arrivals()")
                print(f"  get_recent_arrivals() count: {cur.fetchone()}")
                cur.execute("SELECT * FROM get_recent_arrivals() LIMIT 3")
                for row in cur.fetchall():
                    print(f"  sample: {row}")
            except Exception as exc:
                print(f"  EXCEPTION: {type(exc).__name__}: {exc}")

            print()
            try:
                cur.execute("SELECT COUNT(*) AS n FROM get_recent_price_drops()")
                print(f"  get_recent_price_drops() count: {cur.fetchone()}")
            except Exception as exc:
                print(f"  EXCEPTION: {type(exc).__name__}: {exc}")

            print()
            print("=" * 70)
            print("(5) scraper_runs head — last 8 rows")
            print("=" * 70)
            cur.execute(
                """
                SELECT id, vendor_id, status, listings_seen, listings_new,
                       listings_restocked, listings_oos, started_at,
                       finished_at, git_sha
                FROM scraper_runs
                ORDER BY id DESC
                LIMIT 8
                """
            )
            for row in cur.fetchall():
                print(f"  {row}")

            print()
            print("=" * 70)
            print("(6) Per-vendor scraper_runs most-recent + status")
            print("=" * 70)
            cur.execute(
                """
                SELECT
                  v.slug,
                  MAX(sr.id) AS last_run_id,
                  MAX(sr.started_at) AS last_started_at
                FROM scraper_runs sr
                JOIN vendors v ON v.id = sr.vendor_id
                GROUP BY v.slug
                ORDER BY v.slug
                """
            )
            for row in cur.fetchall():
                print(f"  {row}")

            print()
            print("=" * 70)
            print("(7) RPC source — get_recent_arrivals() body (truncated)")
            print("=" * 70)
            cur.execute(
                """
                SELECT pg_get_functiondef(oid) AS def
                FROM pg_proc
                WHERE proname = 'get_recent_arrivals'
                """
            )
            for row in cur.fetchall():
                def_text = row["def"]
                print(def_text[:800])
                if len(def_text) > 800:
                    print(f"  ... [{len(def_text) - 800} more chars]")


if __name__ == "__main__":
    main()
