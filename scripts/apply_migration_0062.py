"""Apply migration 0062 — CTK-204 per-vendor drop-cadence query family.

Ships two new row-returning functions over the honest-organic population (guarded
just-listed + INV-07 equipment denylist + INV-08 bulk_cluster):
  - get_vendor_recent_drops(slug, window_days, limit)  — Scope A feed
  - get_vendor_drop_cadence(slug)                       — Scope B summary + gate

Both are CREATE FUNCTION (new names). This script DROPs both signatures first so it
is re-runnable, then applies the migration body. Mirrors apply_migration_0058.py:
scrapers.common.db.get_conn against NEON_DATABASE_URL (architecture-v1.md #65).

Verification (exercises the guarantees, not just presence):
  Scope A — get_vendor_recent_drops returns the honest-organic feed:
    * a qualifying vendor (wwc) returns a non-empty feed, ordered first_seen DESC,
      and every returned id is bulk_cluster=false + non-equipment (the INV join has
      teeth — fail-if-the-join-were-dropped).
    * a quiet vendor (battlecorals) returns ZERO rows (the honest "quiet lately"
      state, not an error).
  Scope B — get_vendor_drop_cadence:
    * qualifies_for_histogram across the live fleet equals EXACTLY
      {wwc, tsa, jf, pacific_east} — the ratified set. Drift here means the gate is
      mis-specified (CTK-204 directive: "if the set drifts, the gate's wrong").
    * battlecorals + cornbred report organic_drop_count = 0, last_organic_drop_at
      NULL, qualifies_for_histogram = false (feed-only / quiet states).
    * DOW buckets sum to organic_drop_count (no drops lost or double-counted).
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
    / "0062_vendor_drop_cadence.sql"
)

EXPECTED_QUALIFIERS = {"wwc", "tsa", "jf", "pacific_east"}
DROP_SQL = (
    "DROP FUNCTION IF EXISTS get_vendor_recent_drops(text, int, int); "
    "DROP FUNCTION IF EXISTS get_vendor_drop_cadence(text);"
)


def main() -> int:
    sql = MIGRATION_PATH.read_text(encoding="utf-8")

    with get_conn() as conn:
        with conn.cursor() as cur:
            print(f"executing: {MIGRATION_PATH.name} ({len(sql)} bytes)...")
            t0 = time.monotonic()
            try:
                cur.execute(DROP_SQL)
                cur.execute(sql)
            except Exception as exc:  # noqa: BLE001 — surface loudly, exit 1
                print(f"  FAILED: {type(exc).__name__}: {exc}")
                return 1
            elapsed_ms = (time.monotonic() - t0) * 1000.0
            print(f"  applied in {elapsed_ms:.0f} ms")

        # ── Presence ──
        with conn.cursor() as cur:
            cur.execute(
                "SELECT proname FROM pg_proc "
                "WHERE proname IN ('get_vendor_recent_drops', 'get_vendor_drop_cadence')"
            )
            present = {r["proname"] for r in cur.fetchall()}
        missing = {"get_vendor_recent_drops", "get_vendor_drop_cadence"} - present
        if missing:
            print(f"  VERIFY FAILED: functions missing after apply: {sorted(missing)}")
            return 1
        print("  present: get_vendor_recent_drops, get_vendor_drop_cadence")

        # ── Scope A — feed has teeth (wwc non-empty, INV join enforced) ──
        with conn.cursor() as cur:
            t0 = time.monotonic()
            cur.execute("SELECT * FROM get_vendor_recent_drops('wwc', 60, NULL)")
            wwc_rows = cur.fetchall()
            a_ms = (time.monotonic() - t0) * 1000.0
            if not wwc_rows:
                print("  VERIFY FAILED: get_vendor_recent_drops('wwc') returned 0 rows")
                return 1
            # Ordered first_seen DESC.
            fs = [r["first_seen_at"] for r in wwc_rows]
            if fs != sorted(fs, reverse=True):
                print("  VERIFY FAILED: get_vendor_recent_drops('wwc') not ordered first_seen DESC")
                return 1
            # Every returned id is non-equipment + bulk_cluster=false (the INV join).
            ids = [r["id"] for r in wwc_rows]
            cur.execute(
                "SELECT COUNT(*)::int AS n FROM vendor_listings "
                "WHERE id = ANY(%s) AND (category = 'equipment' OR bulk_cluster = true)",
                (ids,),
            )
            leaked = cur.fetchone()["n"]
            if leaked:
                print(f"  VERIFY FAILED: {leaked} wwc feed rows are equipment/bulk_cluster (INV join not enforced)")
                return 1

            # Scope A quiet state — battlecorals returns zero rows.
            cur.execute("SELECT COUNT(*)::int AS n FROM get_vendor_recent_drops('battlecorals', 60, NULL)")
            bc_feed = cur.fetchone()["n"]
            if bc_feed != 0:
                print(f"  VERIFY FAILED: battlecorals feed returned {bc_feed} rows, expected 0 (quiet state)")
                return 1
        print(
            f"  Scope A: wwc feed = {len(wwc_rows)} rows (ordered, INV-clean, {a_ms:.0f} ms); "
            f"battlecorals feed = 0 rows (quiet)."
        )

        # ── Scope B — gate reproduces the ratified set across the live fleet ──
        with conn.cursor() as cur:
            cur.execute("SELECT slug FROM vendors WHERE slug NOT LIKE '\\_%' ORDER BY slug")
            slugs = [r["slug"] for r in cur.fetchall()]
            qualifiers = set()
            cadence = {}
            t0 = time.monotonic()
            for slug in slugs:
                cur.execute("SELECT * FROM get_vendor_drop_cadence(%s)", (slug,))
                row = cur.fetchone()
                cadence[slug] = row
                if row and row["qualifies_for_histogram"]:
                    qualifiers.add(slug)
            b_ms = (time.monotonic() - t0) * 1000.0

        if qualifiers != EXPECTED_QUALIFIERS:
            print(
                f"  VERIFY FAILED: qualifies_for_histogram = {sorted(qualifiers)}, "
                f"expected {sorted(EXPECTED_QUALIFIERS)} (gate drift — fix the gate, not the data)"
            )
            return 1

        # Quiet states — battlecorals + cornbred are organic 0 / NULL / not-qualifying.
        for slug in ("battlecorals", "cornbred"):
            r = cadence.get(slug)
            if r is None:
                print(f"  VERIFY FAILED: get_vendor_drop_cadence('{slug}') returned no row")
                return 1
            if r["organic_drop_count"] != 0 or r["last_organic_drop_at"] is not None or r["qualifies_for_histogram"]:
                print(
                    f"  VERIFY FAILED: {slug} not a clean quiet state — "
                    f"organic={r['organic_drop_count']}, last={r['last_organic_drop_at']}, "
                    f"qualifies={r['qualifies_for_histogram']}"
                )
                return 1

        # DOW buckets sum to organic_drop_count for every vendor (no drops lost).
        for slug, r in cadence.items():
            if r is None:
                continue
            dow_sum = sum(
                r[k] for k in ("dow_sun", "dow_mon", "dow_tue", "dow_wed", "dow_thu", "dow_fri", "dow_sat")
            )
            if dow_sum != r["organic_drop_count"]:
                print(
                    f"  VERIFY FAILED: {slug} DOW buckets sum {dow_sum} != organic_drop_count "
                    f"{r['organic_drop_count']}"
                )
                return 1

        print(f"  Scope B: qualifies_for_histogram = {sorted(qualifiers)} ({b_ms:.0f} ms, {len(slugs)} vendors).")
        print(
            "  Scope B: battlecorals + cornbred = organic 0 / NULL / not-qualifying (quiet); "
            "DOW buckets sum to organic_drop_count fleet-wide."
        )

    print("0062 applied + verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
