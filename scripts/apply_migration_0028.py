"""Apply migration 0028 — Q2 amendment: get_listing_lead_event() precedence-
aware three-arm RPC + get_recent_price_drops() inline-widen + drop the
0027 orphan get_listing_drop_context().

CTK-047 B-1 Q2 amendment (price-dropped > back-in-stock > just-listed lead-
event precedence; /brand-manager lock 2026-06-02) + CTK-109 (compare_at_price
+ INV-05 #4 predicate inline on get_recent_price_drops). Supersedes 0027's
get_listing_drop_context shape (orphan; zero production callers — pivot
commit repoints cross-surface medal helper to get_listing_lead_event with
event_filter=['price-dropped']).

Uses scrapers.common.db.get_conn per CTK-061 amendment-2 single-statement
path. Reads the .sql file from disk and executes it as a single batch under
the autocommit connection. Mirrors apply_migration_0027.py shape.

DROP FUNCTION on get_listing_drop_context is no-op-safe (DROP IF EXISTS in
the migration); the orphan has zero callers at apply time (the pivot commit
repoints the medal helper before this script runs). Same idempotency
posture as 0027 — re-running rebinds without error.

get_recent_arrivals() is NOT touched by 0028 — it stays applied state to
keep /new live during the apply → Vercel deploy window. Follow-up
migration 0029 drops it after deploy smoke-pass per open-items.md L263
convention.

Verification: post-apply queries pg_proc for the three expected functions
(present/absent + return-shape) and runs a smoke row-count on
get_listing_lead_event(NULL, 24, NULL).
"""

from __future__ import annotations

import sys
from pathlib import Path

from scrapers.common.db import get_conn

MIGRATION_PATH = Path(__file__).resolve().parent.parent / "supabase" / "migrations" / "0028_get_listing_lead_event.sql"


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
                WHERE proname IN ('get_listing_lead_event', 'get_recent_price_drops',
                                  'get_recent_arrivals', 'get_listing_drop_context')
                  AND pronamespace = 'public'::regnamespace
                ORDER BY proname
                """
            )
            rows = cur.fetchall()
        present = {r["proname"] for r in rows}
        for row in rows:
            print(f"  {row['proname']}({row['args']})")
            result_str = row["result"].replace("\n", " ")
            has_compare = "compare_at_price" in result_str
            has_event = "event " in result_str or result_str.endswith(" event")
            has_prior = "prior_price" in result_str
            markers = []
            if has_compare:
                markers.append("compare_at_price")
            if has_event:
                markers.append("event")
            if has_prior:
                markers.append("prior_price")
            print(f"    projects: {', '.join(markers) if markers else '(none of compare_at_price/event/prior_price)'}")

        # Assertions per directive smoke list.
        if "get_listing_lead_event" not in present:
            print("  MISSING: get_listing_lead_event not created")
            return 1
        lead = [r for r in rows if r["proname"] == "get_listing_lead_event"][0]
        for col in ("event ", "prior_price", "event_at", "compare_at_price"):
            if col.strip() not in lead["result"]:
                print(f"  MISSING: get_listing_lead_event return signature does not include {col!r}")
                return 1

        if "get_recent_price_drops" not in present:
            print("  MISSING: get_recent_price_drops not present post-DROP+CREATE")
            return 1
        gpd = [r for r in rows if r["proname"] == "get_recent_price_drops"][0]
        if "compare_at_price" not in gpd["result"]:
            print("  MISSING: get_recent_price_drops does not project compare_at_price post-widen")
            return 1

        if "get_listing_drop_context" in present:
            print("  EXPECTED ABSENT: get_listing_drop_context still present after 0028 DROP")
            return 1

        if "get_recent_arrivals" not in present:
            print("  EXPECTED PRESENT: get_recent_arrivals dropped early (should land at 0029, not 0028)")
            return 1

        print()
        print("=" * 70)
        print("smoke — get_listing_lead_event(NULL, 24, NULL) row count + event mix")
        print("=" * 70)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT event, COUNT(*) AS c
                FROM get_listing_lead_event(NULL, 24, NULL)
                GROUP BY event
                ORDER BY event
                """
            )
            event_rows = cur.fetchall()
            # CTK-124 migration 0034 retired the zero-arg signature; probe
            # the one-arg union so a historical re-run doesn't crash here.
            cur.execute("SELECT COUNT(*) AS c FROM get_recent_price_drops(7)")
            gpd_count = cur.fetchone()["c"]
        total = sum(int(r["c"]) for r in event_rows)
        print(f"  get_listing_lead_event(NULL, 24, NULL) total: {total} rows")
        for r in event_rows:
            print(f"    event={r['event']:<15} {r['c']} rows")
        print(f"  get_recent_price_drops(7)             total: {gpd_count} rows (one-arg union post-CTK-124)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
