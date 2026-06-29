"""scrapers/tests/test_vendor_drop_cadence.py — CTK-208 port of the orphan O11
guarantees from the deleted apply_migration_0062 verify block (CTK-204 drop-cadence
function family).

Exercises BEHAVIOR of get_vendor_recent_drops + get_vendor_drop_cadence — each test
fails if the function is dropped or its guarantee removed:

  Scope A — get_vendor_recent_drops(slug, window_days, limit):
    * a qualifying vendor returns a non-empty feed ordered first_seen_at DESC, and
      every returned id is non-equipment (INV-07) + bulk_cluster=false (INV-08) — the
      INV join has teeth (fail-if-the-join-were-dropped).
    * a quiet vendor returns ZERO rows (the honest "quiet lately" state, not an error).
  Scope B — get_vendor_drop_cadence(slug):
    * qualifies_for_histogram across the live fleet equals EXACTLY the ratified set
      {wwc, tsa, jf, pacific_east}. This is the CTK-204 gate-drift alarm: "if the set
      drifts, the gate's wrong" — a failure here means the gate (organic_drop_count
      >= 15) is mis-specified OR the fleet genuinely drifted; re-confirm before
      editing the gate.
    * quiet vendors (battlecorals, cornbred) report organic_drop_count = 0,
      last_organic_drop_at NULL, qualifies_for_histogram = false.
    * DOW buckets sum to organic_drop_count for every vendor (no drop lost/double-counted).

These are LIVE-FLEET assertions by design (they were the apply-time gate). They are
`requires_db` so CI's `-m "not requires_db"` deselects them — they run only in the
local live suite, exactly where a fleet/gate-drift alarm belongs.

The fleet sweep is ONE LATERAL round-trip computed ONCE (module-scoped fixture) — not
a per-vendor call loop repeated per test. get_vendor_drop_cadence is a heavy aggregate;
a 17-vendor sequential loop run four times kept a single connection busy long enough
that Neon dropped it under load (CTK-208 flake). One set-returning LATERAL is fast and
robust.

Runnable as:
  python -m scrapers.tests.test_vendor_drop_cadence
"""

from __future__ import annotations

import os
import sys
import traceback

from scrapers.common import db

try:
    import pytest
    mark_requires_db = pytest.mark.requires_db
except ImportError:
    mark_requires_db = lambda f: f


EXPECTED_QUALIFIERS = {"wwc", "tsa", "jf", "pacific_east"}
QUALIFYING_VENDOR = "wwc"
QUIET_VENDORS = ("battlecorals", "cornbred")
_DOW_COLS = ("dow_sun", "dow_mon", "dow_tue", "dow_wed", "dow_thu", "dow_fri", "dow_sat")


def _fleet_cadence(conn) -> dict[str, dict]:
    """get_vendor_drop_cadence for every real (non-test) vendor in ONE LATERAL
    round-trip — keyed by slug."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT v.slug AS slug, c.* "
            "FROM vendors v, LATERAL get_vendor_drop_cadence(v.slug) c "
            "WHERE v.slug NOT LIKE '\\_%' "
            "ORDER BY v.slug"
        )
        return {r["slug"]: r for r in cur.fetchall()}


try:
    import pytest

    @pytest.fixture(scope="module")
    def fleet_cadence():
        """Module-scoped: sweep the fleet once for all Scope-B assertions. Opens its
        own short-lived connection (independent of the function-scoped conn fixture).
        CTK-215: targets the TEST branch via get_test_conn; the skip gate keys off
        TEST_DATABASE_URL to match (NEON_DATABASE_URL is prod, never the test target)."""
        if not os.environ.get("TEST_DATABASE_URL"):
            pytest.skip("TEST_DATABASE_URL not set — live-DB test")
        with db.get_test_conn() as conn:
            return _fleet_cadence(conn)
except ImportError:
    pass


@mark_requires_db
def test_recent_drops_feed_ordered_and_inv_clean(conn):
    """Scope A — qualifying vendor feed is non-empty, ordered first_seen_at DESC, and
    every row is non-equipment + bulk_cluster=false (INV-07/INV-08 join has teeth).
    A quiet vendor returns zero rows."""
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM get_vendor_recent_drops(%s, 60, NULL)", (QUALIFYING_VENDOR,))
        rows = cur.fetchall()
    assert rows, f"get_vendor_recent_drops({QUALIFYING_VENDOR!r}) returned 0 rows (fleet drift — re-confirm)"
    fs = [r["first_seen_at"] for r in rows]
    assert fs == sorted(fs, reverse=True), "feed not ordered first_seen_at DESC"
    ids = [r["id"] for r in rows]
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*)::int AS n FROM vendor_listings "
            "WHERE id = ANY(%s) AND (category = 'equipment' OR bulk_cluster = true)",
            (ids,),
        )
        leaked = cur.fetchone()["n"]
    assert leaked == 0, f"{leaked} feed rows are equipment/bulk_cluster — INV-07/INV-08 join not enforced"
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*)::int AS n FROM get_vendor_recent_drops(%s, 60, NULL)", (QUIET_VENDORS[0],))
        quiet = cur.fetchone()["n"]
    assert quiet == 0, f"{QUIET_VENDORS[0]} feed returned {quiet} rows, expected 0 (quiet state)"


@mark_requires_db
def test_drop_cadence_qualifies_matches_ratified_set(fleet_cadence):
    """Scope B — the CTK-204 gate-drift alarm. qualifies_for_histogram across the live
    fleet must equal {wwc, tsa, jf, pacific_east}. Drift = the gate is mis-specified
    OR the fleet changed; fix the gate, not the data (re-confirm the ratified set).

    NOT every failure here is a regression: a vendor legitimately crossing
    organic_drop_count >= 15 (a real ramp in honest drop cadence) is a deliberate
    RE-RATIFY moment — confirm the new member against CTK-204 intent, then edit
    EXPECTED_QUALIFIERS to include it. The test exists to force that conscious
    re-ratification, not to pin the set forever."""
    qualifiers = {slug for slug, r in fleet_cadence.items() if r and r["qualifies_for_histogram"]}
    assert qualifiers == EXPECTED_QUALIFIERS, (
        f"qualifies_for_histogram = {sorted(qualifiers)}, expected {sorted(EXPECTED_QUALIFIERS)} "
        f"(gate drift — fix the gate, not the data)"
    )


@mark_requires_db
def test_drop_cadence_quiet_states(fleet_cadence):
    """Scope B — quiet vendors report a clean organic-0 / NULL / not-qualifying state
    (feed-only / quiet), never an error or a spurious qualification."""
    for slug in QUIET_VENDORS:
        r = fleet_cadence.get(slug)
        assert r is not None, f"get_vendor_drop_cadence({slug!r}) returned no row"
        assert r["organic_drop_count"] == 0 and r["last_organic_drop_at"] is None and not r["qualifies_for_histogram"], (
            f"{slug} not a clean quiet state — organic={r['organic_drop_count']}, "
            f"last={r['last_organic_drop_at']}, qualifies={r['qualifies_for_histogram']}"
        )


@mark_requires_db
def test_drop_cadence_dow_buckets_sum(fleet_cadence):
    """Scope B — the 7 DOW buckets sum to organic_drop_count for every vendor (no drop
    lost or double-counted across the day-of-week histogram)."""
    for slug, r in fleet_cadence.items():
        if r is None:
            continue
        dow_sum = sum(r[k] for k in _DOW_COLS)
        assert dow_sum == r["organic_drop_count"], (
            f"{slug} DOW buckets sum {dow_sum} != organic_drop_count {r['organic_drop_count']}"
        )


def main() -> int:
    with db.get_test_conn() as conn:
        cadence = _fleet_cadence(conn)
        checks = [
            ("test_recent_drops_feed_ordered_and_inv_clean", lambda: test_recent_drops_feed_ordered_and_inv_clean(conn)),
            ("test_drop_cadence_qualifies_matches_ratified_set", lambda: test_drop_cadence_qualifies_matches_ratified_set(cadence)),
            ("test_drop_cadence_quiet_states", lambda: test_drop_cadence_quiet_states(cadence)),
            ("test_drop_cadence_dow_buckets_sum", lambda: test_drop_cadence_dow_buckets_sum(cadence)),
        ]
        failures = []
        for name, fn in checks:
            try:
                fn()
                print(f"  [PASS] {name}")
            except AssertionError as e:
                print(f"  [FAIL] {name}: {e}")
                failures.append(name)
            except Exception as e:  # noqa: BLE001
                print(f"  [ERROR] {name}: {type(e).__name__}: {e}")
                traceback.print_exc()
                failures.append(name)
        print()
        print(f"{len(checks) - len(failures)}/{len(checks)} passed")
        return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
