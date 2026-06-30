"""scrapers/tests/test_rematch.py — CTK-029 v1 B2 invariant lock on
scrapers.rematch.rematch_one.

Pins three failure-mode-discriminating invariants before B3a behavior
locks (plan §B2):

  (i)   matched_at = first_seen_at on backfill (NOT now()) per arch
        decision #30. Failure mode the test guards against: notifier
        polls WHERE matched_at > last_poll AND named_coral_id IS NOT
        NULL — if backfill spuriously sets matched_at = now(), every
        backfilled row blasts a retroactive wishlist hit on Phase 4
        notifier first-poll. Recovery is hard (sends already went,
        dedup is per-listing not per-event).

  (ii)  Single-coral cache filter — rematch_one(named_coral_id=N) only
        evaluates listings against coral N's filtered cache. Listings
        whose title would match a different coral (M ≠ N) in a fully-
        loaded cache stay named_coral_id=NULL post-rematch. Failure
        mode the test guards against: a regression that drops the
        cache filter would re-match every listing against the full
        seed, spuriously overwriting matches set by real-time scrape
        + cross-vendor aliases under CTK-030 v1.

  (iii) Last-seen-at window — listings with last_seen_at < now() - 7
        days are skipped. Failure mode the test guards against: a
        regression that scans the full vendor_listings table would
        re-match dormant listings whose first_seen_at is months/years
        in the past, polluting analytics + slowing the run beyond
        §3.8's "takes seconds" budget.

Hits live Neon Postgres via psycopg. Uses a dedicated test vendor
(slug='_ctk029_test', active=false) + two synthetic test named_corals
with disjoint canonical names that no real listing can match — pre-
existing pattern from scrapers/tests/test_first_seen_at.py.

Runnable as:
  python -m scrapers.tests.test_rematch

Requires NEON_DATABASE_URL in env (auto-loaded from .env at repo root
via scrapers/common/db.py:44 load_dotenv()).
"""

from __future__ import annotations

import sys
import traceback
from datetime import datetime, timedelta, timezone

from scrapers.common import db
from scrapers.rematch import rematch_one

try:
    import pytest
    mark_requires_db = pytest.mark.requires_db
except ImportError:
    mark_requires_db = lambda f: f


TEST_VENDOR_SLUG = "_ctk029_test"
# Synthetic canonical names chosen so trigram Jaccard between them is
# well below the 0.7 stage-6 fuzzy threshold (computed Jaccard ~0.4)
# and so no production listing title can collide. Both rows are active
# so production scrapes load them into the match cache as a no-op
# (~2 trigram comparisons per listing per scrape; negligible).
TEST_CORAL_ALPHA_CANONICAL = "Ctk029 Alphacoral Xxxxx"
TEST_CORAL_ALPHA_NORMALIZED = "ctk029 alphacoral xxxxx"
TEST_CORAL_ALPHA_SLUG = "ctk029-alphacoral-xxxxx"
TEST_CORAL_BETA_CANONICAL = "Ctk029 Betacoral Yyyyy"
TEST_CORAL_BETA_NORMALIZED = "ctk029 betacoral yyyyy"
TEST_CORAL_BETA_SLUG = "ctk029-betacoral-yyyyy"


def _setup_test_vendor(conn) -> dict:
    """Idempotent test-vendor setup. UPSERT shape — flips active=true on
    every run so a pre-existing active=false row from earlier sessions
    (e.g., CTK-029 v1 Session 2 pre-fold-batch state) gets healed.

    active=true is required because rematch.py:170 SELECT JOINs vendors
    on v.active=TRUE per /code-review fold-batch finding #5. Cron-safety
    is preserved by the absence of a corresponding workflow YAML at
    .github/workflows/scrape-_ctk029_test.yml — the test vendor has no
    cron path even when active=true.
    """
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO vendors "
            "(slug, display_name, base_url, platform, scrape_method, "
            "cadence_label, image_strategy, active) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (slug) DO UPDATE SET active = EXCLUDED.active "
            "RETURNING id, slug",
            (
                TEST_VENDOR_SLUG,
                "CTK-029 test vendor",
                "https://example.test",
                "shopify",
                "products_json",
                "daily",
                "mirror",
                True,
            ),
        )
        return cur.fetchone()


def _setup_test_coral(conn, canonical: str, normalized: str, slug: str) -> dict:
    """Idempotent test-coral setup with active-heal. UPSERT shape mirroring
    _setup_test_vendor:84-103 — flips active=true on every run.

    CTK-219 Fix 1: the prior SELECT-by-slug-then-INSERT never healed active.
    The ctk029 alpha/beta corals were stranded active=false by an earlier
    session (named_coral_id=21 = alpha), so the SELECT branch returned that
    stale inactive row and rematch_one raised "named_coral_id=21 not found
    or inactive" (rematch._load_single_coral_cache filters
    `WHERE id = %s AND active = TRUE`). ON CONFLICT (slug) DO UPDATE SET
    active = true heals the flag without mutating canonical/normalized
    identity. Returns {id, canonical_name}.
    """
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO named_corals "
            "(canonical_name, normalized_name, slug, origin_vendor, "
            "coral_type, category, requires_vendor_prefix, active) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (slug) DO UPDATE SET active = true "
            "RETURNING id, canonical_name",
            (canonical, normalized, slug, "ctk029-test", "sps", 1, False, True),
        )
        return cur.fetchone()


def _wipe_listings(conn, vendor_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM vendor_listings WHERE vendor_id = %s", (vendor_id,))


def _insert_listing(
    conn,
    vendor_id: int,
    product_url: str,
    normalized_title: str,
    first_seen_at: str,
    last_seen_at: str,
) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO vendor_listings "
            "(vendor_id, product_url, raw_title, normalized_title, in_stock, "
            "first_seen_at, last_seen_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) "
            "RETURNING id",
            (
                vendor_id, product_url, normalized_title, normalized_title,
                True, first_seen_at, last_seen_at,
            ),
        )
        return cur.fetchone()


def _select_match_fields(conn, listing_id: int) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT named_coral_id, match_confidence, match_method, "
            "matched_at, first_seen_at, last_seen_at "
            "FROM vendor_listings WHERE id = %s",
            (listing_id,),
        )
        return cur.fetchone()


# ─── Test 1: matched_at = first_seen_at on backfill (NOT now()) ──────────────
@mark_requires_db
def test_matched_at_equals_first_seen_at_on_backfill(conn, vendor, coral_alpha, coral_beta):
    """(i) — decision #30 lock. Insert a listing with first_seen_at=T0 (past)
    whose normalized_title matches coral_alpha. Run rematch_one against
    coral_alpha's id. Assert post-rematch:
      - named_coral_id == coral_alpha.id (cascade hit)
      - matched_at == first_seen_at (exact equality — backfill discipline,
        NOT now())

    Pre-discipline: matched_at = now() would put the listing's match in the
    notifier-eligible window WHERE matched_at > last_poll on first poll,
    blasting a retroactive wishlist hit. Post-discipline: matched_at sits
    in the past, naturally excluded from the notifier.
    """
    _wipe_listings(conn, vendor["id"])
    t0 = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    last_seen = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    listing = _insert_listing(
        conn, vendor["id"],
        "https://example.test/p/ctk029-matched-at-discipline",
        TEST_CORAL_ALPHA_NORMALIZED,
        first_seen_at=t0,
        last_seen_at=last_seen,
    )

    rematch_one(conn, named_coral_id=coral_alpha["id"])

    after = _select_match_fields(conn, listing["id"])
    assert after["named_coral_id"] == coral_alpha["id"], (
        f"expected named_coral_id={coral_alpha['id']} (cascade hit); "
        f"got {after['named_coral_id']!r} method={after['match_method']!r}"
    )
    assert after["matched_at"] == after["first_seen_at"], (
        f"decision #30 violated: matched_at must equal first_seen_at on "
        f"backfill (NOT now()). got matched_at={after['matched_at']!r} "
        f"first_seen_at={after['first_seen_at']!r}"
    )


# ─── Test 2: single-coral cache filter ──────────────────────────────────────
@mark_requires_db
def test_single_coral_cache_filter_discriminates(conn, vendor, coral_alpha, coral_beta):
    """(ii) — cascade against rematch_one(N) only sees coral N's row + its
    aliases. A listing whose title matches coral M (M ≠ N) stays
    named_coral_id=NULL post-rematch.

    Insert two listings:
      - L_alpha: title matches coral_alpha's canonical name
      - L_beta:  title matches coral_beta's canonical name

    Run rematch_one against coral_alpha. Assert:
      - L_alpha.named_coral_id == coral_alpha.id (in-cache match)
      - L_beta.named_coral_id is None (coral_beta absent from filtered cache;
        cascade cannot reach it)
    """
    _wipe_listings(conn, vendor["id"])
    t0 = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    last_seen = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    l_alpha = _insert_listing(
        conn, vendor["id"],
        "https://example.test/p/ctk029-filter-alpha",
        TEST_CORAL_ALPHA_NORMALIZED,
        first_seen_at=t0, last_seen_at=last_seen,
    )
    l_beta = _insert_listing(
        conn, vendor["id"],
        "https://example.test/p/ctk029-filter-beta",
        TEST_CORAL_BETA_NORMALIZED,
        first_seen_at=t0, last_seen_at=last_seen,
    )

    rematch_one(conn, named_coral_id=coral_alpha["id"])

    after_alpha = _select_match_fields(conn, l_alpha["id"])
    after_beta = _select_match_fields(conn, l_beta["id"])
    assert after_alpha["named_coral_id"] == coral_alpha["id"], (
        f"L_alpha should match coral_alpha={coral_alpha['id']}; "
        f"got {after_alpha['named_coral_id']!r}"
    )
    assert after_beta["named_coral_id"] is None, (
        f"L_beta should stay NULL — coral_beta is filtered out of the "
        f"cache. got named_coral_id={after_beta['named_coral_id']!r} "
        f"method={after_beta['match_method']!r}"
    )


# ─── Test 3: last-seen-at window ────────────────────────────────────────────
@mark_requires_db
def test_last_seen_at_7d_window_skips_dormant(conn, vendor, coral_alpha, coral_beta):
    """(iii) — listings with last_seen_at < now() - interval '7 days' are
    skipped by the scan WHERE clause.

    Insert two listings whose titles BOTH match coral_alpha:
      - L_fresh:  last_seen_at = now() - 2 days (inside window)
      - L_dormant: last_seen_at = now() - 10 days (outside window)

    Run rematch_one against coral_alpha. Assert:
      - L_fresh.named_coral_id == coral_alpha.id (in-window, matched)
      - L_dormant.named_coral_id is None (outside window, skipped)
    """
    _wipe_listings(conn, vendor["id"])
    t0 = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    fresh_last_seen = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    dormant_last_seen = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    l_fresh = _insert_listing(
        conn, vendor["id"],
        "https://example.test/p/ctk029-fresh",
        TEST_CORAL_ALPHA_NORMALIZED,
        first_seen_at=t0, last_seen_at=fresh_last_seen,
    )
    l_dormant = _insert_listing(
        conn, vendor["id"],
        "https://example.test/p/ctk029-dormant",
        TEST_CORAL_ALPHA_NORMALIZED,
        first_seen_at=t0, last_seen_at=dormant_last_seen,
    )

    rematch_one(conn, named_coral_id=coral_alpha["id"])

    after_fresh = _select_match_fields(conn, l_fresh["id"])
    after_dormant = _select_match_fields(conn, l_dormant["id"])
    assert after_fresh["named_coral_id"] == coral_alpha["id"], (
        f"L_fresh (last_seen_at=now()-2d) should match coral_alpha={coral_alpha['id']}; "
        f"got {after_fresh['named_coral_id']!r}"
    )
    assert after_dormant["named_coral_id"] is None, (
        f"L_dormant (last_seen_at=now()-10d) is outside the 7-day window — "
        f"must be skipped. got named_coral_id={after_dormant['named_coral_id']!r}"
    )


def main() -> int:
    with db.get_test_conn() as conn:
        vendor = _setup_test_vendor(conn)
        coral_alpha = _setup_test_coral(
            conn, TEST_CORAL_ALPHA_CANONICAL,
            TEST_CORAL_ALPHA_NORMALIZED, TEST_CORAL_ALPHA_SLUG,
        )
        coral_beta = _setup_test_coral(
            conn, TEST_CORAL_BETA_CANONICAL,
            TEST_CORAL_BETA_NORMALIZED, TEST_CORAL_BETA_SLUG,
        )
        print(
            f"test fixtures: vendor.id={vendor['id']} "
            f"coral_alpha.id={coral_alpha['id']} "
            f"coral_beta.id={coral_beta['id']}"
        )

        tests = [
            test_matched_at_equals_first_seen_at_on_backfill,
            test_single_coral_cache_filter_discriminates,
            test_last_seen_at_7d_window_skips_dormant,
        ]

        failures: list[tuple[str, str]] = []
        for fn in tests:
            name = fn.__name__
            try:
                fn(conn, vendor, coral_alpha, coral_beta)
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
