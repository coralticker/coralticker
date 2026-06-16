"""scrapers/tests/test_content_queries.py — CTK-161 unit coverage for the shared
content-data query layer (scrapers/tools/content_queries.py) + the D-2 publish
gate (scrapers/tools/ig_spotlight.py auto_publishable).

Pure — no DB, no network, no env. The cross-vendor ranking ITSELF is now the SQL
function get_cross_vendor_cheapest (migration 0041); the pure cross_vendor_cheapest_ids
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
  test_velocity_present              velocity registered, non-comparative (publish-now)
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


def test_velocity_present():
    # Velocity (listed-and-gone) cleared publish-now-safe 2026-06-16: registered,
    # non-comparative (single listing, no cross-vendor price comparison).
    assert "velocity" in CONTENT_FORMATS
    assert CONTENT_FORMATS["velocity"].comparative is False


def test_auto_publishable_gate():
    assert auto_publishable(CONTENT_FORMATS["aggregate-activity"]) is True
    assert auto_publishable(CONTENT_FORMATS["velocity"]) is True
    assert auto_publishable(CONTENT_FORMATS["cheapest-across-vendors"]) is False
    assert auto_publishable(CONTENT_FORMATS["market-report"]) is False
    keys = {d.key for d in auto_publishable_formats()}
    assert keys == {"aggregate-activity", "most-restocked", "single-listing-drop", "velocity"}
    assert "cheapest-across-vendors" not in keys
    assert "market-report" not in keys


def test_cross_vendor_line_contract():
    row = {"current_price": Decimal("10"), "vendor_display_name": "World Wide Corals"}
    assert cross_vendor_cheapest_line(row) == [
        {"label": "Price", "value": "$10.00"},
        {"label": "Vendor", "value": "World Wide Corals"},
    ]


# --- CTK-164 content-card selection filters --------------------------------

from scrapers.tools.content_queries import (  # noqa: E402
    MIRROR_HOST,
    build_card_fields,
    drop_price_value,
    is_single_card_eligible,
    lineage_value,
    plain_price_value,
    single_card_reject,
    superlative_drop_sane,
    superlative_post_worthy,
)


def _drop_row(**kw):
    base = {
        "named_coral_id": 1,
        "image_url": MIRROR_HOST + "/wwc/x.webp",
        "current_price": Decimal("455"),
        "prior_price": Decimal("650"),
        "compare_at_price": None,
    }
    base.update(kw)
    return base


def test_single_card_eligible_floor():
    assert is_single_card_eligible(_drop_row()) is True
    assert single_card_reject(_drop_row(named_coral_id=None)) == "unmatched"   # matched-only
    assert single_card_reject(_drop_row(image_url=None)) == "no-image"
    assert single_card_reject(_drop_row(image_url="https://vendor.example/x.jpg")) == "non-mirror-image"
    assert single_card_reject(_drop_row(current_price=None)) == "price-on-request"


def test_superlative_glitch_rejection():
    assert superlative_drop_sane(_drop_row()) is True                          # 30% sane
    assert superlative_drop_sane(_drop_row(prior_price=Decimal("650"), current_price=Decimal("9.99"))) is False  # 98% glitch
    assert superlative_drop_sane(_drop_row(prior_price=Decimal("10"), current_price=Decimal("3"))) is False      # sub-$5 floor
    assert superlative_drop_sane(_drop_row(prior_price=Decimal("455"), current_price=Decimal("455"))) is False   # 0% drop


def test_superlative_post_worthy_gate():
    # 30% off, post-drop $455 -> worthy.
    assert superlative_post_worthy(_drop_row()) is True
    # Big % but cheap coral ($120 -> $90 = 25%, but $90 < $100 floor) -> not worthy.
    assert superlative_post_worthy(_drop_row(prior_price=Decimal("120"), current_price=Decimal("90"))) is False
    # Substantial coral but small drop ($600 -> $560 = ~6.7% < 25%) -> not worthy.
    assert superlative_post_worthy(_drop_row(prior_price=Decimal("600"), current_price=Decimal("560"))) is False


def test_lineage_value_degrade():
    assert lineage_value("WWC", 2018) == "WWC · 2018"
    assert lineage_value("WWC", None) == "WWC"          # year missing -> origin only
    assert lineage_value(None, 2018) == "2018"          # origin missing -> year only
    assert lineage_value(None, None) is None            # both absent -> caller omits field
    assert lineage_value("", None) is None              # empty origin treated as absent


def test_build_card_fields_two_field_v1():
    # v1 D-4: exactly Price. — Listed. (Lineage dropped), regardless of origin/year.
    f = build_card_fields(price_value="$250.00", origin="WWC", year=2018, listed_at="2026-06-16T12:00:00Z")
    assert [x["label"] for x in f] == ["Price", "Listed"]
    # origin/year are accepted (latent three-field path) but produce no Lineage in v1.
    f2 = build_card_fields(price_value="$250.00", origin=None, year=None, listed_at="2026-06-16T12:00:00Z")
    assert [x["label"] for x in f2] == ["Price", "Listed"]
    # Listed omitted only when listed_at is None.
    f3 = build_card_fields(price_value="$250.00", listed_at=None)
    assert [x["label"] for x in f3] == ["Price"]


def test_superlative_fields_drop_baseline():
    from scrapers.tools.content_queries import superlative_fields
    from datetime import datetime, timezone
    ev = datetime(2026, 6, 16, 12, 0, 0, tzinfo=timezone.utc)
    # CT-observed arm: prior_price is the struck old value.
    f = superlative_fields(_drop_row(prior_price=Decimal("650"), current_price=Decimal("455"),
                                     named_coral_origin_vendor="WWC", event_at=ev))
    assert [x["label"] for x in f] == ["Price", "Listed"]   # v1 two-field (no Lineage)
    assert f[0]["value"] == {"kind": "price-drop-new", "oldValue": "$650.00", "newValue": "$455.00"}
    # Markdown arm: prior_price NULL -> struck old falls back to compare_at_price,
    # never a null 'price on request'.
    f2 = superlative_fields(_drop_row(prior_price=None, compare_at_price=Decimal("250"),
                                      current_price=Decimal("174.99"),
                                      named_coral_origin_vendor="WWC", event_at=ev))
    assert f2[0]["value"]["oldValue"] == "$250.00"
    assert f2[0]["value"]["newValue"] == "$174.99"


def test_price_value_helpers():
    assert plain_price_value(Decimal("250")) == "$250.00"
    assert drop_price_value(Decimal("650"), Decimal("455")) == {
        "kind": "price-drop-new", "oldValue": "$650.00", "newValue": "$455.00",
    }


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
