"""scrapers/tests/test_cohort_convergence_db.py — CTK-137 /code-review F2
requires_db integration tests for the SQL-level capture wiring the pure
test_cohort_convergence.py suite cannot see (the project has been bitten by
write-path / unchanged-path capture gaps before — feedback_capture_path_
unchanged_blind_spot).

Two narrow round-trips against live Neon (NOT a full run() harness — that stays
deferred):
  1. finish_scraper_run persists cohort_absent_set_hash + cohort_absent_count,
     AND the failure-path call shape (no cohort kwargs) round-trips NULL.
  2. get_recent_cohort_absent_hashes returns the K-1 newest by started_at DESC,
     EXCLUDES the in-flight run_id, and surfaces NULL hashes as-is.

Dedicated test vendor (slug='_ctk137_test', active=false) for isolation;
scraper_runs for it wiped before + after each test. Mirrors
test_fetch_existing_listings_pagination.py shape.

Runnable as:
  python -m scrapers.tests.test_cohort_convergence_db
Requires NEON_DATABASE_URL in env.
"""

from __future__ import annotations

import sys
import traceback

from scrapers.common import db
from scrapers.common.diff import Counters

try:
    import pytest
    mark_requires_db = pytest.mark.requires_db
except ImportError:  # script-mode on a lean venv without pytest
    mark_requires_db = lambda f: f  # noqa: E731


TEST_VENDOR_SLUG = "_ctk137_test"


def _setup_test_vendor(conn) -> dict:
    """Idempotent test-vendor setup (active=false keeps it out of the cron
    orchestrator). Returns the row."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, slug FROM vendors WHERE slug = %s", (TEST_VENDOR_SLUG,)
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
                "CTK-137 test vendor",
                "https://example.test",
                "shopify",
                "products_json",
                "daily",
                "mirror",
                False,
            ),
        )
        return cur.fetchone()


def _wipe_runs(conn, vendor_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM scraper_runs WHERE vendor_id = %s", (vendor_id,))


def _insert_run(conn, vendor_id: int, started_at: str, hash_val, count_val=None) -> int:
    """Insert a scraper_runs row with explicit started_at (for deterministic
    DESC ordering) + a chosen cohort_absent_set_hash (str or None)."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO scraper_runs "
            "(vendor_id, status, started_at, cohort_absent_set_hash, cohort_absent_count) "
            "VALUES (%s, 'success', %s, %s, %s) RETURNING id",
            (vendor_id, started_at, hash_val, count_val),
        )
        return cur.fetchone()["id"]


# ─── Test 1: finish_scraper_run round-trips both columns (set + NULL) ──────────
@mark_requires_db
def test_finish_scraper_run_persists_cohort_columns(conn, vendor):
    """finish_scraper_run with cohort_absent_set_hash + cohort_absent_count set
    persists both; the failure-path call shape (no cohort kwargs) round-trips
    NULL for both — the capture-wiring the pure suite can't reach."""
    _wipe_runs(conn, vendor["id"])
    counters = Counters(seen=4589)

    # (a) set path
    run_id = db.start_scraper_run(conn, vendor["id"], "test-sha")
    db.finish_scraper_run(
        conn, run_id, "success", None, None, counters, None, 200,
        cohort_absent_set_hash="deadbeefcafe",
        cohort_absent_count=159,
    )
    with conn.cursor() as cur:
        cur.execute(
            "SELECT cohort_absent_set_hash, cohort_absent_count "
            "FROM scraper_runs WHERE id = %s",
            (run_id,),
        )
        row = cur.fetchone()
    assert row["cohort_absent_set_hash"] == "deadbeefcafe", (
        f"hash not persisted: {row['cohort_absent_set_hash']!r}"
    )
    assert row["cohort_absent_count"] == 159, (
        f"count not persisted: {row['cohort_absent_count']!r}"
    )

    # (b) failure-path call shape — no cohort kwargs → NULL round-trip
    run_id2 = db.start_scraper_run(conn, vendor["id"], "test-sha")
    db.finish_scraper_run(
        conn, run_id2, "failed", "block", "x", counters, None, None,
    )
    with conn.cursor() as cur:
        cur.execute(
            "SELECT cohort_absent_set_hash, cohort_absent_count "
            "FROM scraper_runs WHERE id = %s",
            (run_id2,),
        )
        row2 = cur.fetchone()
    assert row2["cohort_absent_set_hash"] is None, (
        f"failure-path hash should be NULL, got {row2['cohort_absent_set_hash']!r}"
    )
    assert row2["cohort_absent_count"] is None, (
        f"failure-path count should be NULL, got {row2['cohort_absent_count']!r}"
    )


# ─── Test 2: get_recent_cohort_absent_hashes ordering + exclusion + NULL ───────
@mark_requires_db
def test_get_recent_cohort_absent_hashes_order_exclude_null(conn, vendor):
    """Seed 3 historical runs (newest carries a NULL hash) + 1 in-flight run.
    get_recent_cohort_absent_hashes(conn, vendor, in_flight_id, 2) returns the
    2 newest HISTORICAL by started_at DESC, excludes the in-flight run_id, and
    surfaces the NULL hash as-is (None)."""
    _wipe_runs(conn, vendor["id"])
    # Oldest -> newest historical.
    _insert_run(conn, vendor["id"], "2026-01-01T00:00:01Z", "hashC", 100)  # oldest
    _insert_run(conn, vendor["id"], "2026-01-01T00:00:02Z", "hashB", 110)  # middle
    _insert_run(conn, vendor["id"], "2026-01-01T00:00:03Z", None, None)    # newest historical, NULL
    # In-flight run is the newest of all by started_at; must be excluded.
    in_flight_id = _insert_run(
        conn, vendor["id"], "2026-01-01T00:00:04Z", "INFLIGHT_EXCLUDE_ME", 999
    )

    result = db.get_recent_cohort_absent_hashes(conn, vendor["id"], in_flight_id, 2)

    assert result == [None, "hashB"], (
        f"expected the 2 newest historical by started_at DESC with NULL "
        f"surfaced as-is and the in-flight run excluded; got {result!r}"
    )

    # K=1 boundary: limit 0 short-circuits to [] (no DB hit).
    assert db.get_recent_cohort_absent_hashes(conn, vendor["id"], in_flight_id, 0) == []


def main() -> int:
    conn = db.get_conn()
    vendor = _setup_test_vendor(conn)
    print(f"test vendor: id={vendor['id']} slug={vendor['slug']}")

    tests = [
        test_finish_scraper_run_persists_cohort_columns,
        test_get_recent_cohort_absent_hashes_order_exclude_null,
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
                _wipe_runs(conn, vendor["id"])
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
