"""scrapers/tests/test_fetch_existing_listings_pagination.py — CTK-033
regression tests for db.fetch_existing_listings range-loop pagination per
Tasks §6.

Hits the live hosted Supabase via service_role client (no local stub yet).
Uses a dedicated test vendor (slug='_ctk033_test', active=false) for
isolation — created on first run, listings wiped before + after each test.
Test vendor row stays in `vendors` between runs; cheap, no real-scrape
side-effects (active=false keeps it out of the cron orchestrator).

Runnable as:
  python -m scrapers.tests.test_fetch_existing_listings_pagination

Requires SUPABASE_URL + SUPABASE_SERVICE_KEY in env (same as production
scraper).

Coverage per CTK-033 plan §6:
  test_pagination_returns_full_catalog          full-catalog pagination (2500 > 1000-cap)
  test_pagination_under_page_size               under-page-size single-chunk path
  test_pagination_empty_catalog                 empty-catalog zero-row path
  test_pagination_dict_keys_unique              .range() boundary off-by-one regression
"""

from __future__ import annotations

import sys
import traceback

from scrapers.common import db


TEST_VENDOR_SLUG = "_ctk033_test"


def _setup_test_vendor(client) -> dict:
    """Idempotent test-vendor setup. Returns the row."""
    existing = (
        client.table("vendors")
        .select("id,slug,display_name,base_url,platform,image_strategy,active")
        .eq("slug", TEST_VENDOR_SLUG)
        .execute()
        .data
        or []
    )
    if existing:
        return existing[0]
    inserted = (
        client.table("vendors")
        .insert({
            "slug": TEST_VENDOR_SLUG,
            "display_name": "CTK-033 test vendor",
            "base_url": "https://example.test",
            "platform": "shopify",
            "scrape_method": "products_json",
            "cadence_label": "daily",  # any value passing vendors_cadence_label_check; semantically inert (active=False)
            "image_strategy": "mirror",
            "active": False,
        })
        .execute()
        .data
    )
    return inserted[0]


def _wipe_listings(client, vendor_id: int) -> None:
    client.table("vendor_listings").delete().eq("vendor_id", vendor_id).execute()


def _insert_listings_bulk(client, vendor_id: int, count: int, url_prefix: str) -> None:
    """Bulk-insert `count` rows with deterministic URLs `<url_prefix><i>` for
    i in 0..count-1. Chunked at 500/insert to stay clear of any PostgREST
    request-body cap.
    """
    chunk_size = 500
    for chunk_start in range(0, count, chunk_size):
        chunk_end = min(chunk_start + chunk_size, count)
        rows = [
            {
                "vendor_id": vendor_id,
                "product_url": f"{url_prefix}{i}",
                "raw_title": f"test row {i}",
                "normalized_title": f"test row {i}",
                "in_stock": True,
            }
            for i in range(chunk_start, chunk_end)
        ]
        client.table("vendor_listings").insert(rows).execute()


# ─── Test 1: full-catalog pagination (2500 > PostgREST 1000-row default cap) ──
def test_pagination_returns_full_catalog(client, vendor):
    """Insert 2500 listings (above PostgREST 1000-row default cap); call
    fetch_existing_listings; assert all 2500 land in the returned dict.
    Pre-CTK-033: would return at most 1000 keys (the bug).
    Post-CTK-033: range-loop pagination surfaces all 2500.
    """
    _wipe_listings(client, vendor["id"])
    _insert_listings_bulk(client, vendor["id"], 2500, "https://example.test/p/full-catalog-")

    result = db.fetch_existing_listings(client, vendor["id"])
    assert len(result) == 2500, (
        f"pagination dropped rows: expected 2500 keys, got {len(result)} "
        f"(pre-CTK-033 PostgREST 1000-row truncation regression)"
    )


# ─── Test 2: under-page-size single-chunk path ────────────────────────────────
def test_pagination_under_page_size(client, vendor):
    """Insert 50 listings (well below page_size=1000); first chunk is short
    so the loop terminates after one round-trip. Assert all 50 land.
    """
    _wipe_listings(client, vendor["id"])
    _insert_listings_bulk(client, vendor["id"], 50, "https://example.test/p/under-page-")

    result = db.fetch_existing_listings(client, vendor["id"])
    assert len(result) == 50, (
        f"under-page-size single-chunk path broken: expected 50 keys, got {len(result)}"
    )


# ─── Test 3: empty-catalog zero-row path ──────────────────────────────────────
def test_pagination_empty_catalog(client, vendor):
    """Wipe listings, do not insert any. fetch_existing_listings should return
    an empty dict cleanly without raising; loop terminates on first empty
    response.
    """
    _wipe_listings(client, vendor["id"])

    result = db.fetch_existing_listings(client, vendor["id"])
    assert result == {}, (
        f"empty-catalog path broken: expected empty dict, got {len(result)} keys: "
        f"{list(result.keys())[:5]}"
    )


# ─── Test 4: .range() boundary off-by-one regression ──────────────────────────
def test_pagination_dict_keys_unique(client, vendor):
    """Insert 2500 listings with deterministic URLs; call fetch_existing_listings;
    assert no key collisions in returned dict (catches off-by-one in .range()
    boundary handling). 2500 distinct stored URLs MUST yield 2500 distinct dict
    keys — if .range(0, 999) + .range(1000, 1999) accidentally overlapped on
    boundary row 1000 (or skipped it), the dict-build collapses or drops.
    """
    _wipe_listings(client, vendor["id"])
    _insert_listings_bulk(client, vendor["id"], 2500, "https://example.test/p/unique-")

    result = db.fetch_existing_listings(client, vendor["id"])
    expected_keys = {f"https://example.test/p/unique-{i}" for i in range(2500)}
    actual_keys = set(result.keys())
    missing = expected_keys - actual_keys
    extra = actual_keys - expected_keys
    assert actual_keys == expected_keys, (
        f"dict-keys do not match inserted set:\n"
        f"  missing ({len(missing)}): {sorted(missing)[:5]}\n"
        f"  extra   ({len(extra)}): {sorted(extra)[:5]}"
    )
    assert len(result) == 2500, (
        f"key collision via .range() overlap: expected 2500 keys, got {len(result)}"
    )


def main() -> int:
    client = db.get_client()
    vendor = _setup_test_vendor(client)
    print(f"test vendor: id={vendor['id']} slug={vendor['slug']}")

    tests = [
        test_pagination_returns_full_catalog,
        test_pagination_under_page_size,
        test_pagination_empty_catalog,
        test_pagination_dict_keys_unique,
    ]

    failures: list[tuple[str, str]] = []
    for fn in tests:
        name = fn.__name__
        try:
            fn(client, vendor)
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
                _wipe_listings(client, vendor["id"])
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
