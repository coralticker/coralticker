"""scrapers/tests/test_fetch_existing_listings_pagination.py — CTK-033 +
CTK-034 regression tests for db.fetch_existing_listings range-loop
pagination.

Hits live Neon Postgres via a psycopg connection (no local stub yet).
Uses a dedicated test vendor (slug='_ctk033_test', active=false) for
isolation — created on first run, listings wiped before + after each test.
Test vendor row stays in `vendors` between runs; cheap, no real-scrape
side-effects (active=false keeps it out of the cron orchestrator).

Runnable as:
  python -m scrapers.tests.test_fetch_existing_listings_pagination

Requires NEON_DATABASE_URL in env (same as production scraper).

CTK-043 cut-1: ported from supabase-py to psycopg. Test bodies unchanged
beyond the param rename (client → conn) — the load-bearing assertions are
in db.fetch_existing_listings's internals, not the test surface. Test 7's
mock is reshaped to psycopg's cursor.execute / fetchall / fetchone surface
since that's the API db.fetch_existing_listings now hits.

Coverage:
  CTK-033 Tasks §6 (range-loop pagination):
    test_pagination_returns_full_catalog          full-catalog pagination (2500 > prior 1000-cap)
    test_pagination_under_page_size               under-page-size single-chunk path
    test_pagination_empty_catalog                 empty-catalog zero-row path
    test_pagination_dict_keys_unique              page boundary off-by-one regression
  CTK-034 Task §4 (chunk-ordering stability):
    test_pagination_dict_size_matches_catalog_count  multi-iteration chunk-stability
    test_pagination_returns_all_unique_keys          all-keys-present at scale
    test_sanity_check_raises_on_count_mismatch       count-mismatch loud-failure (mocked)
"""

from __future__ import annotations

import sys
import traceback

from scrapers.common import db

# CTK-039 D1 marker — pytest-aware so CI filter `-m "not requires_db"` skips
# this module's tests (live hosted DB). Script-mode invocation on a lean
# venv without pytest installed continues to work via the identity fallback.
try:
    import pytest
    mark_requires_db = pytest.mark.requires_db
except ImportError:
    mark_requires_db = lambda f: f


TEST_VENDOR_SLUG = "_ctk033_test"


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
                "CTK-033 test vendor",
                "https://example.test",
                "shopify",
                "products_json",
                "daily",  # any value passing vendors_cadence_label_check; semantically inert (active=False)
                "mirror",
                False,
            ),
        )
        inserted = cur.fetchone()
    return inserted


def _wipe_listings(conn, vendor_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM vendor_listings WHERE vendor_id = %s", (vendor_id,))


def _insert_listings_bulk(conn, vendor_id: int, count: int, url_prefix: str) -> None:
    """Bulk-insert `count` rows with deterministic URLs `<url_prefix><i>` for
    i in 0..count-1. Chunked at 500/insert via executemany.
    """
    chunk_size = 500
    for chunk_start in range(0, count, chunk_size):
        chunk_end = min(chunk_start + chunk_size, count)
        rows = [
            (
                vendor_id,
                f"{url_prefix}{i}",
                f"test row {i}",
                f"test row {i}",
                True,
            )
            for i in range(chunk_start, chunk_end)
        ]
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO vendor_listings "
                "(vendor_id, product_url, raw_title, normalized_title, in_stock) "
                "VALUES (%s, %s, %s, %s, %s)",
                rows,
            )


# ─── Test 1: full-catalog pagination (2500 > prior 1000-row default cap) ──────
@mark_requires_db
def test_pagination_returns_full_catalog(conn, vendor):
    """Insert 2500 listings (above the prior PostgREST 1000-row default cap);
    call fetch_existing_listings; assert all 2500 land in the returned dict.
    Pre-CTK-033 (under supabase-py): would return at most 1000 keys (the bug).
    Post-CTK-033: range-loop pagination surfaces all 2500.
    Post-CTK-043 cut-1 (psycopg): LIMIT/OFFSET chunk loop preserves the same
    invariant against the same regression class on the new driver.
    """
    _wipe_listings(conn, vendor["id"])
    _insert_listings_bulk(conn, vendor["id"], 2500, "https://example.test/p/full-catalog-")

    result = db.fetch_existing_listings(conn, vendor["id"])
    assert len(result) == 2500, (
        f"pagination dropped rows: expected 2500 keys, got {len(result)} "
        f"(pre-CTK-033 PostgREST 1000-row truncation regression)"
    )


# ─── Test 2: under-page-size single-chunk path ────────────────────────────────
@mark_requires_db
def test_pagination_under_page_size(conn, vendor):
    """Insert 50 listings (well below page_size=1000); first chunk is short
    so the loop terminates after one round-trip. Assert all 50 land.
    """
    _wipe_listings(conn, vendor["id"])
    _insert_listings_bulk(conn, vendor["id"], 50, "https://example.test/p/under-page-")

    result = db.fetch_existing_listings(conn, vendor["id"])
    assert len(result) == 50, (
        f"under-page-size single-chunk path broken: expected 50 keys, got {len(result)}"
    )


# ─── Test 3: empty-catalog zero-row path ──────────────────────────────────────
@mark_requires_db
def test_pagination_empty_catalog(conn, vendor):
    """Wipe listings, do not insert any. fetch_existing_listings should return
    an empty dict cleanly without raising; loop terminates on first empty
    response.
    """
    _wipe_listings(conn, vendor["id"])

    result = db.fetch_existing_listings(conn, vendor["id"])
    assert result == {}, (
        f"empty-catalog path broken: expected empty dict, got {len(result)} keys: "
        f"{list(result.keys())[:5]}"
    )


# ─── Test 4: page boundary off-by-one regression ──────────────────────────────
@mark_requires_db
def test_pagination_dict_keys_unique(conn, vendor):
    """Insert 2500 listings with deterministic URLs; call fetch_existing_listings;
    assert no key collisions in returned dict (catches off-by-one in
    LIMIT/OFFSET boundary handling). 2500 distinct stored URLs MUST yield 2500
    distinct dict keys — if OFFSET 0 LIMIT 1000 + OFFSET 1000 LIMIT 1000
    accidentally overlapped on boundary row 1000 (or skipped it), the
    dict-build collapses or drops.
    """
    _wipe_listings(conn, vendor["id"])
    _insert_listings_bulk(conn, vendor["id"], 2500, "https://example.test/p/unique-")

    result = db.fetch_existing_listings(conn, vendor["id"])
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
        f"key collision via page overlap: expected 2500 keys, got {len(result)}"
    )


# ─── Test 5: chunk-stability across iterations (CTK-034) ─────────────────────
@mark_requires_db
def test_pagination_dict_size_matches_catalog_count(conn, vendor):
    """Insert 2500 listings; call fetch_existing_listings 5 times; assert each
    iteration returns 2500 keys. Catches the CTK-034 chunk-ordering bug:
    paged SELECTs without ORDER BY return chunks in indeterminate scan order,
    so successive fires can skip rows on some iterations and overlap on others.
    With ORDER BY id in place, every iteration is deterministic.
    """
    _wipe_listings(conn, vendor["id"])
    _insert_listings_bulk(conn, vendor["id"], 2500, "https://example.test/p/stable-")

    for iteration in range(5):
        result = db.fetch_existing_listings(conn, vendor["id"])
        assert len(result) == 2500, (
            f"chunk-ordering instability: iteration {iteration} returned {len(result)} keys, "
            f"expected 2500 (CTK-034 ORDER BY regression)"
        )


# ─── Test 6: all expected URLs present at scale (CTK-034) ────────────────────
@mark_requires_db
def test_pagination_returns_all_unique_keys(conn, vendor):
    """Insert 2500 listings with zero-padded URLs; call fetch_existing_listings;
    assert every expected URL appears in the returned dict. Catches the same
    CTK-034 bug from the URL-key direction — chunk-skip surfaces as a missing
    key in the result dict, not just a wrong row count.
    """
    _wipe_listings(conn, vendor["id"])
    _insert_listings_bulk(
        conn, vendor["id"], 2500, "https://test.example.com/products/test-"
    )

    result = db.fetch_existing_listings(conn, vendor["id"])
    expected_keys = {
        f"https://test.example.com/products/test-{i}" for i in range(2500)
    }
    actual_keys = set(result.keys())
    missing = expected_keys - actual_keys
    assert not missing, (
        f"chunk-skip dropped {len(missing)} keys; "
        f"sample missing: {sorted(missing)[:5]}"
    )


# ─── Test 7: count-mismatch sanity-check raises (CTK-034) ────────────────────
# Convention break: this test uses unittest.mock to force the count-mismatch
# branch. Tests 1-6 use plain-assert + DB-live fixture (the _ctk033_test
# vendor pattern). Forcing count-mismatch at the DB layer would require a
# concurrent DELETE between the chunk SELECT and the COUNT(*) call —
# race-y and flakier than mocking. Mock is the cleaner shape for this single
# test; deviation from the plain-assert/DB-live convention is intentional.
@mark_requires_db
def test_sanity_check_raises_on_count_mismatch(conn, vendor):
    """Mock the psycopg connection so the chunked SELECT returns 30 rows but
    the COUNT(*) query reports 50; assert RuntimeError raised. Validates the
    CTK-034 loud-failure assertion at fetch_existing_listings loop exit.
    """
    from unittest.mock import MagicMock

    chunk_data = [
        {
            "id": i,
            "product_url": f"https://example.test/p/mock-{i}",
            "current_price": None,
            "in_stock": True,
            "image_url": None,
        }
        for i in range(30)
    ]

    # CTK-043 cut-1: reshape mock to psycopg's cursor.execute / fetchall /
    # fetchone surface. Dispatch on the SQL string: COUNT(*) query returns
    # the inflated 50 count; the paged SELECT returns the short 30-row
    # chunk (triggers loop-exit on the first iteration).
    def execute_dispatch(sql, params=None):
        if "COUNT(*)" in sql:
            mock_cursor._count_mode = True
        else:
            mock_cursor._count_mode = False

    def fetchall_dispatch():
        return chunk_data

    def fetchone_dispatch():
        return {"c": 50}

    mock_cursor = MagicMock()
    mock_cursor.execute.side_effect = execute_dispatch
    mock_cursor.fetchall.side_effect = fetchall_dispatch
    mock_cursor.fetchone.side_effect = fetchone_dispatch
    mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
    mock_cursor.__exit__ = MagicMock(return_value=False)

    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor

    try:
        db.fetch_existing_listings(mock_conn, vendor_id=999)
    except RuntimeError as e:
        assert "coverage gap" in str(e), f"unexpected error message: {e}"
        return
    raise AssertionError(
        "expected RuntimeError on count mismatch; none was raised"
    )


def main() -> int:
    conn = db.get_test_conn()
    vendor = _setup_test_vendor(conn)
    print(f"test vendor: id={vendor['id']} slug={vendor['slug']}")

    tests = [
        test_pagination_returns_full_catalog,
        test_pagination_under_page_size,
        test_pagination_empty_catalog,
        test_pagination_dict_keys_unique,
        test_pagination_dict_size_matches_catalog_count,
        test_pagination_returns_all_unique_keys,
        test_sanity_check_raises_on_count_mismatch,
    ]

    failures: list[tuple[str, str]] = []
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
