"""scrapers/tests/test_price_drops_rpc_union.py — CTK-208 ports of two orphan
guarantees from the deleted apply_migration_0026/0033/0035 verify blocks.

These exercise BEHAVIOR of get_recent_price_drops(integer), not its shape — each
fails if the underlying predicate is removed from the function body:

  O1 (was 0026 verify) — the OOS exclusion. Both union arms carry
     `vl.in_stock = true`; an in-window markdown row that is out of stock must NOT
     appear in /deals. test_price_drops_rpc_floor only ever seeded in_stock=true, so
     dropping the `in_stock = true` predicate passed silently before this test.
  O2 (was 0033/0035 verify) — the union has both arms + an honest timestamp + the
     INV-05 auction gate:
       * Arm 1 (LLAG over price_history) emits rows with prior_price NOT NULL.
       * Arm 2 (active markdown ≥ 5% floor) emits rows with prior_price NULL.
       * event_at is never NULL (both arms project a real onset).
       * INV-05: a row whose listing has auction_end_time set is excluded (the live
         body gates on `auction_end_time IS NULL`, both arms — CTK-208 verified
         against pg_get_functiondef 2026-06-28).

Live Neon, isolated active=false vendor (`_ctk208_pricedrops_test`, its own slug so it
never shares rows with test_price_drops_rpc_floor's _ctk124_test under the global RPC).
Each test wipes + reseeds; assertions scope to this vendor's rows where the RPC output
is global. conftest.py provides conn + vendor (delegating to _setup_test_vendor below).

Runnable as:
  python -m scrapers.tests.test_price_drops_rpc_union
"""

from __future__ import annotations

import os
import sys
import traceback
from decimal import Decimal

from scrapers.common import db

try:
    import pytest
    mark_requires_db = pytest.mark.requires_db
except ImportError:
    mark_requires_db = lambda f: f


TEST_VENDOR_SLUG = "_ctk208_pricedrops_test"
WINDOW_DAYS = 7


def _setup_test_vendor(conn) -> dict:
    """Idempotent active=false test-vendor setup (conftest delegates `vendor` here)."""
    with conn.cursor() as cur:
        cur.execute("SELECT id, slug FROM vendors WHERE slug = %s", (TEST_VENDOR_SLUG,))
        existing = cur.fetchall()
    if existing:
        return existing[0]
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO vendors "
            "(slug, display_name, base_url, platform, scrape_method, "
            "cadence_label, image_strategy, active) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id, slug",
            (TEST_VENDOR_SLUG, "CTK-208 price-drops test vendor", "https://example.test",
             "shopify", "products_json", "daily", "mirror", False),
        )
        return cur.fetchone()


def _wipe_listings(conn, vendor_id: int) -> None:
    # ON DELETE CASCADE clears price_history for these listings.
    with conn.cursor() as cur:
        cur.execute("DELETE FROM vendor_listings WHERE vendor_id = %s", (vendor_id,))


def _seed_markdown(conn, vendor_id: int, url: str, *, current: Decimal, compare_at: Decimal,
                   in_stock: bool = True, auction_end=None) -> int:
    """Arm-2 (markdown) row: compare_at ≥ current, markdown onset in-window."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO vendor_listings "
            "(vendor_id, product_url, raw_title, normalized_title, current_price, currency, "
            "in_stock, compare_at_price, markdown_started_at, auction_end_time) "
            "VALUES (%s, %s, %s, %s, %s, 'USD', %s, %s, now() - interval '1 hour', %s) "
            "RETURNING id",
            (vendor_id, url, "Union Pin Coral", "union pin coral",
             current, in_stock, compare_at, auction_end),
        )
        return cur.fetchone()["id"]


def _seed_lag_drop(conn, vendor_id: int, url: str, *, prior: Decimal, new: Decimal,
                   in_stock: bool = True, auction_end=None) -> int:
    """Arm-1 (CT-observed drop) row: a listing + two in-window price_history points
    (prior then new, new < prior) so the LAG CTE emits prior_price NOT NULL. in_stock /
    auction_end parameterize the drop arm's own INV-05 predicates (vl.in_stock = true
    AND vl.auction_end_time IS NULL) for the exclusion variants."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO vendor_listings "
            "(vendor_id, product_url, raw_title, normalized_title, current_price, currency, "
            "in_stock, auction_end_time) VALUES (%s, %s, %s, %s, %s, 'USD', %s, %s) RETURNING id",
            (vendor_id, url, "Union LAG Coral", "union lag coral", new, in_stock, auction_end),
        )
        lid = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO price_history (listing_id, price, in_stock, observed_at) VALUES "
            "(%s, %s, true, now() - interval '2 hours'), "
            "(%s, %s, true, now() - interval '1 hour')",
            (lid, prior, lid, new),
        )
    return lid


def _rpc_rows(conn) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, vendor_id, prior_price, event_at FROM get_recent_price_drops(%s)",
            (WINDOW_DAYS,),
        )
        return cur.fetchall()


@mark_requires_db
def test_oos_markdown_excluded(conn, vendor):
    """O1 — an out-of-stock in-window markdown row must NOT appear; an otherwise
    identical in-stock row must. Deleting `vl.in_stock = true` from the arms admits
    the OOS row (click-through-to-sold-out on /deals) and fails this."""
    _wipe_listings(conn, vendor["id"])
    oos = _seed_markdown(conn, vendor["id"], "https://example.test/p/o1-oos",
                         current=Decimal("100.00"), compare_at=Decimal("150.00"), in_stock=False)
    live = _seed_markdown(conn, vendor["id"], "https://example.test/p/o1-instock",
                          current=Decimal("100.00"), compare_at=Decimal("150.00"), in_stock=True)
    ids = [r["id"] for r in _rpc_rows(conn)]
    assert oos not in ids, "OOS markdown row leaked into get_recent_price_drops (in_stock gate removed?)"
    assert live in ids, "in-stock control markdown should be present — seed/window sanity"


@mark_requires_db
def test_union_arms_present_with_honest_timestamp(conn, vendor):
    """O2 (union) — both arms fire and every row carries a real onset. A LAG row
    (prior_price NOT NULL) AND a markdown row (prior_price NULL) both surface; no row
    has a NULL event_at. Deleting either arm, or breaking the event_at projection,
    fails this."""
    _wipe_listings(conn, vendor["id"])
    lag = _seed_lag_drop(conn, vendor["id"], "https://example.test/p/o2-lag",
                         prior=Decimal("120.00"), new=Decimal("100.00"))
    md = _seed_markdown(conn, vendor["id"], "https://example.test/p/o2-md",
                        current=Decimal("100.00"), compare_at=Decimal("150.00"))
    mine = {r["id"]: r for r in _rpc_rows(conn) if r["vendor_id"] == vendor["id"]}
    assert lag in mine, "LAG-arm (CT-observed drop) row missing — arm 1 dropped?"
    assert md in mine, "markdown-arm row missing — arm 2 dropped?"
    assert mine[lag]["prior_price"] is not None, "LAG-arm row must carry prior_price (NOT NULL)"
    assert mine[md]["prior_price"] is None, "markdown-arm row must carry prior_price NULL"
    assert all(r["event_at"] is not None for r in mine.values()), (
        "every price-drop row must carry a real event_at (honest timestamp)"
    )


@mark_requires_db
def test_auction_markdown_excluded(conn, vendor):
    """O2 (INV-05) — a markdown row whose listing has auction_end_time set is excluded
    (auction prices are on-request, never a fixed-price deal). A non-auction control
    with the same markdown is present. Deleting `auction_end_time IS NULL` admits the
    auction row and fails this."""
    _wipe_listings(conn, vendor["id"])
    auction = _seed_markdown(conn, vendor["id"], "https://example.test/p/o2-auction",
                             current=Decimal("100.00"), compare_at=Decimal("150.00"),
                             auction_end="2099-12-31T23:59:59+00:00")
    fixed = _seed_markdown(conn, vendor["id"], "https://example.test/p/o2-fixed",
                           current=Decimal("100.00"), compare_at=Decimal("150.00"))
    ids = [r["id"] for r in _rpc_rows(conn)]
    assert auction not in ids, "auction markdown row leaked into /deals (auction_end_time gate removed?)"
    assert fixed in ids, "non-auction control markdown should be present — seed/window sanity"


@mark_requires_db
def test_drop_arm_oos_excluded(conn, vendor):
    """O1 (drop arm) — a CT-observed price drop on an OOS listing must be excluded.
    The markdown-arm OOS case (test_oos_markdown_excluded) doesn't exercise the drop
    arm's own `vl.in_stock = true` (0035 drop-arm JOIN predicate); this restores the
    narrowed 0033/0035 both-arms coverage. Fails if that predicate is removed."""
    _wipe_listings(conn, vendor["id"])
    oos = _seed_lag_drop(conn, vendor["id"], "https://example.test/p/o1-drop-oos",
                         prior=Decimal("120.00"), new=Decimal("100.00"), in_stock=False)
    live = _seed_lag_drop(conn, vendor["id"], "https://example.test/p/o1-drop-instock",
                          prior=Decimal("120.00"), new=Decimal("100.00"), in_stock=True)
    ids = [r["id"] for r in _rpc_rows(conn)]
    assert oos not in ids, "OOS LAG-drop row leaked into /deals (drop-arm in_stock gate removed?)"
    assert live in ids, "in-stock control LAG-drop should be present — seed/window sanity"


@mark_requires_db
def test_drop_arm_auction_excluded(conn, vendor):
    """O2 (drop arm INV-05) — a CT-observed price drop on an auction-ended listing
    must be excluded. Exercises the drop arm's own `vl.auction_end_time IS NULL`
    (0035 drop-arm JOIN predicate), distinct from the markdown-arm auction case. Fails
    if that predicate is removed."""
    _wipe_listings(conn, vendor["id"])
    auction = _seed_lag_drop(conn, vendor["id"], "https://example.test/p/o2-drop-auction",
                             prior=Decimal("120.00"), new=Decimal("100.00"),
                             auction_end="2020-01-01T00:00:00+00:00")
    fixed = _seed_lag_drop(conn, vendor["id"], "https://example.test/p/o2-drop-fixed",
                           prior=Decimal("120.00"), new=Decimal("100.00"))
    ids = [r["id"] for r in _rpc_rows(conn)]
    assert auction not in ids, "auction LAG-drop row leaked into /deals (drop-arm auction_end_time gate removed?)"
    assert fixed in ids, "non-auction control LAG-drop should be present — seed/window sanity"


try:
    import pytest as _pytest_cleanup

    @_pytest_cleanup.fixture(scope="module", autouse=True)
    def _module_cleanup():
        """CTK-208 /code-review #6 — wipe this vendor after the suite. main()'s
        per-test finally-wipe does NOT run under pytest, so leaked in-stock seed rows
        on _ctk208_pricedrops_test would survive into the global get_recent_price_drops
        output and red the test_price_drops_rpc_floor determinism test."""
        yield
        # CTK-215: this teardown DELETEs on the TEST branch via get_test_conn; key the
        # guard off TEST_DATABASE_URL so it no-ops when there is no test target (and
        # never opens a prod connection to clean up — NEON_DATABASE_URL is prod).
        if not os.environ.get("TEST_DATABASE_URL"):
            return
        with db.get_test_conn() as c:
            with c.cursor() as cur:
                cur.execute(
                    "DELETE FROM vendor_listings WHERE vendor_id IN "
                    "(SELECT id FROM vendors WHERE slug = %s)",
                    (TEST_VENDOR_SLUG,),
                )
except ImportError:
    pass


def main() -> int:
    with db.get_test_conn() as conn:
        vendor = _setup_test_vendor(conn)
        print(f"test vendor: id={vendor['id']} slug={vendor['slug']}")
        tests = [
            test_oos_markdown_excluded,
            test_union_arms_present_with_honest_timestamp,
            test_auction_markdown_excluded,
            test_drop_arm_oos_excluded,
            test_drop_arm_auction_excluded,
        ]
        failures = []
        for fn in tests:
            try:
                fn(conn, vendor)
                print(f"  [PASS] {fn.__name__}")
            except AssertionError as e:
                print(f"  [FAIL] {fn.__name__}: {e}")
                failures.append(fn.__name__)
            except Exception as e:  # noqa: BLE001
                print(f"  [ERROR] {fn.__name__}: {type(e).__name__}: {e}")
                traceback.print_exc()
                failures.append(fn.__name__)
            finally:
                try:
                    _wipe_listings(conn, vendor["id"])
                except Exception as e:  # noqa: BLE001
                    print(f"  [cleanup-warn] {fn.__name__}: {e}")
        print()
        print(f"{len(tests) - len(failures)}/{len(tests)} passed")
        return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
