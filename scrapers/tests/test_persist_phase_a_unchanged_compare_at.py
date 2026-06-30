"""scrapers/tests/test_persist_phase_a_unchanged_compare_at.py — CTK-100
Wave-2 hotfix regression-pin.

The Wave-2 ship at `55962ad` (2026-06-01) wired F6 (`_UPSERT_ALLOWED_COLS`
extend + `persist_phase_a` row build at diff.py:275-287) to flip Wave-1's
dark `compare_at_price` column on. But TG run 765 verify-pass returned 0
non-NULL writes against 348 listings_seen — including the 4 audit-confirmed
live markdowns from W2-§B. Root cause: diff.py:246-248 early-returns
decision=="unchanged" rows to a touch-only path at L341-347 that UPDATEs
last_seen_at alone; the row dict at L275 (including the F6 compare_at_price
key) is never built for those rows. For the dominant case (rows whose
current_price + in_stock didn't change between scrapes), F6 was dark.

This test pins the post-hotfix invariant: when persist_phase_a sees an
unchanged row whose parser-output items-dict carries
`compare_at_price = Decimal("100.00")`, the row's compare_at_price column
post-call must be Decimal("100.00"), not NULL.

Without this regression test the bug recurs on any future column-add that
parsers populate via the items-dict but `persist_phase_a` routes through
the unchanged-row path. See feedback_capture_path_unchanged_blind_spot.

Hits live Neon Postgres via psycopg — uses test vendor slug='_ctk100_test'
(active=false; isolated from cron). Mirrors test_first_seen_at.py +
test_rematch.py shape. Pytest-discovery requires a `conn` + `vendor`
fixture pair that the project does not declare globally; standalone-mode
main() builds them inline.

Runnable as:
  python -m scrapers.tests.test_persist_phase_a_unchanged_compare_at
"""

from __future__ import annotations

import sys
import traceback
from decimal import Decimal

from scrapers.common import db
from scrapers.common.diff import ItemDecision, persist_phase_a

try:
    import pytest
    mark_requires_db = pytest.mark.requires_db
except ImportError:
    mark_requires_db = lambda f: f


TEST_VENDOR_SLUG = "_ctk100_test"
TEST_PRODUCT_URL = "https://example.test/p/unchanged-compare-at-pin"


def _setup_test_vendor(conn) -> dict:
    """Idempotent test-vendor setup. Returns the row.
    Mirrors test_first_seen_at._setup_test_vendor shape."""
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
            (
                TEST_VENDOR_SLUG,
                "CTK-100 test vendor",
                "https://example.test",
                "shopify",
                "products_json",
                "daily",
                "mirror",
                False,
            ),
        )
        inserted = cur.fetchone()
    return inserted


def _wipe_listings(conn, vendor_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM vendor_listings WHERE vendor_id = %s", (vendor_id,))


def _start_scraper_run(conn, vendor_id: int) -> int:
    """Open a scraper_runs row so price_history INSERTs have a valid FK."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO scraper_runs (vendor_id, status, git_sha) "
            "VALUES (%s, 'running', %s) RETURNING id",
            (vendor_id, "ctk100-hotfix-test"),
        )
        return cur.fetchone()["id"]


def _seed_existing_listing(conn, vendor_id: int, product_url: str) -> dict:
    """INSERT a baseline row with compare_at_price = NULL (Wave-1 dark-column
    state). Returns the seeded row including id."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO vendor_listings "
            "(vendor_id, product_url, raw_title, normalized_title, "
            "current_price, currency, in_stock, compare_at_price) "
            "VALUES (%s, %s, %s, %s, %s, 'USD', %s, NULL) "
            "RETURNING id, compare_at_price",
            (vendor_id, product_url, "Test Coral", "test coral",
             Decimal("80.00"), True),
        )
        return cur.fetchone()


def _select_compare_at(conn, listing_id: int):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, current_price, compare_at_price, last_seen_at "
            "FROM vendor_listings WHERE id = %s",
            (listing_id,),
        )
        return cur.fetchone()


# ─── Regression test ──────────────────────────────────────────────────────────

@mark_requires_db
def test_unchanged_path_writes_compare_at_price(conn, vendor):
    """The load-bearing pin. Pre-hotfix this test fails (compare_at_price
    stays NULL post-call); post-hotfix it captures the value from the
    items-dict via the widened touch-path UPDATE.

    Setup:
      - seed an existing vendor_listings row with current_price=80.00,
        in_stock=True, compare_at_price=NULL
      - build a single ItemDecision(decision="unchanged", existing_id=<seed_id>)
        whose item dict carries the same current_price + in_stock (unchanged)
        plus compare_at_price = Decimal("100.00")
      - call persist_phase_a
      - assert row's compare_at_price post-call == Decimal("100.00")

    Why this would have caught the Wave-2 incident: ANY unchanged-row
    column-write goes through the touch-path; the F6 wiring at the UPSERT
    path is bypassed. A test that pre-seeds the row + asserts the
    unchanged-path UPDATE writes the new column is the only shape that
    surfaces the blind spot."""
    _wipe_listings(conn, vendor["id"])
    seeded = _seed_existing_listing(conn, vendor["id"], TEST_PRODUCT_URL)
    assert seeded["compare_at_price"] is None, "baseline must seed compare_at_price = NULL"

    run_id = _start_scraper_run(conn, vendor["id"])

    # Build the unchanged-decision shape — item carries compare_at_price,
    # existing_id points at the seeded row.
    item = {
        "product_url": TEST_PRODUCT_URL,
        "raw_title": "Test Coral",
        "normalized_title": "test coral",
        "current_price": Decimal("80.00"),
        "compare_at_price": Decimal("100.00"),
        "currency": "USD",
        "in_stock": True,
        "category": "sps",
        "lineage_flag": "unknown",
        "vendor_sku": None,
        "vendor_image_url": None,
    }
    decision = ItemDecision(
        item=item,
        decision="unchanged",
        existing_id=seeded["id"],
    )

    # existing_by_url shape mirrors db.fetch_existing_listings return
    existing_by_url = {
        TEST_PRODUCT_URL: {
            "id": seeded["id"],
            "product_url": TEST_PRODUCT_URL,
            "current_price": Decimal("80.00"),
            "in_stock": True,
            "image_url": None,
        },
    }

    persist_phase_a(
        conn=conn,
        vendor_row=vendor,
        decisions=[decision],
        existing_by_url=existing_by_url,
        run_id=run_id,
    )

    # Post-call assertion: the touch-path UPDATE writes compare_at_price.
    after = _select_compare_at(conn, seeded["id"])
    assert after["compare_at_price"] == Decimal("100.00"), (
        f"PRE-HOTFIX BUG REPRO — unchanged-row compare_at_price was NOT "
        f"written. Got {after['compare_at_price']!r}, expected "
        f"Decimal('100.00'). Root cause: diff.py touch-path UPDATE wrote "
        f"only last_seen_at; F6's UPSERT-path wiring at L275-287 never "
        f"fires for decision=='unchanged' rows."
    )
    # Belt-and-suspenders — last_seen_at also updated (the original
    # touch-path semantic still holds).
    assert after["last_seen_at"] is not None, "last_seen_at must still update"


# ─── Companion test — None compare_at_price round-trips cleanly ───────────────

@mark_requires_db
def test_unchanged_path_writes_none_when_no_markdown(conn, vendor):
    """Companion pin: an unchanged row whose items-dict carries
    compare_at_price=None (the dominant case — non-sale row) writes None,
    not garbage. Pins the psycopg numeric[] adapter behavior for
    Decimal-or-None mixed lists (probed live 2026-06-01: str-or-None
    list → numeric[] adapts cleanly, round-trips as Decimal-or-None)."""
    _wipe_listings(conn, vendor["id"])
    # Seed with an arbitrary non-NULL compare_at_price so we can detect a
    # bad clobber (None should overwrite the prior value, not be ignored).
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO vendor_listings "
            "(vendor_id, product_url, raw_title, normalized_title, "
            "current_price, currency, in_stock, compare_at_price) "
            "VALUES (%s, %s, %s, %s, %s, 'USD', %s, %s) "
            "RETURNING id",
            (vendor["id"], TEST_PRODUCT_URL, "Test Coral", "test coral",
             Decimal("80.00"), True, Decimal("100.00")),
        )
        seeded_id = cur.fetchone()["id"]

    run_id = _start_scraper_run(conn, vendor["id"])

    item = {
        "product_url": TEST_PRODUCT_URL,
        "raw_title": "Test Coral",
        "normalized_title": "test coral",
        "current_price": Decimal("80.00"),
        "compare_at_price": None,  # vendor cleared the markdown
        "currency": "USD",
        "in_stock": True,
        "category": "sps",
        "lineage_flag": "unknown",
        "vendor_sku": None,
        "vendor_image_url": None,
    }
    decision = ItemDecision(
        item=item,
        decision="unchanged",
        existing_id=seeded_id,
    )
    existing_by_url = {
        TEST_PRODUCT_URL: {
            "id": seeded_id,
            "product_url": TEST_PRODUCT_URL,
            "current_price": Decimal("80.00"),
            "in_stock": True,
            "image_url": None,
        },
    }

    persist_phase_a(
        conn=conn,
        vendor_row=vendor,
        decisions=[decision],
        existing_by_url=existing_by_url,
        run_id=run_id,
    )

    after = _select_compare_at(conn, seeded_id)
    assert after["compare_at_price"] is None, (
        f"unchanged-row touch-path must accept None (markdown cleared); "
        f"got {after['compare_at_price']!r}"
    )


def main() -> int:
    with db.get_test_conn() as conn:
        vendor = _setup_test_vendor(conn)
        print(f"test vendor: id={vendor['id']} slug={vendor['slug']}")

        tests = [
            test_unchanged_path_writes_compare_at_price,
            test_unchanged_path_writes_none_when_no_markdown,
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
