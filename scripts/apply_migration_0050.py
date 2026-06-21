"""Apply migration 0050 — CTK-162 (b): per-vendor price time-series function.

Adds get_coral_price_by_vendor(named_coral_id, window) — for each (day, vendor)
the cheapest in-stock price across that vendor's listings of the coral, via the
same LOCF pick as 0049's get_coral_price_envelope. The chart draws one line per
vendor with the envelope floor underneath.

CREATE OR REPLACE (re-runnable, brand-new function, no signature change). No live
caller yet — the per-vendor chart is the downstream build — so applying early is
safe and there is no apply-pre-push sequencing gate. Uses
scrapers.common.db.get_conn per the CTK-061 single-statement path. Mirrors
apply_migration_0049.py shape.

Verification (the load-bearing one is the LAST):
  - function present in pg_proc after apply
  - callable against a real multi-vendor coral and internally coherent:
      * days non-decreasing, (day, vendor_slug) ordering holds
      * every min_price non-null and > 0, every listing_count >= 1
  - CONSISTENCY-BY-CONSTRUCTION (C2): for every day, MIN(min_price) across this
    function's per-vendor rows EQUALS get_coral_price_envelope.min_price for that
    day. This is the whole point of cloning the envelope's LATERAL + gate verbatim
    — the rendered floor is the min of the per-vendor lines, so they must agree by
    construction. A mismatch means the pick or gate drifted between the twins.
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
    / "0050_coral_price_by_vendor.sql"
)

EXPECTED_FUNC = "get_coral_price_by_vendor"


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
            cur.execute("SELECT proname FROM pg_proc WHERE proname = %s", (EXPECTED_FUNC,))
            if not cur.fetchone():
                print(f"  VERIFY FAILED: {EXPECTED_FUNC} missing after apply")
                return 1
        print(f"  present: {EXPECTED_FUNC}")

        # Pick a coral that genuinely EXERCISES the per-vendor path: more than one
        # distinct vendor AND at least one in-stock non-null observation (so the
        # function is non-empty AND the cross-vendor floor really is a min over
        # multiple vendor lines). Most vendors, then most listings, then most ph
        # rows. Fall back to any coral with ph rows and warn LOUDLY that the
        # multi-vendor consistency check is unexercised — never let a degenerate
        # single-vendor pick masquerade as a real C2 verify.
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
            print("0050 applied + verified (presence).")
            return 0

        coral_id = pick["id"]
        print(
            f"  smoke coral: named_coral_id={coral_id} "
            f"({pick['n_vendors']} vendor(s), {pick['n_listings']} listing(s), "
            f"{pick['ph_rows']} ph row(s))"
        )
        if degenerate:
            print(
                "  WARNING: no coral has >1 vendor with in-stock history — the "
                "MULTI-VENDOR consistency check (C2) is UNEXERCISED by this smoke "
                "(a single-vendor per-vendor min trivially equals the envelope)."
            )

        # Pin the session tz so this function's `days.d + 1` timestamptz cast and
        # get_coral_price_envelope's agree on "midnight of d+1" — both twins share
        # the same boundary, so a tz drift here would desync them spuriously.
        with conn.cursor() as cur:
            cur.execute("SET TIME ZONE 'UTC'")

        # get_coral_price_by_vendor — full history.
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM get_coral_price_by_vendor(%s::int, NULL)", (coral_id,)
            )
            bv = cur.fetchall()

        # Ordering: (vendor_id, day) non-decreasing as the function ORDER BYs
        # (vendor-major per the CTK-162 (b) directive — each vendor's line is a
        # contiguous time-ordered run).
        order_key = [(r["vendor_id"], r["day"]) for r in bv]
        if order_key != sorted(order_key):
            print("  VERIFY FAILED: get_coral_price_by_vendor rows not ordered "
                  "by (vendor_id, day)")
            return 1

        # Every emitted row is a real in-stock per-vendor min: positive price, at
        # least one listing behind it.
        bad = [
            r for r in bv
            if r["min_price"] is None or r["min_price"] <= 0 or r["listing_count"] < 1
        ]
        if bad:
            print(
                f"  VERIFY FAILED: {len(bad)} per-vendor row(s) with null/<=0 "
                f"min_price or listing_count < 1; first {bad[0]['day']} "
                f"vendor={bad[0]['vendor_slug']}"
            )
            return 1
        n_days = len({r["day"] for r in bv})
        n_vendors = len({r["vendor_id"] for r in bv})
        print(
            f"  get_coral_price_by_vendor(): {len(bv)} row(s) across {n_days} day(s) "
            f"x {n_vendors} vendor(s), order + positivity hold"
        )

        # ── C2: consistency-by-construction against get_coral_price_envelope ──
        # The whole reason this function clones the envelope's LATERAL + gate: the
        # rendered floor is the min of the per-vendor lines, so for every day,
        # MIN(min_price) over this function's rows MUST equal the envelope's
        # min_price for that day. A mismatch means the pick/gate drifted apart.
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM get_coral_price_envelope(%s::int, NULL)", (coral_id,)
            )
            env = cur.fetchall()

        if not env and not bv:
            print(
                "  WARNING: both envelope and per-vendor are EMPTY for the smoke "
                "coral (no in-stock history) — C2 UNEXERCISED. Not a verify."
            )
            print("0050 applied + verified (presence + shape; C2 unexercised).")
            return 0

        env_by_day = {r["day"]: r["min_price"] for r in env}

        # Fold the per-vendor rows to a per-day min.
        floor_by_day: dict[str, object] = {}
        for r in bv:
            cur_min = floor_by_day.get(r["day"])
            if cur_min is None or r["min_price"] < cur_min:
                floor_by_day[r["day"]] = r["min_price"]

        # Day sets must match exactly: a day present in one twin but not the other
        # is itself a construction divergence (the honest-gap property must agree).
        env_days = set(env_by_day)
        bv_days = set(floor_by_day)
        only_env = sorted(env_days - bv_days)
        only_bv = sorted(bv_days - env_days)
        if only_env or only_bv:
            print(
                f"  VERIFY FAILED (C2): day sets differ — "
                f"{len(only_env)} day(s) in envelope only "
                f"(first {only_env[0] if only_env else '-'}), "
                f"{len(only_bv)} day(s) in per-vendor only "
                f"(first {only_bv[0] if only_bv else '-'})"
            )
            return 1

        mismatches = [
            (d, floor_by_day[d], env_by_day[d])
            for d in env_days
            if floor_by_day[d] != env_by_day[d]
        ]
        if mismatches:
            d, got, exp = mismatches[0]
            print(
                f"  VERIFY FAILED (C2): MIN(per-vendor min_price) != envelope "
                f"min_price on {len(mismatches)} day(s); first day={d} "
                f"per-vendor-floor={got} envelope={exp}"
            )
            return 1
        print(
            f"  C2 OK: MIN(per-vendor min) == envelope min on all {len(env_days)} "
            f"day(s) — floor-equals-min-of-lines holds by construction"
        )

        # ── Raw-row recompute ORACLE (review finding #6) ──────────────────────
        # C2 above is SQL-vs-SQL: both twins share the LOCF construction, so a bug
        # IN that construction passes clean (both are wrong identically). This
        # recomputes the per-(day, vendor) min + listing_count straight from raw
        # price_history rows in Python — an INDEPENDENT implementation of "latest
        # in-stock state as of end-of-day d, per vendor" — so the proof has a
        # tz-independent ground truth, not a mirror of itself. Mirrors the
        # expected_min/by_listing oracle in apply_migration_0049.py, lifted to the
        # per-vendor grain. Session is already SET TIME ZONE 'UTC' above, matching
        # the UTC boundary computed here.
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT ph.id, ph.listing_id, vl.vendor_id,
                       ph.observed_at, ph.price, ph.in_stock
                FROM vendor_listings vl
                JOIN price_history ph ON ph.listing_id = vl.id
                WHERE vl.named_coral_id = %s
                """,
                (coral_id,),
            )
            raw = cur.fetchall()

        by_listing: dict[int, list] = {}
        listing_vendor: dict[int, int] = {}
        for r in raw:
            by_listing.setdefault(r["listing_id"], []).append(r)
            listing_vendor[r["listing_id"]] = r["vendor_id"]

        def expected_by_vendor(day_str: str) -> dict[int, tuple]:
            # vendor_id -> (min_price, listing_count) as of end-of-day day_str.
            # boundary = midnight of day+1 UTC, matching the function's
            # `days.d + 1`::timestamptz tiebreak (ph.id DESC) under UTC.
            day = datetime.strptime(day_str, "%Y-%m-%d").date()
            boundary = datetime.combine(
                day + timedelta(days=1), dtime.min, tzinfo=timezone.utc
            )
            per_vendor: dict[int, list] = {}
            for listing_id, rows in by_listing.items():
                prior = [x for x in rows if x["observed_at"] < boundary]
                if not prior:
                    continue
                # Match the SQL tiebreak: latest observed_at, then highest id.
                latest = max(prior, key=lambda x: (x["observed_at"], x["id"]))
                if latest["in_stock"] and latest["price"] is not None:
                    per_vendor.setdefault(listing_vendor[listing_id], []).append(
                        latest["price"]
                    )
            return {vid: (min(ps), len(ps)) for vid, ps in per_vendor.items()}

        def check_oracle(rows, label: str) -> bool:
            # Compare the function's (day, vendor) cells against the raw recompute
            # over exactly the days the function emitted. Checks both cell-set
            # parity (honest-gap correctness) and value correctness (min + count).
            fn = {
                (r["day"], r["vendor_id"]): (r["min_price"], r["listing_count"])
                for r in rows
            }
            exp: dict[tuple, tuple] = {}
            for day_str in {r["day"] for r in rows}:
                for vid, cell in expected_by_vendor(day_str).items():
                    exp[(day_str, vid)] = cell
            only_fn = sorted(set(fn) - set(exp))
            only_exp = sorted(set(exp) - set(fn))
            if only_fn or only_exp:
                print(
                    f"  VERIFY FAILED ({label} oracle): (day,vendor) cell sets "
                    f"differ — {len(only_fn)} in fn only "
                    f"(first {only_fn[0] if only_fn else '-'}), "
                    f"{len(only_exp)} in oracle only "
                    f"(first {only_exp[0] if only_exp else '-'})"
                )
                return False
            bad = [(k, fn[k], exp[k]) for k in fn if fn[k] != exp[k]]
            if bad:
                k, got, want = bad[0]
                print(
                    f"  VERIFY FAILED ({label} oracle): {len(bad)} cell(s) mismatch "
                    f"raw recompute; first (day={k[0]}, vendor={k[1]}) "
                    f"fn=(min,count){got} oracle={want}"
                )
                return False
            print(
                f"  {label} oracle OK: all {len(fn)} (day,vendor) cell(s) match the "
                f"raw price_history recompute (min + listing_count, tz-independent)"
            )
            return True

        if not check_oracle(bv, "full-history"):
            return 1

        # ── Windowed smoke + oracle ───────────────────────────────────────────
        # Start-clamp: a windowed call must not emit a day before
        # current_date - WINDOW. Oracle: the windowed cells must ALSO match the raw
        # recompute (which reaches back before the window from raw rows), proving
        # the LOCF carried the level INTO the window edge rather than restarting —
        # the previous windowed leg compared to nothing.
        WINDOW = 30
        with conn.cursor() as cur:
            cur.execute("SELECT current_date AS d")
            today = cur.fetchone()["d"]
            cur.execute(
                "SELECT * FROM get_coral_price_by_vendor(%s::int, %s)",
                (coral_id, WINDOW),
            )
            wbv = cur.fetchall()

        clamp_floor = today - timedelta(days=WINDOW)
        early = [
            r["day"] for r in wbv
            if datetime.strptime(r["day"], "%Y-%m-%d").date() < clamp_floor
        ]
        if early:
            print(
                f"  VERIFY FAILED: windowed per-vendor emitted {len(early)} day(s) "
                f"before the clamp floor {clamp_floor}; first {early[0]}"
            )
            return 1
        if wbv and not check_oracle(wbv, "windowed"):
            return 1
        print(
            f"  windowed smoke (w={WINDOW}): {len(wbv)} row(s), start clamped "
            f">= {clamp_floor}, cells match raw recompute (reach-back holds)"
        )

    print("0050 applied + verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
