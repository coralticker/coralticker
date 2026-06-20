"""Apply migration 0049 — CTK-162 (b): per-coral price time-series functions.

Adds two STABLE read functions over the append-only price_history table for the
/coral/[slug]/price-history template (plan.md scope b):
  1. get_coral_price_history(named_coral_id, window) — per-listing step series
     (one row per observation; in_stock per point for OOS-gap rendering).
  2. get_coral_price_envelope(named_coral_id, window) — cross-vendor daily-min
     floor with LOCF (last-observation-carried-forward over the sparse,
     change-only table); OOS/null listings drop out of the per-day min, all-OOS
     days emit no row.

CREATE OR REPLACE (re-runnable, no signature change). No live caller yet — the
price-history template is the downstream build — so applying early is safe and
there is no apply-pre-push sequencing gate. Uses scrapers.common.db.get_conn per
the CTK-061 single-statement path. Mirrors apply_migration_0046.py shape.

Verification:
  - both functions present in pg_proc after apply
  - both callable against a real coral (picked = most listings, then most
    price_history rows) and the output shape is internally coherent:
      * history: ordered by (listing_id, observed_at)
      * envelope: days strictly increasing, every min_price non-null and > 0,
        and min(envelope) >= the coral's cheapest in-stock observation (the
        envelope can never undercut a real in-stock price)
  - GRANTs are in the migration body; a missing GRANT surfaces on the first
    wrapper call, not silently.
"""

from __future__ import annotations

import sys
import time
from datetime import datetime, time as dtime, timedelta, timezone
from pathlib import Path

from scrapers.common.db import get_conn

MIGRATION_PATH = (
    Path(__file__).resolve().parent.parent
    / "supabase"
    / "migrations"
    / "0049_coral_price_history_and_envelope.sql"
)

EXPECTED_FUNCS = ("get_coral_price_history", "get_coral_price_envelope")


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

        # Presence check — both functions.
        for fn in EXPECTED_FUNCS:
            with conn.cursor() as cur:
                cur.execute("SELECT proname FROM pg_proc WHERE proname = %s", (fn,))
                if not cur.fetchone():
                    print(f"  VERIFY FAILED: {fn} missing after apply")
                    return 1
            print(f"  present: {fn}")

        # Pick a coral that genuinely EXERCISES the cross-vendor LOCF path: more
        # than one distinct vendor AND at least one in-stock non-null observation
        # (so the envelope is non-empty). Most vendors, then most listings, then
        # most ph rows. If none qualifies, fall back to any coral with ph rows
        # and warn LOUDLY that the cross-vendor path is unexercised — never let a
        # degenerate (single-vendor / no-in-stock) pick masquerade as a real
        # cross-vendor verify.
        def pick_coral(cur):
            cur.execute(
                """
                SELECT vl.named_coral_id AS id,
                       COUNT(DISTINCT vl.vendor_id) AS n_vendors,
                       COUNT(DISTINCT vl.id)        AS n_listings,
                       COUNT(*)                     AS ph_rows
                FROM vendor_listings vl
                JOIN price_history ph ON ph.listing_id = vl.id
                WHERE vl.named_coral_id IS NOT NULL
                GROUP BY vl.named_coral_id
                HAVING COUNT(DISTINCT vl.vendor_id) > 1
                   AND COUNT(*) FILTER (WHERE ph.in_stock AND ph.price IS NOT NULL) > 0
                ORDER BY n_vendors DESC, n_listings DESC, ph_rows DESC
                LIMIT 1
                """
            )
            return cur.fetchone()

        def pick_any(cur):
            cur.execute(
                """
                SELECT vl.named_coral_id AS id,
                       COUNT(DISTINCT vl.vendor_id) AS n_vendors,
                       COUNT(DISTINCT vl.id)        AS n_listings,
                       COUNT(*)                     AS ph_rows
                FROM vendor_listings vl
                JOIN price_history ph ON ph.listing_id = vl.id
                WHERE vl.named_coral_id IS NOT NULL
                GROUP BY vl.named_coral_id
                ORDER BY n_listings DESC, ph_rows DESC
                LIMIT 1
                """
            )
            return cur.fetchone()

        with conn.cursor() as cur:
            pick = pick_coral(cur)
            degenerate = False
            if not pick:
                pick = pick_any(cur)
                degenerate = True

        if not pick:
            print("  smoke: no matched coral with price_history — presence-only")
            print("0049 applied + verified (presence).")
            return 0

        coral_id = pick["id"]
        print(
            f"  smoke coral: named_coral_id={coral_id} "
            f"({pick['n_vendors']} vendor(s), {pick['n_listings']} listing(s), "
            f"{pick['ph_rows']} ph row(s))"
        )
        if degenerate:
            print(
                "  WARNING: no coral has >1 vendor with in-stock history — "
                "the CROSS-VENDOR envelope path is UNEXERCISED by this smoke "
                "(single-vendor min is a degenerate pass-through)."
            )

        # get_coral_price_history — ordered by (listing_id, observed_at).
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM get_coral_price_history(%s::int, NULL)", (coral_id,)
            )
            hist = cur.fetchall()
        order_key = [(r["listing_id"], r["observed_at"]) for r in hist]
        if order_key != sorted(order_key):
            print("  VERIFY FAILED: get_coral_price_history rows not ordered "
                  "by (listing_id, observed_at)")
            return 1
        print(f"  get_coral_price_history(): {len(hist)} point(s), order holds")

        # Pin the session tz so the function's `days.d + 1` timestamptz cast and
        # the Python recompute boundary below agree on what "midnight of d+1"
        # means. Without this they could diverge by the server's tz offset.
        with conn.cursor() as cur:
            cur.execute("SET TIME ZONE 'UTC'")

        # get_coral_price_envelope — monotonic days, positive non-null mins.
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM get_coral_price_envelope(%s::int, NULL)", (coral_id,)
            )
            env = cur.fetchall()
        days = [r["day"] for r in env]
        if days != sorted(set(days)):
            print("  VERIFY FAILED: get_coral_price_envelope days not strictly "
                  "increasing / has duplicates")
            return 1
        bad = [r for r in env if r["min_price"] is None or r["min_price"] <= 0]
        if bad:
            print(f"  VERIFY FAILED: {len(bad)} envelope day(s) with null/<=0 min_price")
            return 1
        print(f"  get_coral_price_envelope(): {len(env)} day(s), days strict, mins > 0")

        # Independent day-level recompute — the real LOCF + OOS-gate check (the
        # old env_min >= floor was near-tautological; it cannot fail on a
        # carry-forward error). Pull every raw price_history row for the coral's
        # listings, then for each envelope day recompute the expected
        # cross-vendor min the way the function should: per listing take the
        # LATEST row with observed_at < day+1 REGARDLESS of stock, keep it only
        # if that latest state is in_stock with a non-null price, min across
        # listings. A later OOS flip must drop the listing — so this catches the
        # bug where the function carried forward a stale in-stock price past a
        # newer OOS row.
        if env:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT ph.id, ph.listing_id, ph.observed_at, ph.price, ph.in_stock
                    FROM vendor_listings vl
                    JOIN price_history ph ON ph.listing_id = vl.id
                    WHERE vl.named_coral_id = %s
                    """,
                    (coral_id,),
                )
                raw = cur.fetchall()

            # Group raw rows by listing for per-listing "latest as of d" lookups.
            by_listing: dict[int, list] = {}
            for r in raw:
                by_listing.setdefault(r["listing_id"], []).append(r)

            def expected_min(day_str: str) -> float | None:
                # day arrives as TEXT (YYYY-MM-DD) now — parse to a date.
                # boundary = midnight of day+1, UTC, matching the function's
                # `days.d + 1`::timestamptz tiebreak (ph.id DESC) under UTC.
                day = datetime.strptime(day_str, "%Y-%m-%d").date()
                boundary = datetime.combine(
                    day + timedelta(days=1), dtime.min, tzinfo=timezone.utc
                )
                prices = []
                for rows in by_listing.values():
                    prior = [x for x in rows if x["observed_at"] < boundary]
                    if not prior:
                        continue
                    # Match the SQL tiebreak: latest observed_at, then highest id.
                    latest = max(prior, key=lambda x: (x["observed_at"], x["id"]))
                    if latest["in_stock"] and latest["price"] is not None:
                        prices.append(latest["price"])
                return min(prices) if prices else None

            mismatches = []
            for r in env:
                exp = expected_min(r["day"])
                if exp != r["min_price"]:
                    mismatches.append((r["day"], r["min_price"], exp))
            if mismatches:
                print(
                    f"  VERIFY FAILED: {len(mismatches)} day(s) where the function "
                    f"min_price != independent recompute; first: "
                    f"day={mismatches[0][0]} fn={mismatches[0][1]} expected={mismatches[0][2]}"
                )
                return 1
            print(
                f"  envelope recompute: all {len(env)} day(s) match the independent "
                f"latest-state-as-of-day cross-vendor min (LOCF + OOS-gate verified)"
            )
        else:
            # Don't let an empty envelope read as a pass — the LOCF path ran zero
            # days, so nothing was actually exercised.
            print(
                "  WARNING: envelope is EMPTY for the smoke coral — LOCF UNEXERCISED "
                "(no in-stock history). Not a verify."
            )

        # Windowed smoke (item #9) — exercise the GREATEST start-clamp and the
        # reach-back-before-window invariant: a windowed call must clamp the
        # series start to >= current_date - WINDOW, AND every day it emits must
        # carry the SAME min_price as the full-history call for that day (proving
        # the LOCF reached back BEFORE the window boundary rather than restarting
        # mid-level at the window edge).
        if env:
            WINDOW = 30
            with conn.cursor() as cur:
                cur.execute("SELECT current_date AS d")
                today = cur.fetchone()["d"]
                cur.execute(
                    "SELECT * FROM get_coral_price_envelope(%s::int, %s)",
                    (coral_id, WINDOW),
                )
                wenv = cur.fetchall()

            clamp_floor = today - timedelta(days=WINDOW)
            early = [
                r["day"] for r in wenv
                if datetime.strptime(r["day"], "%Y-%m-%d").date() < clamp_floor
            ]
            if early:
                print(
                    f"  VERIFY FAILED: windowed envelope emitted {len(early)} day(s) "
                    f"before the GREATEST clamp floor {clamp_floor}; first {early[0]}"
                )
                return 1

            full_by_day = {r["day"]: r["min_price"] for r in env}
            drift = [
                (r["day"], r["min_price"], full_by_day.get(r["day"]))
                for r in wenv
                if full_by_day.get(r["day"]) != r["min_price"]
            ]
            if drift:
                print(
                    f"  VERIFY FAILED: windowed min_price diverges from full-history "
                    f"on {len(drift)} day(s) (LOCF did not reach before the window); "
                    f"first day={drift[0][0]} windowed={drift[0][1]} full={drift[0][2]}"
                )
                return 1
            print(
                f"  windowed smoke (w={WINDOW}): {len(wenv)} day(s), start clamped "
                f">= {clamp_floor}, all match full-history (reach-back holds)"
            )

    print("0049 applied + verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
