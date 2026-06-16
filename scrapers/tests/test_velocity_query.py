"""scrapers/tests/test_velocity_query.py — CTK-161: behavior coverage for the
velocity (listed-and-gone) query (get_velocity_listings, migration 0042; fetched
via content_queries.fetch_velocity).

The load-bearing guarantee is CLAIM-HONESTY: velocity may describe only listings
we genuinely WATCHED appear and go. This test seeds a fixture exercising every
inclusion/exclusion rule into a ROLLED-BACK transaction (no committed writes) and
asserts what the SQL crowns:

  R  real-time-appeared, still-OOS, named   -> INCLUDED, exact timestamps
  F  first-observed-OOS then restocked      -> INCLUDED; first_oos_at is the
                                               transition AFTER first_seen, NOT the
                                               earlier OOS state (the bug a literal
                                               "first false" reading would ship)
  C  cold-start (no successful run finished  -> EXCLUDED (fictional lifespan — we
     before its first in-stock observation)     never saw it appear)
  S  still in stock                          -> EXCLUDED (the piece is not gone)
  U  unnamed (named_coral_id IS NULL)        -> EXCLUDED (can't name the coral)

DB-GATED: requires a live NEON_DATABASE_URL + migration 0042 applied. Skips cleanly
(exit 0) when no DB is reachable or the function is absent — NOT part of the pure
suite. Run where a DB is available:
  python -m scrapers.tests.test_velocity_query
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone

from scrapers.tools.content_queries import fetch_velocity


def _ts(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


# Vendor cold-start scrape: the first-ever successful run for the seeded vendor.
RUN_STARTED = "2026-06-01 00:00:00"
RUN_FINISHED = "2026-06-01 00:05:00"

# Per-listing price_history observations: (in_stock, observed_at).
_LISTINGS = {
    # R — watched it appear (after the cold-start run finished) and go. An
    # intermediate in-stock row (price change) moves last_in_stock_at off
    # first_seen_at, so the uncertainty window is tighter than the lifespan.
    "R": dict(
        in_stock_now=False, named=True,
        ph=[(True, "2026-06-06 12:00:00"), (True, "2026-06-07 12:00:00"),
            (False, "2026-06-08 12:00:00")],
        expect_included=True,
        first_seen="2026-06-06 12:00:00", last_in_stock="2026-06-07 12:00:00",
        first_oos="2026-06-08 12:00:00",
    ),
    # F — first OBSERVED OOS (a prior state), then restocked, then gone. first_oos_at
    # must be the transition AFTER first_seen (06-09), never the earlier 06-05 false.
    "F": dict(
        in_stock_now=False, named=True,
        ph=[(False, "2026-06-05 00:00:00"), (True, "2026-06-06 00:00:00"),
            (False, "2026-06-09 00:00:00")],
        expect_included=True,
        first_seen="2026-06-06 00:00:00", last_in_stock="2026-06-06 00:00:00",
        first_oos="2026-06-09 00:00:00",
    ),
    # C — first in-stock observation during the cold-start scrape (no successful run
    # finished before 00:03). Clean appeared->gone shape, but fictional: excluded.
    "C": dict(
        in_stock_now=False, named=True,
        ph=[(True, "2026-06-01 00:03:00"), (False, "2026-06-08 12:00:00")],
        expect_included=False,
    ),
    # S — still in stock: the piece is not gone.
    "S": dict(
        in_stock_now=True, named=True,
        ph=[(True, "2026-06-06 12:00:00")],
        expect_included=False,
    ),
    # U — unnamed: can't carry the coral identity line.
    "U": dict(
        in_stock_now=False, named=False,
        ph=[(True, "2026-06-06 12:00:00"), (False, "2026-06-08 12:00:00")],
        expect_included=False,
    ),
}


def _seed(cur) -> tuple[dict[str, int], list[int]]:
    """Seed one vendor + its cold-start run + one named_coral + the listings with
    explicit price_history. Returns ({label: listing_id}, [seeded_coral_ids])."""
    cur.execute(
        "INSERT INTO vendors (slug, display_name, base_url, platform, scrape_method, cadence_label) "
        "VALUES ('ctk161-vel-v0', 'CTK161 Velocity Vendor', 'https://vel.invalid', "
        "'shopify', 'products_json', 'hourly') RETURNING id"
    )
    vendor_id = cur.fetchone()["id"]

    cur.execute(
        "INSERT INTO scraper_runs (vendor_id, started_at, finished_at, status) "
        "VALUES (%s, %s, %s, 'success')",
        (vendor_id, _ts(RUN_STARTED), _ts(RUN_FINISHED)),
    )

    cur.execute(
        "INSERT INTO named_corals (canonical_name, normalized_name, slug, origin_vendor, coral_type, category) "
        "VALUES ('CTK161 Velocity Coral', 'ctk161 velocity coral', 'ctk161-velocity-coral', "
        "'velocity', 'lps', 1) RETURNING id"
    )
    coral_id = cur.fetchone()["id"]

    ids: dict[str, int] = {}
    for label, spec in _LISTINGS.items():
        cur.execute(
            "INSERT INTO vendor_listings "
            "(vendor_id, product_url, raw_title, normalized_title, in_stock, current_price, named_coral_id) "
            "VALUES (%s, %s, %s, %s, %s, 100, %s) RETURNING id",
            (
                vendor_id,
                f"https://vel.invalid/p/{label}",
                f"velocity listing {label}",
                f"velocity listing {label}",
                spec["in_stock_now"],
                coral_id if spec["named"] else None,
            ),
        )
        lid = cur.fetchone()["id"]
        ids[label] = lid
        for in_stock, observed_at in spec["ph"]:
            cur.execute(
                "INSERT INTO price_history (listing_id, price, in_stock, observed_at) "
                "VALUES (%s, 100, %s, %s)",
                (lid, in_stock, _ts(observed_at)),
            )
    return ids, [coral_id]


def test_velocity_query(conn) -> None:
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            ids, coral_ids = _seed(cur)

            # Read the crowns, isolated to the seeded coral (so production rows don't
            # leak in). fetch_velocity is the production path; filter after.
            rows = [r for r in fetch_velocity(conn) if r["named_coral_id"] in coral_ids]

        by_id = {r["id"]: r for r in rows}
        for label, spec in _LISTINGS.items():
            lid = ids[label]
            present = lid in by_id
            assert present == spec["expect_included"], (
                f"listing {label} (id {lid}): expected "
                f"{'INCLUDED' if spec['expect_included'] else 'EXCLUDED'}, "
                f"got {'INCLUDED' if present else 'EXCLUDED'}"
            )
            if not spec["expect_included"]:
                continue
            row = by_id[lid]
            for field, want in (
                ("first_seen_at", spec["first_seen"]),
                ("last_in_stock_at", spec["last_in_stock"]),
                ("first_oos_at", spec["first_oos"]),
            ):
                assert row[field] == _ts(want), (
                    f"listing {label}: {field} = {row[field]}, want {_ts(want)}"
                )
            # The honesty invariant the whole format rests on.
            assert row["first_seen_at"] <= row["last_in_stock_at"] < row["first_oos_at"], (
                f"listing {label}: lifecycle invariant violated"
            )
    finally:
        conn.rollback()


def _run_all() -> int:
    try:
        from scrapers.common import db
        conn = db.get_conn()
    except Exception as e:  # noqa: BLE001 — no DB reachable -> skip, not fail
        print(f"SKIP test_velocity_query: no DB ({type(e).__name__}: {e})")
        return 0

    try:
        test_velocity_query(conn)
        print("ok   test_velocity_query")
        print("\n1/1 passed")
        return 0
    except AssertionError as e:
        print(f"FAIL test_velocity_query: {e}")
        return 1
    except Exception as e:  # noqa: BLE001
        import psycopg
        if isinstance(e, psycopg.errors.UndefinedFunction):
            print("SKIP test_velocity_query: migration 0042 not applied "
                  "(get_velocity_listings absent)")
            return 0
        print(f"ERROR test_velocity_query: {type(e).__name__}: {e}")
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(_run_all())
