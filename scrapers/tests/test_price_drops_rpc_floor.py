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
body) — apply via `python -m scripts.apply_migration 35` (CTK-208 shared
runner; the per-migration apply_migration_0035.py clone was removed).

Test rows are seeded (in_stock=true, in-window onset) on a dedicated
active=true, NON-underscore vendor 'ctk219-pricedrops-floor' so they
survive get_recent_price_drops's final vendors JOIN filter
(`v.active = true AND v.slug NOT LIKE '!_%' ESCAPE '!'`, CTK-213). The
prior active=false, '_'-prefixed '_ctk124_test' was filtered out of the
RPC entirely, so the membership pins could never see their own rows
(CTK-219 Fix 2 — the original "no vendors.active predicate" diagnosis was
disproven by the live function body). Safe because CTK-215 scopes
requires_db to a Neon branch (TEST_DATABASE_URL), never prod /deals.
Cleanup is the module-scoped autouse teardown below (the per-test
finally-wipe in main() does NOT run under pytest, and the now-RPC-visible
rows would otherwise accumulate on the branch).

Hits live Neon Postgres via psycopg. Mirrors
test_markdown_started_at_capture.py shape. Pytest-discovery requires a
`conn` + `vendor` fixture pair the project does not declare globally;
standalone-mode main() builds them inline.

Runnable as:
  python -m scrapers.tests.test_price_drops_rpc_floor
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


# CTK-219 Fix 2: a DEDICATED active=true, non-underscore vendor (was the
# active=false '_ctk124_test' shared with test_markdown_started_at_capture).
# get_recent_price_drops filters its final vendors JOIN on
# `v.active = true AND v.slug NOT LIKE '!_%' ESCAPE '!'` (CTK-213), so the
# old seed vendor was filtered out of the RPC entirely and these floor pins
# could never see their own rows. Non-underscore + active=true so seeded rows
# survive the RPC filter; safe because CTK-215 scopes requires_db to a Neon
# branch (TEST_DATABASE_URL), never prod /deals. The capture suite keeps
# '_ctk124_test' (it never calls the RPC) — no longer shared.
TEST_VENDOR_SLUG = "ctk219-pricedrops-floor"
TEST_VENDOR_DISPLAY = "CTK-219 TEST pricedrops floor — not a real vendor"
URL_EXACT_5PCT = "https://example.test/p/floor-pin-exact-5pct"
URL_SUB_5PCT = "https://example.test/p/floor-pin-sub-5pct"
URL_TIE_A = "https://example.test/p/tie-pin-a"
URL_TIE_B = "https://example.test/p/tie-pin-b"
WINDOW_DAYS = 7


def _setup_test_vendor(conn) -> dict:
    """Idempotent test-vendor setup, UPSERT-heal to active=true (CTK-219 Fix 2).
    active=true + non-underscore slug so seeded rows survive the
    get_recent_price_drops vendors JOIN filter (CTK-213). The unmistakable
    display_name flags the row as synthetic for anyone scanning the branch's
    vendors table — the dropped '_' prefix no longer carries that signal. No
    scrape workflow exists for this slug, so active=true never triggers a cron."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO vendors "
            "(slug, display_name, base_url, platform, scrape_method, "
            "cadence_label, image_strategy, active) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (slug) DO UPDATE SET "
            "active = true, display_name = EXCLUDED.display_name "
            "RETURNING id, slug",
            (
                TEST_VENDOR_SLUG,
                TEST_VENDOR_DISPLAY,
                "https://example.test",
                "shopify",
                "products_json",
                "daily",
                "mirror",
                True,
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


try:
    import pytest as _pytest_cleanup

    @_pytest_cleanup.fixture(scope="module", autouse=True)
    def _module_cleanup():
        """CTK-219 Fix 2 — wipe this vendor's listings after the suite. The
        per-test finally-wipe in main() does NOT run under pytest, and the
        vendor is now active=true / RPC-visible, so leaked seed rows would
        otherwise accumulate on the branch (harmless — no /deals consumer on
        the test branch — but hygiene; mirrors test_price_drops_rpc_union's
        teardown). Keyed off TEST_DATABASE_URL so it no-ops with no test
        target and never opens a prod connection to clean up."""
        yield
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
