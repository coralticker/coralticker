"""scrapers/tests/test_price_drops_rpc_floor.py — CTK-124 Session 3b pins.

Four pins on the migration-0035 get_recent_price_drops(integer) body:

  1. Floor admits the EXACTLY-5% boundary row (compare_at = current *
     1.05, inclusive >=) — mirrors the SEMANTIC of the card gate at
     components/listing-card.tsx:71-72, whose executable form is the
     epsilon rewrite (compareAt - current) >= current * 0.05 - 1e-9
     (95898fb; naive *1.05 float math dropped ~29% of integer-dollar 5%
     markdowns). count == render is the invariant. SQL numeric
     arithmetic is exact, so the naive form is the correct mirror here —
     the boundary admits deterministically, no epsilon needed.
  2. Floor rejects the 4.9% row (compare_at = current * 1.049).
  3. ORDER BY tiebreak determinism — two consecutive calls return the
     identical id sequence (event_at DESC, listing_id is a total order;
     the 0033 seed cohort shares one timestamp, so event_at alone was
     planner-dependent).
  4. Tied-onset relative order — two seeded rows sharing one onset must
     render lower-listing_id first. Pin 3 alone can pass on a planner
     that happens to be stable; this one fails the moment the tiebreak
     is removed (close-fold /code-review rider (e)).

Requires migration 0035 applied (floor + tiebreak live in the function
body) — run AFTER scripts/apply_migration_0035.py.

Test rows are seeded on the active=false '_ctk124_test' vendor with
in_stock=true and an in-window onset, so they are RPC-visible for the
seconds they exist (the function has no vendors.active predicate).
Cleanup runs in finally; the live /deals ISR window (300s) makes a
transient capture unlikely and self-healing.

Hits live Neon Postgres via psycopg. Mirrors
test_markdown_started_at_capture.py shape. Pytest-discovery requires a
`conn` + `vendor` fixture pair the project does not declare globally;
standalone-mode main() builds them inline.

Runnable as:
  python -m scrapers.tests.test_price_drops_rpc_floor
"""

from __future__ import annotations

import sys
import traceback
from decimal import Decimal

from scrapers.common import db

try:
    import pytest
    mark_requires_db = pytest.mark.requires_db
except ImportError:
    mark_requires_db = lambda f: f


TEST_VENDOR_SLUG = "_ctk124_test"
URL_EXACT_5PCT = "https://example.test/p/floor-pin-exact-5pct"
URL_SUB_5PCT = "https://example.test/p/floor-pin-sub-5pct"
URL_TIE_A = "https://example.test/p/tie-pin-a"
URL_TIE_B = "https://example.test/p/tie-pin-b"
WINDOW_DAYS = 7


def _setup_test_vendor(conn) -> dict:
    """Idempotent test-vendor setup (shared slug with the capture pins)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, slug FROM vendors WHERE slug = %s",
            (TEST_VENDOR_SLUG,),
        )
        existing = cur.fetchall()
    if existing:
        return existing[0]
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO vendors "
            "(slug, display_name, base_url, platform, scrape_method, "
            "cadence_label, image_strategy, active) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
            "RETURNING id, slug",
            (
                TEST_VENDOR_SLUG,
                "CTK-124 test vendor",
                "https://example.test",
                "shopify",
                "products_json",
                "daily",
                "mirror",
                False,
            ),
        )
        return cur.fetchone()


def _wipe_listings(conn, vendor_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM vendor_listings WHERE vendor_id = %s", (vendor_id,))


def _seed_markdown_row(conn, vendor_id: int, product_url: str, *,
                       current: Decimal, compare_at: Decimal,
                       onset=None) -> int:
    """INSERT an in-stock row with an in-window onset; returns id.

    onset: explicit timestamp for the tie pin (the autocommit connection
    gives each INSERT its own transaction, so now() differs per call —
    a shared tie timestamp must be passed in). None = now() - 1h.
    """
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO vendor_listings "
            "(vendor_id, product_url, raw_title, normalized_title, "
            "current_price, currency, in_stock, compare_at_price, markdown_started_at) "
            "VALUES (%s, %s, %s, %s, %s, 'USD', true, %s, "
            "COALESCE(%s, now() - interval '1 hour')) "
            "RETURNING id",
            (vendor_id, product_url, "Floor Pin Coral", "floor pin coral",
             current, compare_at, onset),
        )
        return cur.fetchone()["id"]


def _rpc_ids(conn) -> list[int]:
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM get_recent_price_drops(%s)", (WINDOW_DAYS,))
        return [r["id"] for r in cur.fetchall()]


# ─── Floor boundary ───────────────────────────────────────────────────────────

@mark_requires_db
def test_floor_admits_exact_5pct_row(conn, vendor):
    """Pin 1 — INCLUSIVE >=: 105.00 vs 100.00 is exactly the boundary and
    must be in the output (numeric arithmetic is exact; 100.00 * 1.05 is
    precisely 105.0000)."""
    _wipe_listings(conn, vendor["id"])
    lid = _seed_markdown_row(conn, vendor["id"], URL_EXACT_5PCT,
                             current=Decimal("100.00"), compare_at=Decimal("105.00"))
    assert lid in _rpc_ids(conn), (
        "exactly-5% markdown row must ADMIT (floor is inclusive >=, "
        "mirroring the components/listing-card.tsx:71-72 epsilon gate's "
        "semantic — SQL numeric is exact, no epsilon needed)"
    )


@mark_requires_db
def test_floor_rejects_sub_5pct_row(conn, vendor):
    """Pin 2 — 104.90 vs 100.00 (4.9%) sits below the floor and must be
    absent (a sub-floor row would count into the eyebrow without
    rendering a price-treatment card — count != render)."""
    _wipe_listings(conn, vendor["id"])
    lid = _seed_markdown_row(conn, vendor["id"], URL_SUB_5PCT,
                             current=Decimal("100.00"), compare_at=Decimal("104.90"))
    assert lid not in _rpc_ids(conn), (
        "4.9% markdown row must REJECT (below the 5% card-gate floor)"
    )


# ─── Tiebreak determinism ─────────────────────────────────────────────────────

@mark_requires_db
def test_order_is_deterministic_across_calls(conn, vendor):
    """Pin 3 — (event_at DESC, listing_id) is a total order; two
    consecutive calls must return the identical id sequence even while
    the seed cohort shares a single event_at."""
    seq_a = _rpc_ids(conn)
    seq_b = _rpc_ids(conn)
    assert seq_a == seq_b, (
        "id sequences diverged between consecutive calls — tiebreak not total"
    )


@mark_requires_db
def test_tied_onset_orders_by_listing_id(conn, vendor):
    """Pin 4 — seed two rows sharing ONE onset timestamp (the seed-cohort
    tie shape); the lower listing_id must render first per ORDER BY
    r.event_at DESC, r.listing_id. Pin 3 can pass on a coincidentally
    stable planner — this pin fails the moment the tiebreak is removed."""
    _wipe_listings(conn, vendor["id"])
    with conn.cursor() as cur:
        cur.execute("SELECT now() - interval '1 hour' AS ts")
        tie_ts = cur.fetchone()["ts"]
    id_a = _seed_markdown_row(conn, vendor["id"], URL_TIE_A,
                              current=Decimal("100.00"),
                              compare_at=Decimal("150.00"), onset=tie_ts)
    id_b = _seed_markdown_row(conn, vendor["id"], URL_TIE_B,
                              current=Decimal("100.00"),
                              compare_at=Decimal("150.00"), onset=tie_ts)
    ids = _rpc_ids(conn)
    assert id_a in ids and id_b in ids, "both tie rows must be in the output"
    lo, hi = sorted((id_a, id_b))
    assert ids.index(lo) < ids.index(hi), (
        "tied-onset rows must order by listing_id ascending — tiebreak missing"
    )


def main() -> int:
    with db.get_conn() as conn:
        vendor = _setup_test_vendor(conn)
        print(f"test vendor: id={vendor['id']} slug={vendor['slug']}")

        tests = [
            test_floor_admits_exact_5pct_row,
            test_floor_rejects_sub_5pct_row,
            test_order_is_deterministic_across_calls,
            test_tied_onset_orders_by_listing_id,
        ]
        failures = []
        for fn in tests:
            name = fn.__name__
            try:
                fn(conn, vendor)
                print(f"  [PASS] {name}")
            except AssertionError as e:
                print(f"  [FAIL] {name}: {e}")
                failures.append((name, str(e)))
            except Exception as e:  # noqa: BLE001
                print(f"  [ERROR] {name}: {type(e).__name__}: {e}")
                traceback.print_exc()
                failures.append((name, f"{type(e).__name__}: {e}"))
            finally:
                try:
                    _wipe_listings(conn, vendor["id"])
                except Exception as e:  # noqa: BLE001
                    print(f"  [cleanup-warn] {name}: {e}")

        print()
        if failures:
            print(f"{len(failures)}/{len(tests)} tests failed:")
            for name, msg in failures:
                print(f"  - {name}: {msg[:200]}")
            return 1
        print(f"all {len(tests)} tests passed")
        return 0


if __name__ == "__main__":
    sys.exit(main())
