"""scrapers/tests/test_onboarding_detection.py — CTK-214 behavioral guarantees for
the new-vendor onboarding-detection backend (migrations 0068 + 0069 per-channel split).

Every test fails if the function is dropped or its guarantee removed (no tautologies):

  Signal 1 — get_pending_onboarding_announcements(channel) / mark_onboarding_announced:
    * n is the BROWSEABLE in-stock count — in_stock AND NOT equipment AND NOT invert.
      Asserted against a fixture (a vendor seeded with OOS + invert + equipment rows
      announces the REDUCED count, not total) — the honest-framing invariant, never a
      live literal (live n drifts every scrape).
    * per-channel independence (0069): a dark vendor is pending on BOTH channels; an
      email announce leaves it pending on Discord and vice-versa; each channel's mark
      is fire-once on its own column; a backfilled vendor is pending on neither; an
      unknown channel RAISES.

  Signal 2 — get_onboarding_strip_state() / stamp_first_organic_drop_at():
    * the strip returns ACTIVE strips only — a vendor with first_organic_drop_at set
      (organically retired, incl. the pre-feature backfilled set) is excluded.
    * the organic stamp fires on a genuine guarded-just-listed survivor (cold-start-
      survived + bulk_cluster=false) and returns the timestamp.
    * BULK-COHORT SUPPRESSION (the load-bearing one): a >=50-row same-first_seen_at
      cohort that flip_new_bulk_clusters flags bulk_cluster=true is suppressed — the
      SAME 50 rows are kept-survivors BEFORE the flip (teeth) and vanish AFTER it, so
      the onboarding flood never stamps first_organic_drop_at.
    * gate: a NOT-announced vendor never stamps even with survivors present.
    * fire-once: an already-stamped vendor is never overwritten to now().

ISOLATION: every test runs inside ONE transaction on a NON-autocommit connection and
ROLLS BACK in teardown — nothing is ever committed to the live DB. The test vendor
carries a real-shaped slug (NOT '_'-prefixed) on purpose: the 0068 functions all apply
the CTK-213 belt (slug NOT LIKE '!_%'), so a '_'-prefixed vendor would be invisible to
the very functions under test. A non-committing real-slug vendor is the only way to
exercise the belt-applying path. requires_db (deselected by CI's -m "not requires_db").

Runnable as:
  python -m scrapers.tests.test_onboarding_detection
"""

from __future__ import annotations

import os
import sys
import traceback

import psycopg

from scrapers.common import bulk_cluster, db

try:
    import pytest
    mark_requires_db = pytest.mark.requires_db
except ImportError:
    mark_requires_db = lambda f: f


SLUG = "ctk214test"            # real-shaped (no leading '_') so the CTK-213 belt keeps it
DISPLAY = "CTK-214 Test Vendor"


# ---------------------------------------------------------------------------
# Seed helpers — all run inside the caller's open (uncommitted) transaction, so
# the 0068 functions see the fixture rows via the same connection.
# ---------------------------------------------------------------------------

def _seed_vendor(cur, *, email: str | None = None, discord: str | None = None,
                 first_organic: str | None = None, active: bool = True) -> int:
    """Insert the test vendor; return its id. `email` / `discord` / `first_organic` are
    SQL exprs relative to now() (e.g. \"now() - interval '1 day'\") or None — the two
    per-channel announce stamps + the organic stamp (CTK-214 0069 per-channel split).
    `active` exercises the active=true guard (the CTK-214 [2] fold)."""
    cur.execute(
        "INSERT INTO vendors (slug, display_name, base_url, platform, scrape_method, "
        "cadence_label, active, onboarding_announced_email_at, onboarding_announced_discord_at, "
        "first_organic_drop_at) "
        "VALUES (%s, %s, 'https://example.test', 'shopify', 'products_json', 'daily', %s, "
        f"{email or 'NULL'}, {discord or 'NULL'}, {first_organic or 'NULL'}) RETURNING id",
        (SLUG, DISPLAY, active),
    )
    return cur.fetchone()["id"]


def _seed_listing(cur, vendor_id: int, n: int, *, in_stock: bool, category: str | None,
                  first_seen: str = "now() - interval '1 hour'", bulk_cluster_val: bool = False) -> None:
    """Insert `n` listings for the vendor. category None = coral (browseable);
    'invert'/'equipment' = hidden. first_seen is a SQL expr (controls cold-start +
    cohort day). product_url is unique per row to avoid collisions."""
    cat = "NULL" if category is None else f"'{category}'"
    for i in range(n):
        cur.execute(
            "INSERT INTO vendor_listings (vendor_id, product_url, raw_title, normalized_title, "
            "in_stock, category, first_seen_at, is_auction, bulk_cluster) "
            f"VALUES (%s, %s, %s, %s, %s, {cat}, {first_seen}, false, %s)",
            (vendor_id, f"https://example.test/p/{vendor_id}/{category}/{in_stock}/{i}",
             f"Test Coral {i}", f"test coral {i}", in_stock, bulk_cluster_val),
        )


def _seed_success_run_before(cur, vendor_id: int) -> None:
    """A successful scraper_run that finished BEFORE the seeded listings' first_seen_at,
    so just-listed rows are is_cold_start=false (cold-start-survived) and thus
    kept-eligible. Without this every just-listed row is cold_start -> never kept."""
    cur.execute(
        "INSERT INTO scraper_runs (vendor_id, started_at, finished_at, status, "
        "listings_seen, listings_new, listings_price_changed, listings_restocked, "
        "listings_oos, per_category_counts) "
        "VALUES (%s, now() - interval '2 days', now() - interval '2 days', 'success', "
        "0, 0, 0, 0, 0, '{}'::jsonb)",
        (vendor_id,),
    )


def _pending_n(cur, channel: str) -> int | None:
    cur.execute(
        "SELECT n FROM get_pending_onboarding_announcements(%s) WHERE vendor_slug = %s",
        (channel, SLUG),
    )
    row = cur.fetchone()
    return row["n"] if row else None


def _guarded_just_listed_count(cur, vendor_id: int) -> int:
    """Kept just-listed survivors the 0068 organic check sees for this vendor."""
    cur.execute(
        "SELECT count(*)::int AS n FROM get_f7_arrivals_guarded(24 * 3650, ARRAY['just-listed']) le "
        "WHERE le.vendor_slug = %s",
        (SLUG,),
    )
    return cur.fetchone()["n"]


def _first_organic(cur, vendor_id: int):
    cur.execute("SELECT first_organic_drop_at FROM vendors WHERE id = %s", (vendor_id,))
    return cur.fetchone()["first_organic_drop_at"]


# ---------------------------------------------------------------------------
# Rollback-isolated connection fixture.
# ---------------------------------------------------------------------------

def _open_iso_conn() -> psycopg.Connection:
    # CTK-219: open via get_test_conn (TEST_DATABASE_URL branch; fails closed on an
    # unset/prod DSN per CTK-215) instead of raw psycopg.connect(NEON_DATABASE_URL),
    # which targeted prod directly and skipped on the D3 CI lane (prod omitted there).
    # get_test_conn returns an autocommit connection; flip to non-autocommit so the
    # per-test rollback-in-teardown isolation still holds (no write reaches the branch).
    # dict_row row_factory is already set by get_test_conn.
    conn = db.get_test_conn()
    conn.autocommit = False
    return conn


try:
    import pytest

    @pytest.fixture
    def iso_conn():
        """Non-autocommit connection; every test's writes ROLL BACK in teardown —
        nothing reaches the live DB."""
        if not os.environ.get("TEST_DATABASE_URL"):
            pytest.skip("TEST_DATABASE_URL not set — live-DB test")
        conn = _open_iso_conn()
        try:
            yield conn
        finally:
            conn.rollback()
            conn.close()
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Signal 1 — pending announcements + fire-once.
# ---------------------------------------------------------------------------

def _mark(cur, channel: str) -> list[str]:
    cur.execute("SELECT stamped_slug FROM mark_onboarding_announced(ARRAY[%s], %s)", (SLUG, channel))
    return [r["stamped_slug"] for r in cur.fetchall()]


@mark_requires_db
def test_pending_n_is_browseable_in_stock(iso_conn):
    """n counts in-stock browseable corals ONLY — OOS, invert, and equipment rows are
    excluded. Seed 3 browseable + 2 OOS + 4 invert + 5 equipment = 14 total; n must be
    3, not 14. The honest-framing invariant, asserted against the fixture not a literal."""
    with iso_conn.cursor() as cur:
        vid = _seed_vendor(cur)                             # pending on both channels
        _seed_listing(cur, vid, 3, in_stock=True, category=None)        # browseable coral
        _seed_listing(cur, vid, 2, in_stock=False, category=None)       # OOS coral — excluded
        _seed_listing(cur, vid, 4, in_stock=True, category="invert")    # invert — excluded
        _seed_listing(cur, vid, 5, in_stock=True, category="equipment") # equipment — excluded
        n = _pending_n(cur, "email")
    assert n == 3, f"pending n = {n}, expected 3 browseable in-stock (OOS+invert+equipment must not count)"


@mark_requires_db
def test_pending_excludes_zero_browseable(iso_conn):
    """A vendor with only OOS / hidden-category stock has nothing browseable to announce
    -> n > 0 filter drops it from pending entirely."""
    with iso_conn.cursor() as cur:
        vid = _seed_vendor(cur)
        _seed_listing(cur, vid, 6, in_stock=False, category=None)       # all OOS
        _seed_listing(cur, vid, 3, in_stock=True, category="equipment") # all equipment
        n = _pending_n(cur, "email")
    assert n is None, f"vendor with no browseable in-stock stock appeared in pending (n={n}), expected absent"


@mark_requires_db
def test_channels_announce_independently(iso_conn):
    """The load-bearing per-channel guarantee (0069): a dark vendor is pending on BOTH
    channels; an email announce leaves it pending on Discord (and vice-versa); each
    channel's mark is fire-once on its own column."""
    with iso_conn.cursor() as cur:
        vid = _seed_vendor(cur)                             # NULL/NULL — pending both
        _seed_listing(cur, vid, 4, in_stock=True, category=None)
        assert _pending_n(cur, "email") == 4 and _pending_n(cur, "discord") == 4, "should start pending on both"

        assert _mark(cur, "email") == [SLUG], "email mark should stamp the vendor"
        assert _pending_n(cur, "email") is None, "vendor must leave email-pending after email announce"
        assert _pending_n(cur, "discord") == 4, "vendor must STILL be discord-pending (channels independent)"

        assert _mark(cur, "email") == [], "re-mark email must stamp nothing (fire-once per channel)"

        assert _mark(cur, "discord") == [SLUG], "discord mark should stamp the vendor"
        assert _pending_n(cur, "discord") is None, "vendor must leave discord-pending after discord announce"


@mark_requires_db
def test_backfilled_pending_neither_channel(iso_conn):
    """A vendor announced on both channels (the established/backfilled shape) is pending
    on neither."""
    with iso_conn.cursor() as cur:
        vid = _seed_vendor(cur, email="now() - interval '10 days'", discord="now() - interval '10 days'")
        _seed_listing(cur, vid, 5, in_stock=True, category=None)
        assert _pending_n(cur, "email") is None and _pending_n(cur, "discord") is None, (
            "fully-announced vendor must be pending on neither channel"
        )


@mark_requires_db
def test_inactive_vendor_excluded(iso_conn):
    """The active=true guard (CTK-214 [2] fold) has teeth: an INACTIVE vendor with
    browseable stock and NULL/NULL channel stamps is excluded from pending on both
    channels AND cannot be stamped by mark — a deactivated vendor never re-announces."""
    with iso_conn.cursor() as cur:
        vid = _seed_vendor(cur, active=False)              # paused vendor, never announced
        _seed_listing(cur, vid, 4, in_stock=True, category=None)
        assert _pending_n(cur, "email") is None and _pending_n(cur, "discord") is None, (
            "inactive vendor must not appear in pending (active guard)"
        )
        assert _mark(cur, "email") == [], "mark must not stamp an inactive vendor (active guard)"


@mark_requires_db
def test_invalid_channel_raises(iso_conn):
    """An unknown channel RAISES rather than silently returning the wrong set."""
    import psycopg
    with iso_conn.cursor() as cur:
        try:
            cur.execute("SELECT * FROM get_pending_onboarding_announcements('sms')")
            cur.fetchall()
            assert False, "invalid channel must raise"
        except psycopg.errors.RaiseException:
            iso_conn.rollback()  # clear the aborted tx so teardown's rollback is a no-op


# ---------------------------------------------------------------------------
# Signal 2 — strip state + organic stamp.
# ---------------------------------------------------------------------------

@mark_requires_db
def test_strip_excludes_organically_retired(iso_conn):
    """get_onboarding_strip_state returns ACTIVE strips only: an announced vendor with
    first_organic_drop_at set (retired-by-data, incl. the backfilled set) is excluded;
    an announced vendor with it NULL is present."""
    with iso_conn.cursor() as cur:
        # Announced + retired (organic stamped) -> excluded.
        vid = _seed_vendor(cur, email="now() - interval '1 day'",
                           first_organic="now() - interval '2 hours'")
        _seed_listing(cur, vid, 5, in_stock=True, category=None)
        cur.execute("SELECT 1 FROM get_onboarding_strip_state() WHERE vendor_slug = %s", (SLUG,))
        assert cur.fetchone() is None, "organically-retired vendor must NOT be in the strip"

        # Flip it to active (first_organic NULL) -> present.
        cur.execute("UPDATE vendors SET first_organic_drop_at = NULL WHERE id = %s", (vid,))
        cur.execute("SELECT n FROM get_onboarding_strip_state() WHERE vendor_slug = %s", (SLUG,))
        row = cur.fetchone()
        assert row is not None and row["n"] == 5, f"active-strip vendor must be present with n=5, got {row}"


@mark_requires_db
def test_organic_stamp_fires_on_survivor(iso_conn):
    """A genuine guarded-just-listed survivor (cold-start-survived, small cohort,
    bulk_cluster=false) stamps first_organic_drop_at and returns the timestamp."""
    with iso_conn.cursor() as cur:
        vid = _seed_vendor(cur, email="now() - interval '1 day'")
        _seed_success_run_before(cur, vid)                              # past cold-start
        _seed_listing(cur, vid, 3, in_stock=True, category=None)        # small organic cohort
        assert _guarded_just_listed_count(cur, vid) == 3, "3 rows should be kept survivors"

        cur.execute("SELECT stamp_first_organic_drop_at(%s) AS s", (SLUG,))
        stamp = cur.fetchone()["s"]
        assert stamp is not None, "stamp should fire on a kept survivor"
        assert _first_organic(cur, vid) is not None, "first_organic_drop_at must be set after stamp"


@mark_requires_db
def test_organic_stamp_bulk_cohort_suppressed(iso_conn):
    """THE load-bearing one. A >=50-row same-first_seen_at cohort: the SAME rows are
    kept survivors BEFORE flip_new_bulk_clusters runs (teeth), and vanish AFTER it flags
    bulk_cluster=true — so the onboarding flood never stamps first_organic_drop_at.
    Uses the REAL write-time flip (not a hand-set column) to prove the integration."""
    n = bulk_cluster.BULK_CLUSTER_MIN                                   # exactly the threshold (50)
    with iso_conn.cursor() as cur:
        vid = _seed_vendor(cur, email="now() - interval '1 day'")
        _seed_success_run_before(cur, vid)
        # One identical first_seen_at for the whole cohort (a single-timestamp dump).
        _seed_listing(cur, vid, n, in_stock=True, category=None,
                      first_seen="date_trunc('second', now() - interval '30 minutes')")
        # Teeth: before the flip these 50 rows ARE kept survivors (would stamp).
        assert _guarded_just_listed_count(cur, vid) == n, (
            f"pre-flip the {n}-row cohort should be kept survivors (else the test proves nothing)"
        )

        flipped = bulk_cluster.flip_new_bulk_clusters(iso_conn, vid)    # real write-time hook
        assert flipped == n, f"flip should flag all {n} rows bulk_cluster=true, flipped {flipped}"
        assert _guarded_just_listed_count(cur, vid) == 0, "bulk_cluster cohort must be suppressed from the guarded source"

        cur.execute("SELECT stamp_first_organic_drop_at(%s) AS s", (SLUG,))
        assert cur.fetchone()["s"] is None, "bulk cohort must NOT stamp first_organic_drop_at"
        assert _first_organic(cur, vid) is None, "first_organic_drop_at must stay NULL for the onboarding flood"


@mark_requires_db
def test_organic_stamp_gate_not_announced(iso_conn):
    """The post-onboarding gate: a NOT-announced vendor never stamps, even with a kept
    survivor present (a drop in the pre-announce gap has no strip to retire)."""
    with iso_conn.cursor() as cur:
        vid = _seed_vendor(cur)                                        # NOT announced (NULL/NULL)
        _seed_success_run_before(cur, vid)
        _seed_listing(cur, vid, 3, in_stock=True, category=None)
        assert _guarded_just_listed_count(cur, vid) == 3, "survivors should exist"

        cur.execute("SELECT stamp_first_organic_drop_at(%s) AS s", (SLUG,))
        assert cur.fetchone()["s"] is None, "un-announced vendor must NOT stamp"
        assert _first_organic(cur, vid) is None, "first_organic_drop_at must stay NULL pre-announce"


@mark_requires_db
def test_organic_stamp_fire_once(iso_conn):
    """An already-stamped vendor is never overwritten and the stamp returns NULL (no
    fresh stamp this call) — so the diff.py hook logs only genuine first-drop events,
    not a no-op on the backfilled set (CTK-214 [3])."""
    with iso_conn.cursor() as cur:
        vid = _seed_vendor(cur, email="now() - interval '2 days'",
                           first_organic="now() - interval '1 day'")
        _seed_success_run_before(cur, vid)
        _seed_listing(cur, vid, 3, in_stock=True, category=None)       # fresh survivors present
        cur.execute("SELECT first_organic_drop_at AS f FROM vendors WHERE id = %s", (vid,))
        before = cur.fetchone()["f"]

        cur.execute("SELECT stamp_first_organic_drop_at(%s) AS s", (SLUG,))
        returned = cur.fetchone()["s"]
        after = _first_organic(cur, vid)
        assert returned is None, "stamp must return NULL when already stamped (no fresh stamp this call)"
        assert after == before, "first_organic_drop_at must be unchanged (fire-once)"


# ---------------------------------------------------------------------------
# Script-mode runner.
# ---------------------------------------------------------------------------

def main() -> int:
    if not os.environ.get("TEST_DATABASE_URL"):
        print("TEST_DATABASE_URL not set — skipping live-DB suite")
        return 0
    checks = [
        test_pending_n_is_browseable_in_stock,
        test_pending_excludes_zero_browseable,
        test_channels_announce_independently,
        test_backfilled_pending_neither_channel,
        test_inactive_vendor_excluded,
        test_invalid_channel_raises,
        test_strip_excludes_organically_retired,
        test_organic_stamp_fires_on_survivor,
        test_organic_stamp_bulk_cohort_suppressed,
        test_organic_stamp_gate_not_announced,
        test_organic_stamp_fire_once,
    ]
    failures = []
    for fn in checks:
        conn = _open_iso_conn()
        try:
            fn(conn)
            print(f"  [PASS] {fn.__name__}")
        except AssertionError as e:
            print(f"  [FAIL] {fn.__name__}: {e}")
            failures.append(fn.__name__)
        except Exception as e:  # noqa: BLE001
            print(f"  [ERROR] {fn.__name__}: {type(e).__name__}: {e}")
            traceback.print_exc()
            failures.append(fn.__name__)
        finally:
            conn.rollback()
            conn.close()
    print()
    print(f"{len(checks) - len(failures)}/{len(checks)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
