"""scrapers/tests/test_markdown_started_at_capture.py — CTK-124 F8 pins.

Six pins on the markdown_started_at episode-onset capture (migration 0033
column; diff.py _markdown_transition + both write paths):

  Touch path (decision=="unchanged" — the dominant steady-state case and
  the Wave-2 blind-spot class per feedback_capture_path_unchanged_blind_spot):
    1. NULL -> non-NULL compare_at_price sets onset
    2. non-NULL -> NULL clears onset
    3. non-NULL -> non-NULL value drift KEEPS the original onset
       (a markdown deepening 100 -> 90 is the same episode)

  UPSERT path (new / price_changed):
    4. NEW row with compare_at_price at first sight gets onset = now
    5. price_changed row with NULL -> non-NULL transition sets onset
    6. price_changed row with non-NULL -> non-NULL drift keeps onset
       (the 'keep' action OMITS the column; absent-column = keep-existing
       contract in _upsert_listing_row carries it)

Decision #7 boundary is implicitly pinned too: none of these write
markdown rows into price_history (cases 1-3 produce zero history rows;
4-6 produce only the price/stock baseline rows the pre-CTK-124 code
already wrote).

Hits live Neon Postgres via psycopg — uses test vendor slug='_ctk124_test'
(active=false; isolated from cron). Mirrors
test_persist_phase_a_unchanged_compare_at.py shape. Pytest-discovery
requires a `conn` + `vendor` fixture pair the project does not declare
globally; standalone-mode main() builds them inline.

Runnable as:
  python -m scrapers.tests.test_markdown_started_at_capture
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


TEST_VENDOR_SLUG = "_ctk124_test"
TEST_PRODUCT_URL = "https://example.test/p/markdown-onset-pin"


def _setup_test_vendor(conn) -> dict:
    """Idempotent test-vendor setup. Returns the row."""
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


def _start_scraper_run(conn, vendor_id: int) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO scraper_runs (vendor_id, status, git_sha) "
            "VALUES (%s, 'running', %s) RETURNING id",
            (vendor_id, "ctk124-f8-test"),
        )
        return cur.fetchone()["id"]


def _seed_listing(conn, vendor_id: int, *, compare_at, onset_days_ago: int | None) -> dict:
    """INSERT a baseline row. onset_days_ago=None seeds markdown_started_at
    NULL; an int seeds now() - that many days (DB-side, so the returned
    timestamp is exact for keep-assertions)."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO vendor_listings "
            "(vendor_id, product_url, raw_title, normalized_title, "
            "current_price, currency, in_stock, compare_at_price, markdown_started_at) "
            "VALUES (%s, %s, %s, %s, %s, 'USD', %s, %s, "
            "        CASE WHEN %s::int IS NULL THEN NULL "
            "             ELSE now() - (%s::int * interval '1 day') END) "
            "RETURNING id, compare_at_price, markdown_started_at",
            (vendor_id, TEST_PRODUCT_URL, "Test Coral", "test coral",
             Decimal("80.00"), True, compare_at, onset_days_ago, onset_days_ago),
        )
        return cur.fetchone()


def _select_row(conn, listing_id: int):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, current_price, compare_at_price, markdown_started_at "
            "FROM vendor_listings WHERE id = %s",
            (listing_id,),
        )
        return cur.fetchone()


def _select_row_by_url(conn, vendor_id: int):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, current_price, compare_at_price, markdown_started_at "
            "FROM vendor_listings WHERE vendor_id = %s AND product_url = %s",
            (vendor_id, TEST_PRODUCT_URL),
        )
        return cur.fetchone()


def _item(*, current_price, compare_at):
    return {
        "product_url": TEST_PRODUCT_URL,
        "raw_title": "Test Coral",
        "normalized_title": "test coral",
        "current_price": current_price,
        "compare_at_price": compare_at,
        "currency": "USD",
        "in_stock": True,
        "category": "sps",
        "lineage_flag": "unknown",
        "vendor_sku": None,
        "vendor_image_url": None,
    }


def _existing_entry(seeded: dict, *, current_price=Decimal("80.00")):
    """existing_by_url value mirroring the CTK-124-widened
    fetch_existing_listings SELECT (id, product_url, current_price,
    in_stock, image_url, compare_at_price)."""
    return {
        TEST_PRODUCT_URL: {
            "id": seeded["id"],
            "product_url": TEST_PRODUCT_URL,
            "current_price": current_price,
            "in_stock": True,
            "image_url": None,
            "compare_at_price": seeded["compare_at_price"],
        },
    }


def _persist_one(conn, vendor, decision, existing_by_url):
    run_id = _start_scraper_run(conn, vendor["id"])
    persist_phase_a(
        conn=conn,
        vendor_row=vendor,
        decisions=[decision],
        existing_by_url=existing_by_url,
        run_id=run_id,
    )


# ─── Touch path (decision=="unchanged") ───────────────────────────────────────

@mark_requires_db
def test_touch_path_sets_onset_on_null_to_nonnull(conn, vendor):
    """Pin 1 — the load-bearing one. A row whose ONLY change between scrapes
    is compare_at_price appearing classifies as 'unchanged' (price + stock
    identical) and rides the touch path; onset must be written there, not
    just on the UPSERT path (the exact Wave-2 blind-spot shape)."""
    _wipe_listings(conn, vendor["id"])
    seeded = _seed_listing(conn, vendor["id"], compare_at=None, onset_days_ago=None)
    decision = ItemDecision(
        item=_item(current_price=Decimal("80.00"), compare_at=Decimal("100.00")),
        decision="unchanged",
        existing_id=seeded["id"],
    )
    _persist_one(conn, vendor, decision, _existing_entry(seeded))
    after = _select_row(conn, seeded["id"])
    assert after["compare_at_price"] == Decimal("100.00")
    assert after["markdown_started_at"] is not None, (
        "touch path must SET markdown_started_at on NULL -> non-NULL "
        "compare_at_price (episode onset)"
    )


@mark_requires_db
def test_touch_path_clears_onset_on_nonnull_to_null(conn, vendor):
    """Pin 2 — vendor pulled the slash; onset clears alongside compare_at."""
    _wipe_listings(conn, vendor["id"])
    seeded = _seed_listing(conn, vendor["id"], compare_at=Decimal("100.00"), onset_days_ago=3)
    assert seeded["markdown_started_at"] is not None
    decision = ItemDecision(
        item=_item(current_price=Decimal("80.00"), compare_at=None),
        decision="unchanged",
        existing_id=seeded["id"],
    )
    _persist_one(conn, vendor, decision, _existing_entry(seeded))
    after = _select_row(conn, seeded["id"])
    assert after["compare_at_price"] is None
    assert after["markdown_started_at"] is None, (
        "touch path must CLEAR markdown_started_at on non-NULL -> NULL "
        "compare_at_price (episode end)"
    )


@mark_requires_db
def test_touch_path_keeps_onset_on_value_drift(conn, vendor):
    """Pin 3 — markdown deepens 100 -> 90: same episode, onset untouched."""
    _wipe_listings(conn, vendor["id"])
    seeded = _seed_listing(conn, vendor["id"], compare_at=Decimal("100.00"), onset_days_ago=3)
    original_onset = seeded["markdown_started_at"]
    decision = ItemDecision(
        item=_item(current_price=Decimal("80.00"), compare_at=Decimal("90.00")),
        decision="unchanged",
        existing_id=seeded["id"],
    )
    _persist_one(conn, vendor, decision, _existing_entry(seeded))
    after = _select_row(conn, seeded["id"])
    assert after["compare_at_price"] == Decimal("90.00")
    assert after["markdown_started_at"] == original_onset, (
        f"mid-episode value drift must NOT reset onset: "
        f"expected {original_onset}, got {after['markdown_started_at']}"
    )


# ─── UPSERT path (new / price_changed) ────────────────────────────────────────

@mark_requires_db
def test_new_row_with_markdown_gets_onset_at_first_sight(conn, vendor):
    """Pin 4 — cold-start posture for rows born marked-down."""
    _wipe_listings(conn, vendor["id"])
    decision = ItemDecision(
        item=_item(current_price=Decimal("80.00"), compare_at=Decimal("100.00")),
        decision="new",
    )
    _persist_one(conn, vendor, decision, {})
    after = _select_row_by_url(conn, vendor["id"])
    assert after is not None, "NEW row must land"
    assert after["markdown_started_at"] is not None, (
        "NEW row with compare_at_price at first sight must get onset = now"
    )


@mark_requires_db
def test_upsert_path_sets_onset_on_null_to_nonnull(conn, vendor):
    """Pin 5 — price drop + markdown onset in the same scrape (the common
    real-vendor shape: compare_at set to the old price, current dropped)."""
    _wipe_listings(conn, vendor["id"])
    seeded = _seed_listing(conn, vendor["id"], compare_at=None, onset_days_ago=None)
    decision = ItemDecision(
        item=_item(current_price=Decimal("70.00"), compare_at=Decimal("80.00")),
        decision="price_changed",
        existing_id=seeded["id"],
    )
    _persist_one(conn, vendor, decision, _existing_entry(seeded))
    after = _select_row(conn, seeded["id"])
    assert after["current_price"] == Decimal("70.00")
    assert after["markdown_started_at"] is not None, (
        "UPSERT path must SET onset on NULL -> non-NULL compare_at_price"
    )


@mark_requires_db
def test_upsert_path_keeps_onset_on_value_drift(conn, vendor):
    """Pin 6 — price changes mid-episode; the 'keep' action omits the
    column from the payload, so the absent-column = keep-existing contract
    must preserve the live onset through the UPSERT."""
    _wipe_listings(conn, vendor["id"])
    seeded = _seed_listing(conn, vendor["id"], compare_at=Decimal("100.00"), onset_days_ago=3)
    original_onset = seeded["markdown_started_at"]
    decision = ItemDecision(
        item=_item(current_price=Decimal("70.00"), compare_at=Decimal("100.00")),
        decision="price_changed",
        existing_id=seeded["id"],
    )
    _persist_one(conn, vendor, decision, _existing_entry(seeded))
    after = _select_row(conn, seeded["id"])
    assert after["current_price"] == Decimal("70.00")
    assert after["markdown_started_at"] == original_onset, (
        f"UPSERT 'keep' must preserve onset via absent-column contract: "
        f"expected {original_onset}, got {after['markdown_started_at']}"
    )


def main() -> int:
    with db.get_conn() as conn:
        vendor = _setup_test_vendor(conn)
        print(f"test vendor: id={vendor['id']} slug={vendor['slug']}")

        tests = [
            test_touch_path_sets_onset_on_null_to_nonnull,
            test_touch_path_clears_onset_on_nonnull_to_null,
            test_touch_path_keeps_onset_on_value_drift,
            test_new_row_with_markdown_gets_onset_at_first_sight,
            test_upsert_path_sets_onset_on_null_to_nonnull,
            test_upsert_path_keeps_onset_on_value_drift,
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
