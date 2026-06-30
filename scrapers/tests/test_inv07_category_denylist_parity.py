"""scrapers/tests/test_inv07_category_denylist_parity.py — CTK-212 INV-07 (CTK-197)
consolidation bake-in (feedback_consolidation_bake_in_discoverability).

INV-07 excludes hidden categories from EVERY count / aggregate / feed surface. The
denylist is now {equipment, invert} (CTK-186 'equipment' + CTK-212 'invert' for
Biota's by-design inverts). This test pins, against the LIVE pg_proc bodies, that
every INV-07 content SQL function carries the SAME canonical denylist in the SAME
NULL-safe form — so the next time the set widens (a 3rd hidden category), a function
that's missed, or a set that drifts in one function, FAILS LOUDLY here instead of
silently leaking the category onto one surface.

WHY a live-DB test (requires_db): committed != applied
(feedback_migration_committed_not_applied). A function can be re-CREATE-OR-REPLACE'd by
a later migration that forgets the denylist; only the live body is authoritative. Skips
cleanly without NEON_DATABASE_URL (CI deselects -m "not requires_db").

MAINTENANCE — when a NEW INV-07 content function lands (any function that counts /
aggregates / feeds vendor_listings and must hide these categories), ADD it to
INV07_CONTENT_FUNCTIONS below. When the hidden set changes, update CANONICAL_DENYLIST
here, the TS leaf (lib/queries/category-exclusion.ts), and re-CREATE every function in
one migration — this test enforces all three stay in lockstep.

NOT covered by design: get_listing_lead_event (no category column — its consumers
filter category by JOIN-ing vendor_listings back: bare /new + the digest TS-side, the
IG pool Python-side). It is deliberately absent from INV07_CONTENT_FUNCTIONS.
"""

from __future__ import annotations

import re
import sys
import traceback
from pathlib import Path

from scrapers.common import db

try:
    import pytest
    mark_requires_db = pytest.mark.requires_db
except ImportError:  # script-mode fallback
    mark_requires_db = lambda f: f  # noqa: E731


# The canonical hidden-category denylist. MUST equal the TS source of truth
# (lib/queries/category-exclusion.ts EXCLUDED_CATEGORIES) — asserted below.
CANONICAL_DENYLIST = frozenset({"equipment", "invert"})

# Every INV-07 content function (counts / aggregates / feeds over vendor_listings).
# A new one MUST be added here (see MAINTENANCE above).
INV07_CONTENT_FUNCTIONS = (
    "f7_arrivals_dispositioned",
    "get_aggregate_activity",
    "get_velocity_listings",
    "get_cross_vendor_cheapest",
    "get_most_restocked",
    "get_vendor_drop_cadence",
)

# Matches the NULL-safe set form: ... <> ALL(ARRAY['a','b',...]::text[])
_DENYLIST_RE = re.compile(r"<>\s*ALL\(ARRAY\[([^\]]+)\]::text\[\]\)")
_NULL_SAFE_RE = re.compile(r"vl\.category IS NULL OR vl\.category <>\s*ALL\(ARRAY\[")
_OLD_LITERAL = "IS DISTINCT FROM 'equipment'"

_TS_LEAF = Path(__file__).resolve().parents[2] / "lib" / "queries" / "category-exclusion.ts"


def _parse_array_literal(group: str) -> set[str]:
    """'equipment','invert' -> {'equipment','invert'}."""
    return {m.group(1) for m in re.finditer(r"'([^']+)'", group)}


def _functiondef(conn, fn: str) -> str:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT pg_get_functiondef(p.oid) AS def FROM pg_proc p "
            "JOIN pg_namespace n ON n.oid = p.pronamespace "
            "WHERE n.nspname = 'public' AND p.proname = %s",
            (fn,),
        )
        rows = cur.fetchall()
    assert len(rows) == 1, f"{fn}: expected exactly 1 overload in public, got {len(rows)}"
    return rows[0]["def"]


@mark_requires_db
def test_inv07_functions_carry_canonical_denylist():
    """Every INV-07 content function's category denylist == CANONICAL_DENYLIST, in the
    NULL-safe form, with the old equipment-only literal gone. Fails loudly if a function
    omits a category, carries an extra one, drops NULL-safety, or reverts to the literal."""
    # CTK-219 D2: get_test_conn (TEST branch), not get_conn (prod). requires_db tests
    # target TEST_DATABASE_URL per CTK-215 — this was the lone test still opening a prod
    # connection. The "committed != applied" guarantee holds transitively: the branch is
    # re-cut from / migrated to current with prod (D3 nightly), so the live branch bodies
    # mirror prod's.
    with db.get_test_conn() as conn:
        for fn in INV07_CONTENT_FUNCTIONS:
            body = _functiondef(conn, fn)

            assert _OLD_LITERAL not in body, (
                f"{fn}: still carries the equipment-only `IS DISTINCT FROM 'equipment'` "
                f"literal — INV-07 denylist not widened to {sorted(CANONICAL_DENYLIST)}"
            )

            m = _DENYLIST_RE.search(body)
            assert m, (
                f"{fn}: no `<> ALL(ARRAY[...]::text[])` denylist found — INV-07 category "
                f"exclusion is missing entirely (silent category leak on this surface)"
            )
            denylist = _parse_array_literal(m.group(1))
            assert denylist == set(CANONICAL_DENYLIST), (
                f"{fn}: category denylist {sorted(denylist)} != canonical "
                f"{sorted(CANONICAL_DENYLIST)} — the INV-07 set drifted on this surface"
            )

            assert _NULL_SAFE_RE.search(body), (
                f"{fn}: denylist is not NULL-safe (missing the `vl.category IS NULL OR` "
                f"arm) — reclassified NULL-category corals would be dropped from this surface"
            )


@mark_requires_db
def test_inv07_canonical_matches_ts_leaf():
    """The Python CANONICAL_DENYLIST must equal the TS EXCLUDED_CATEGORIES leaf — the
    single source of truth across the SQL functions, the digest, bare /new, and /search.
    A widen in TS that forgets the SQL functions (or vice-versa) fails here."""
    text = _TS_LEAF.read_text(encoding="utf-8")
    m = re.search(r"EXCLUDED_CATEGORIES\s*=\s*\[([^\]]+)\]", text)
    assert m, f"could not find EXCLUDED_CATEGORIES array in {_TS_LEAF}"
    ts_set = _parse_array_literal(m.group(1))
    assert ts_set == set(CANONICAL_DENYLIST), (
        f"TS leaf EXCLUDED_CATEGORIES {sorted(ts_set)} != this test's CANONICAL_DENYLIST "
        f"{sorted(CANONICAL_DENYLIST)} — SQL and TS hidden-category sets have drifted; "
        f"update both + re-CREATE the six functions in one migration"
    )


def main() -> int:
    failed = 0
    for t in (test_inv07_functions_carry_canonical_denylist, test_inv07_canonical_matches_ts_leaf):
        try:
            t()
            print(f"PASS  {t.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL  {t.__name__}")
            traceback.print_exc()
    print(f"\n{2 - failed}/2 passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
