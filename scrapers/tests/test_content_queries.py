"""scrapers/tests/test_content_queries.py — CTK-161 unit coverage for the shared
content-data query layer (scrapers/tools/content_queries.py) + the D-2 publish
gate (scrapers/tools/ig_spotlight.py auto_publishable).

Pure — no DB, no network, no env. The cross-vendor ranking ITSELF is now the SQL
function get_cross_vendor_cheapest (migration 0038); the pure cross_vendor_cheapest_ids
is the executable REFERENCE SPEC of the crowning contract, pinned here by a golden
fixture. test_cross_vendor_ranking_parity (DB-gated) cross-checks the SQL function
against this same pure ranker over a live-seeded copy of these scenarios.

Runnable as:
  python -m scrapers.tests.test_content_queries

Coverage:
  test_eligible_predicate            is_cross_vendor_eligible: triple + named
  test_ranking_golden                cross_vendor_cheapest_ids over the fixture == expected
  test_ranking_tie_keeps_both        genuine tie -> both ids crowned
  test_ranking_auction_excluded      cheaper auction never crowns; non-auction wins
  test_ranking_oos_excluded          cheaper OOS row never crowns
  test_ranking_null_price_excluded   price-on-request row never crowns
  test_ranking_single_vendor_none    only 1 vendor carries it -> nothing crowned
  test_descriptor_comparative_flags  D-2 tags: non-comparative vs comparative
  test_velocity_absent               velocity out of scope -> not in the registry
  test_auto_publishable_gate         comparative excluded from the auto-publish path
  test_cross_vendor_line_contract    provisional DataRowField[] listing-line shape
"""

from __future__ import annotations

from decimal import Decimal

from scrapers.tools.content_queries import (
    CONTENT_FORMATS,
    cross_vendor_cheapest_ids,
    cross_vendor_cheapest_line,
    is_cross_vendor_eligible,
)
from scrapers.tools.ig_spotlight import auto_publishable, auto_publishable_formats


def _row(id, vendor_id, coral_id, price, *, in_stock=True, auction=None):
    return {
        "id": id,
        "vendor_id": vendor_id,
        "named_coral_id": coral_id,
        "current_price": None if price is None else Decimal(str(price)),
        "in_stock": in_stock,
        "auction_end_time": auction,
        "vendor_display_name": f"Vendor {vendor_id}",
    }


# Reference-spec fixture (mirrored by the DB parity test's seed scenarios):
#   coral 1  single-cheapest across 3 vendors  -> crown the $10 id (1)
#   coral 2  price tie across 2 vendors         -> crown both (4, 5)
#   coral 3  single vendor only                 -> nothing (need >= 2 vendors)
#   coral 4  cheaper AUCTION excluded           -> crown the cheapest non-auction (8)
#   coral 5  cheaper OOS excluded               -> crown the cheapest in-stock (11)
#   coral 6  null-price (price-on-request) excl -> crown the cheapest priced (14)
#   id 16    unnamed listing                    -> excluded (no coral group)
_AUCTION = "2099-01-01T00:00:00Z"
RANKING_FIXTURE = [
    _row(1, 1, 1, 10), _row(2, 2, 1, 12), _row(3, 3, 1, 15),
    _row(4, 1, 2, 20), _row(5, 2, 2, 20),
    _row(6, 1, 3, 5),
    _row(7, 1, 4, 8, auction=_AUCTION), _row(8, 2, 4, 30), _row(9, 3, 4, 40),
    _row(10, 1, 5, 5, in_stock=False), _row(11, 2, 5, 25), _row(12, 3, 5, 35),
    _row(13, 1, 6, None), _row(14, 2, 6, 50), _row(15, 3, 6, 55),
    _row(16, 1, None, 1),
]
RANKING_EXPECTED = {1, 4, 5, 8, 11, 14}


def test_eligible_predicate():
    assert is_cross_vendor_eligible(_row(1, 1, 1, 10)) is True
    assert is_cross_vendor_eligible(_row(1, 1, None, 10)) is False   # unnamed
    assert is_cross_vendor_eligible(_row(1, 1, 1, 10, in_stock=False)) is False  # OOS
    assert is_cross_vendor_eligible(_row(1, 1, 1, 10, auction=_AUCTION)) is False  # auction
    assert is_cross_vendor_eligible(_row(1, 1, 1, None)) is False    # price-on-request


def test_ranking_golden():
    assert cross_vendor_cheapest_ids(RANKING_FIXTURE) == RANKING_EXPECTED


def test_ranking_tie_keeps_both():
    rows = [_row(4, 1, 2, 20), _row(5, 2, 2, 20)]
    assert cross_vendor_cheapest_ids(rows) == {4, 5}


def test_ranking_auction_excluded():
    rows = [_row(7, 1, 4, 8, auction=_AUCTION), _row(8, 2, 4, 30), _row(9, 3, 4, 40)]
    assert cross_vendor_cheapest_ids(rows) == {8}  # the $8 auction never crowns


def test_ranking_oos_excluded():
    rows = [_row(10, 1, 5, 5, in_stock=False), _row(11, 2, 5, 25), _row(12, 3, 5, 35)]
    assert cross_vendor_cheapest_ids(rows) == {11}


def test_ranking_null_price_excluded():
    rows = [_row(13, 1, 6, None), _row(14, 2, 6, 50), _row(15, 3, 6, 55)]
    assert cross_vendor_cheapest_ids(rows) == {14}


def test_ranking_single_vendor_none():
    # After excluding the auction, coral 4 has only vendor 2 + 3 -> 2 vendors, ok;
    # but a TRUE single-vendor coral crowns nothing.
    rows = [_row(6, 1, 3, 5)]
    assert cross_vendor_cheapest_ids(rows) == set()


def test_descriptor_comparative_flags():
    assert CONTENT_FORMATS["aggregate-activity"].comparative is False
    assert CONTENT_FORMATS["most-restocked"].comparative is False
    assert CONTENT_FORMATS["single-listing-drop"].comparative is False
    assert CONTENT_FORMATS["cheapest-across-vendors"].comparative is True
    assert CONTENT_FORMATS["market-report"].comparative is True


def test_velocity_absent():
    # Velocity (time-to-OOS) is OUT of scope this layer (pending ratification).
    assert "velocity" not in CONTENT_FORMATS


def test_auto_publishable_gate():
    assert auto_publishable(CONTENT_FORMATS["aggregate-activity"]) is True
    assert auto_publishable(CONTENT_FORMATS["cheapest-across-vendors"]) is False
    assert auto_publishable(CONTENT_FORMATS["market-report"]) is False
    keys = {d.key for d in auto_publishable_formats()}
    assert keys == {"aggregate-activity", "most-restocked", "single-listing-drop"}
    assert "cheapest-across-vendors" not in keys
    assert "market-report" not in keys


def test_cross_vendor_line_contract():
    row = {"current_price": Decimal("10"), "vendor_display_name": "World Wide Corals"}
    assert cross_vendor_cheapest_line(row) == [
        {"label": "Price", "value": "$10.00"},
        {"label": "Vendor", "value": "World Wide Corals"},
    ]


def _run_all():
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failures = 0
    for fn in fns:
        try:
            fn()
            print(f"ok   {fn.__name__}")
        except AssertionError as e:
            failures += 1
            print(f"FAIL {fn.__name__}: {e}")
    print(f"\n{len(fns) - failures}/{len(fns)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    import sys
    sys.exit(_run_all())
