"""scrapers/tests/test_ctk042_is_auction_gate.py — CTK-042 acute auction-leak
gate, writer-side catch-net.

Two halves, both guarding FUTURE entries (the backfill guards the present
population; these guard rows that arrive after deploy):

  1. Parser (no DB): _normalize_product sets is_auction from the SAME
     _is_auction(...) call that nulls current_price. true on a tag-detected
     auction, false on a non-auction, false when auction_detection is
     unconfigured (the permissive default). Reuses the real _is_auction —
     no re-implemented detection.

  2. Diff (live Neon, isolated test vendor): a decision=="new" auction item
     carries is_auction=true through persist_phase_a's UPSERT row-build into
     the vendor_listings row. This is the load-bearing pin — is_auction rides
     the UPSERT path ONLY (not the unchanged-row touch UPDATE), so the
     guarantee is "a NEW auction row lands is_auction=true." Deleting the
     diff.py row-dict key fails this test.

The unchanged-row path is deliberately NOT wired (see diff.py comment + the
feedback_capture_path_unchanged_blind_spot rationale): is_auction is
monotonic, the backfill seeds the population, and any false->true flip
co-occurs with the CTK-160 price null-out -> price_changed -> UPSERT path. A
companion test pins that a NEW non-auction row lands is_auction=false (no
false-positive on fixed-price rows).

Hits live Neon via psycopg, test vendor slug='_ctk042_test' (active=false;
isolated from cron). Mirrors test_persist_phase_a_unchanged_compare_at.py.

Runnable as:
  python -m scrapers.tests.test_ctk042_is_auction_gate
"""

from __future__ import annotations

import sys
import traceback
from decimal import Decimal

from scrapers.common import db
from scrapers.common.diff import ItemDecision, persist_phase_a
from scrapers.common.parse_shopify import _normalize_product

try:
    import pytest
    mark_requires_db = pytest.mark.requires_db
except ImportError:
    mark_requires_db = lambda f: f


BASE = "https://example-reef.com"
AUCTION_DETECTION = {"tags": ["Auction", "active_bidding", "on_auction"], "slug_suffix": "-auc"}

TEST_VENDOR_SLUG = "_ctk042_test"
AUCTION_URL = "https://example.test/p/ctk042-new-auction"
FIXED_URL = "https://example.test/p/ctk042-new-fixed"


def _p(title="Rainbow Acro", product_type="Frag", tags=None, handle="rainbow-acro",
       available=True, price="100.00") -> dict:
    return {
        "title": title,
        "product_type": product_type,
        "tags": tags or [],
        "handle": handle,
        "variants": [{"available": available, "price": price}],
        "images": [],
    }


# ─── Parser unit tests (no DB) ───────────────────────────────────────────────

def test_normalize_sets_is_auction_true_on_auction():
    """A tag-detected auction -> is_auction=true (and current_price nulled,
    the CTK-041 carry-over — both driven by the one _is_auction call)."""
    p = _p(product_type="WWC Auction", tags=["Auction"], price="599.00")
    out = _normalize_product(p, BASE, "mirror", "wwc", AUCTION_DETECTION)
    assert out["is_auction"] is True, f"is_auction not set on auction: {out['is_auction']!r}"
    assert out["current_price"] is None, "auction price should still null-out (CTK-041)"


def test_normalize_sets_is_auction_false_on_non_auction():
    """A normal coral -> is_auction=false, price preserved."""
    p = _p(price="50.00")
    out = _normalize_product(p, BASE, "mirror", "wwc", AUCTION_DETECTION)
    assert out["is_auction"] is False, f"is_auction true on non-auction: {out['is_auction']!r}"
    assert out["current_price"] == Decimal("50.00")


def test_normalize_is_auction_false_when_detection_unconfigured():
    """No auction_detection block -> is_auction=false even for an
    auction-shaped product (the permissive None default, matches the
    current_price null-out's no-op-when-None shape)."""
    p = _p(product_type="WWC Auction", tags=["Auction"], price="599.00")
    out = _normalize_product(p, BASE, "mirror", "wwc", None)
    assert out["is_auction"] is False, "is_auction should be false with auction_detection=None"
    assert out["current_price"] == Decimal("599.00"), "no null-out without auction_detection"


# ─── Diff new-row tests (live Neon) ──────────────────────────────────────────

def _setup_test_vendor(conn) -> dict:
    """Idempotent test-vendor setup (active=false; cron-isolated)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, slug, display_name, base_url, platform, image_strategy, active "
            "FROM vendors WHERE slug = %s",
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
            "RETURNING id, slug, display_name, base_url, platform, image_strategy, active",
            (TEST_VENDOR_SLUG, "CTK-042 test vendor", "https://example.test",
             "shopify", "products_json", "daily", "mirror", False),
        )
        return cur.fetchone()


def _wipe_listings(conn, vendor_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM vendor_listings WHERE vendor_id = %s", (vendor_id,))


def _start_scraper_run(conn, vendor_id: int) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO scraper_runs (vendor_id, status, git_sha) "
            "VALUES (%s, 'running', %s) RETURNING id",
            (vendor_id, "ctk042-gate-test"),
        )
        return cur.fetchone()["id"]


def _select_is_auction(conn, vendor_id: int, product_url: str):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, is_auction, current_price FROM vendor_listings "
            "WHERE vendor_id = %s AND product_url = %s",
            (vendor_id, product_url),
        )
        return cur.fetchone()


def _new_item(product_url: str, *, is_auction: bool, current_price) -> dict:
    return {
        "product_url": product_url,
        "raw_title": "Test Coral",
        "normalized_title": "test coral",
        "current_price": current_price,
        "compare_at_price": None,
        "currency": "USD",
        "in_stock": True,
        "category": "sps",
        "lineage_flag": "unknown",
        "vendor_sku": None,
        "vendor_image_url": None,
        "is_auction": is_auction,
    }


@mark_requires_db
def test_new_auction_row_persists_is_auction_true(conn, vendor):
    """The load-bearing pin: a NEW auction item carries is_auction=true
    through the UPSERT row-build into vendor_listings. Deleting the diff.py
    row-dict `is_auction` key fails this (column defaults false on INSERT,
    so the row would read false)."""
    _wipe_listings(conn, vendor["id"])
    run_id = _start_scraper_run(conn, vendor["id"])

    decision = ItemDecision(
        item=_new_item(AUCTION_URL, is_auction=True, current_price=None),
        decision="new",
    )
    persist_phase_a(
        conn=conn,
        vendor_row=vendor,
        decisions=[decision],
        existing_by_url={},
        run_id=run_id,
    )

    after = _select_is_auction(conn, vendor["id"], AUCTION_URL)
    assert after is not None, "new auction row was not inserted"
    assert after["is_auction"] is True, (
        f"NEW auction row did not persist is_auction=true. Got "
        f"{after['is_auction']!r}. Root cause if false: diff.py UPSERT "
        f"row-build dropped the is_auction key."
    )


@mark_requires_db
def test_new_fixed_price_row_persists_is_auction_false(conn, vendor):
    """Companion pin: a NEW non-auction row lands is_auction=false — no
    false-positive that would gate a fixed-price coral off the surfaces."""
    _wipe_listings(conn, vendor["id"])
    run_id = _start_scraper_run(conn, vendor["id"])

    decision = ItemDecision(
        item=_new_item(FIXED_URL, is_auction=False, current_price=Decimal("50.00")),
        decision="new",
    )
    persist_phase_a(
        conn=conn,
        vendor_row=vendor,
        decisions=[decision],
        existing_by_url={},
        run_id=run_id,
    )

    after = _select_is_auction(conn, vendor["id"], FIXED_URL)
    assert after is not None, "new fixed-price row was not inserted"
    assert after["is_auction"] is False, (
        f"NEW fixed-price row should be is_auction=false; got {after['is_auction']!r}"
    )


@mark_requires_db
def test_reader_surface_predicate_excludes_auction(conn, vendor):
    """Reader-surface pin: the `in_stock = true AND is_auction = false`
    predicate the web read-surfaces share (search.ts, getVendorInventory,
    getCoralAvailability, named-corals image lateral) excludes an in_stock
    auction row. Self-contained — seeds one auction + one fixed-price row
    for the test vendor and runs the shared predicate shape directly, so it
    pins the gate without coupling to any one surface's full SQL. Dropping
    `AND is_auction = false` from a surface fails this (the auction row
    re-enters the result)."""
    _wipe_listings(conn, vendor["id"])
    run_id = _start_scraper_run(conn, vendor["id"])
    persist_phase_a(
        conn=conn, vendor_row=vendor, run_id=run_id, existing_by_url={},
        decisions=[
            ItemDecision(item=_new_item(AUCTION_URL, is_auction=True, current_price=None),
                         decision="new"),
            ItemDecision(item=_new_item(FIXED_URL, is_auction=False, current_price=Decimal("50.00")),
                         decision="new"),
        ],
    )

    with conn.cursor() as cur:
        # The shared reader predicate: in-stock, non-auction.
        cur.execute(
            "SELECT product_url FROM vendor_listings "
            "WHERE vendor_id = %s AND in_stock = true AND is_auction = false "
            "ORDER BY product_url",
            (vendor["id"],),
        )
        kept = [r["product_url"] for r in cur.fetchall()]
        # Without the gate (regression baseline): both rows return.
        cur.execute(
            "SELECT count(*) AS c FROM vendor_listings "
            "WHERE vendor_id = %s AND in_stock = true",
            (vendor["id"],),
        )
        ungated = cur.fetchone()["c"]

    assert kept == [FIXED_URL], (
        f"reader predicate must keep only the fixed-price row; got {kept!r}"
    )
    assert ungated == 2, (
        f"baseline sanity: both in-stock rows exist (got {ungated}); the gate "
        f"is what drops the auction, not absence of the row"
    )


def main() -> int:
    # Parser tests run without a DB connection.
    parser_tests = [
        test_normalize_sets_is_auction_true_on_auction,
        test_normalize_sets_is_auction_false_on_non_auction,
        test_normalize_is_auction_false_when_detection_unconfigured,
    ]
    db_tests = [
        test_new_auction_row_persists_is_auction_true,
        test_new_fixed_price_row_persists_is_auction_false,
        test_reader_surface_predicate_excludes_auction,
    ]
    failures = []

    for fn in parser_tests:
        try:
            fn()
            print(f"  [PASS] {fn.__name__}")
        except AssertionError as e:
            print(f"  [FAIL] {fn.__name__}: {e}")
            failures.append((fn.__name__, str(e)))

    with db.get_test_conn() as conn:
        vendor = _setup_test_vendor(conn)
        print(f"test vendor: id={vendor['id']} slug={vendor['slug']}")
        for fn in db_tests:
            try:
                fn(conn, vendor)
                print(f"  [PASS] {fn.__name__}")
            except AssertionError as e:
                print(f"  [FAIL] {fn.__name__}: {e}")
                failures.append((fn.__name__, str(e)))
            except Exception as e:  # noqa: BLE001
                print(f"  [ERROR] {fn.__name__}: {type(e).__name__}: {e}")
                traceback.print_exc()
                failures.append((fn.__name__, f"{type(e).__name__}: {e}"))
            finally:
                try:
                    _wipe_listings(conn, vendor["id"])
                except Exception as e:  # noqa: BLE001
                    print(f"  [cleanup-warn] {fn.__name__}: {e}")

    print()
    total = len(parser_tests) + len(db_tests)
    if failures:
        print(f"{len(failures)}/{total} tests failed:")
        for name, msg in failures:
            print(f"  - {name}: {msg[:200]}")
        return 1
    print(f"all {total} tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
