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
    is_surface_b_card_eligible,
    lineage_value,
    plain_price_value,
    select_f7_arrivals,
    select_f9_lineage,
    select_superlative_drop,
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


def test_superlative_pct_matches_rendered_pair():
    # The F8 headline % derives from the SAME baseline + current the rendered Price.
    # pair shows, so headline and on-card receipt can never disagree (%-parity gate).
    from scrapers.tools.content_queries import superlative_fields, superlative_pct
    from datetime import datetime, timezone
    ev = datetime(2026, 6, 16, 12, 0, 0, tzinfo=timezone.utc)

    def _pct_from_rendered_pair(row):
        pair = superlative_fields(row)[0]["value"]   # the rendered Price. drop pair
        old = float(pair["oldValue"].lstrip("$"))
        new = float(pair["newValue"].lstrip("$"))
        return round((old - new) / old * 100)

    # CT-observed arm: $650 -> $455 = exactly 30%.
    r = _drop_row(prior_price=Decimal("650"), current_price=Decimal("455"),
                  named_coral_origin_vendor="WWC", event_at=ev)
    assert superlative_pct(r) == 30
    assert superlative_pct(r) == _pct_from_rendered_pair(r)
    # Markdown arm: baseline falls back to compare_at_price ($250 -> $174.99 ~= 30%);
    # % still computes off the rendered pair, not a separate value.
    r2 = _drop_row(prior_price=None, compare_at_price=Decimal("250"),
                   current_price=Decimal("174.99"), named_coral_origin_vendor="WWC", event_at=ev)
    assert superlative_pct(r2) == _pct_from_rendered_pair(r2)
    # >2-decimal price straddling a half-percent boundary: the RAW ratio is
    # (100-50.504)/100 = 49.496% -> 49, but the rendered pair shows $100.00 -> $50.50
    # = 49.5% -> 50. superlative_pct must follow the DISPLAYED pair (50), not the raw
    # input — the parity guarantee holds for non-2dp inputs, not just clean ones.
    r3 = _drop_row(prior_price=Decimal("100"), current_price=Decimal("50.504"),
                   named_coral_origin_vendor="WWC", event_at=ev)
    assert superlative_pct(r3) == 50
    assert superlative_pct(r3) == _pct_from_rendered_pair(r3)


def test_price_value_helpers():
    assert plain_price_value(Decimal("250")) == "$250.00"
    assert drop_price_value(Decimal("650"), Decimal("455")) == {
        "kind": "price-drop-new", "oldValue": "$650.00", "newValue": "$455.00",
    }


# ---------------------------------------------------------------------------
# Surface-B card eligibility (no image gate) + the F7/F8/F9 selectors.
# The selectors take a conn; _FakeConn returns canned dict rows so the SELECTION
# logic is exercised purely (no DB) — the SQL itself is the DB parity test's job.
# ---------------------------------------------------------------------------


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self._sql = sql

    def fetchall(self):
        return self._rows


class _FakeConn:
    def __init__(self, rows):
        self._rows = rows

    def cursor(self):
        return _FakeCursor(self._rows)


def _le_row(event, *, coral_id=1, coral="WWC Sunkist Bounce", vendor="WWC",
            price=Decimal("250"), at="2026-06-16T12:00:00Z"):
    """A get_listing_lead_event-shaped row (only the fields the F7 selector uses)."""
    return {
        "event": event,
        "named_coral_id": coral_id,
        "named_coral_canonical_name": coral,
        "vendor_display_name": vendor,
        "current_price": price,
        "event_at": at,
    }


def _carrier(*, coral_id=1, coral="WWC Sunkist Bounce", vendor_id=10, vendor="WWC",
             price=Decimal("250"), at="2026-06-16T12:00:00Z"):
    """A get_cross_vendor_carriers-shaped row (only the fields the F9 selector uses)."""
    return {
        "named_coral_id": coral_id,
        "named_coral_canonical_name": coral,
        "vendor_id": vendor_id,
        "vendor_display_name": vendor,
        "current_price": price,
        "event_at": at,
    }


def test_surface_b_card_eligible_no_image_gate():
    # matched + priced clears the floor REGARDLESS of image (surface-B is photo-less).
    assert is_surface_b_card_eligible(_drop_row()) is True
    assert is_surface_b_card_eligible(_drop_row(image_url=None)) is True
    assert is_surface_b_card_eligible(_drop_row(image_url="https://vendor.example/x.jpg")) is True
    # matched-only + priced still bind.
    assert is_surface_b_card_eligible(_drop_row(named_coral_id=None)) is False
    assert is_surface_b_card_eligible(_drop_row(current_price=None)) is False


def test_f8_swap_admits_imageless_keeps_glitch_and_worthiness_gates():
    # Image-less but matched + priced + 30% drop + $455 post-drop: now F8-eligible
    # (was rejected 'no-image' under the old image-bearing predicate).
    winner = _drop_row(image_url=None)
    assert select_superlative_drop(_FakeConn([winner])) is winner
    # Glitch (98% off) still rejected even image-less -> no post.
    glitch = _drop_row(image_url=None, prior_price=Decimal("650"), current_price=Decimal("9.99"))
    assert select_superlative_drop(_FakeConn([glitch])) is None
    # Unworthy (sub-$100 post-drop coral) still rejected even image-less -> no post.
    cheap = _drop_row(image_url=None, prior_price=Decimal("120"), current_price=Decimal("90"))
    assert select_superlative_drop(_FakeConn([cheap])) is None


def test_f7_composition_tracks_population_not_sample():
    # Full population: both arms present -> composition is mixed. But the only
    # card-eligible rows are arrivals (the restock is unmatched), so the SAMPLE is
    # single-arm. The cover variant must follow the POPULATION (mixed), not the
    # sample (all-arrivals) — the honest-count guard.
    rows = [
        _le_row("just-listed", coral_id=1, vendor="WWC"),
        _le_row("just-listed", coral_id=2, coral="TSA Bounce", vendor="TSA"),
        _le_row("back-in-stock", coral_id=None),   # unmatched -> not card-eligible
    ]
    true_count, composition, items = select_f7_arrivals(_FakeConn(rows))
    assert composition == "mixed"                  # population has both arms
    assert true_count == 3                          # full population, not the sample
    assert len(items) == 2                          # only the matched arrivals sampled
    assert true_count != len(items)                 # cover count never the sample size
    assert all(it["event_phrase"] == "listed" for it in items)
    # Every inner field list routes through build_card_fields (INV-01): Price. — Listed.
    assert [f["label"] for f in items[0]["fields"]] == ["Price", "Listed"]


def test_f7_composition_single_arm_variants():
    arr = [_le_row("just-listed"), _le_row("just-listed", coral_id=2)]
    assert select_f7_arrivals(_FakeConn(arr))[1] == "all-arrivals"
    res = [_le_row("back-in-stock"), _le_row("back-in-stock", coral_id=2)]
    assert select_f7_arrivals(_FakeConn(res))[1] == "all-restocks"


def test_f7_sample_capped():
    rows = [_le_row("just-listed", coral_id=i) for i in range(20)]
    true_count, composition, items = select_f7_arrivals(_FakeConn(rows), sample_cap=9)
    assert true_count == 20 and len(items) == 9    # honest count, deflated sample


def test_f9_single_vendor_returns_none():
    # A coral carried by only 1 distinct vendor is not a lineage spotlight.
    rows = [_carrier(coral_id=1, vendor_id=10), _carrier(coral_id=1, vendor_id=10)]
    assert select_f9_lineage(_FakeConn(rows)) is None
    # No carriers at all -> None.
    assert select_f9_lineage(_FakeConn([])) is None


def test_f9_honest_count_with_deflated_sample():
    # Coral 1 carried at 3 distinct vendors, but one carrier is price-on-request
    # (not card-eligible). vendor_count is the TRUE 3; the inner sample is the 2
    # priced carriers. The cover count (3) never collapses to the sample (2).
    rows = [
        _carrier(coral_id=1, vendor_id=10, vendor="WWC", price=Decimal("250"), at="2026-06-16T12:00:00Z"),
        _carrier(coral_id=1, vendor_id=11, vendor="TSA", price=Decimal("230"), at="2026-06-15T12:00:00Z"),
        _carrier(coral_id=1, vendor_id=12, vendor="ASD", price=None, at="2026-06-14T12:00:00Z"),
    ]
    result = select_f9_lineage(_FakeConn(rows))
    assert result is not None
    coral, vendor_count, items = result
    assert coral == "WWC Sunkist Bounce"
    assert vendor_count == 3            # TRUE distinct carriers (price-blind)
    assert len(items) == 2             # only the priced carriers render as inners
    assert vendor_count > len(items)   # deflated sample, honest cover count
    # Recency-ordered (event_at DESC): WWC (06-16) before TSA (06-15).
    assert [it["vendor"] for it in items] == ["WWC", "TSA"]
    assert [f["label"] for f in items[0]["fields"]] == ["Price", "Listed"]


def test_f9_picks_widest_spread_and_dedupes_per_vendor():
    rows = [
        # coral 1: 2 distinct vendors (one with a duplicate listing -> one inner).
        _carrier(coral_id=1, coral="Coral One", vendor_id=10, at="2026-06-16T10:00:00Z"),
        _carrier(coral_id=1, coral="Coral One", vendor_id=10, at="2026-06-16T09:00:00Z"),
        _carrier(coral_id=1, coral="Coral One", vendor_id=11, at="2026-06-16T08:00:00Z"),
        # coral 2: 3 distinct vendors -> widest spread, wins the pick.
        _carrier(coral_id=2, coral="Coral Two", vendor_id=20, at="2026-06-16T07:00:00Z"),
        _carrier(coral_id=2, coral="Coral Two", vendor_id=21, at="2026-06-16T06:00:00Z"),
        _carrier(coral_id=2, coral="Coral Two", vendor_id=22, at="2026-06-16T05:00:00Z"),
    ]
    coral, vendor_count, items = select_f9_lineage(_FakeConn(rows))
    assert coral == "Coral Two" and vendor_count == 3 and len(items) == 3
    # And the dedupe holds for the runner-up shape: re-run with only coral 1.
    coral1, vc1, items1 = select_f9_lineage(_FakeConn(rows[:3]))
    assert coral1 == "Coral One" and vc1 == 2 and len(items1) == 2   # 3 rows, 2 vendors


def test_f9_falls_to_renderable_runner_up_not_none():
    # The widest-spread coral is all price-on-request (no renderable inner); a
    # narrower >= 2-vendor coral IS renderable. The selector must return the
    # narrower one, NOT None (runner-up-starvation fix).
    rows = [
        _carrier(coral_id=1, coral="Wide Coral", vendor_id=10, price=None, at="2026-06-16T12:00:00Z"),
        _carrier(coral_id=1, coral="Wide Coral", vendor_id=11, price=None, at="2026-06-16T11:00:00Z"),
        _carrier(coral_id=1, coral="Wide Coral", vendor_id=12, price=None, at="2026-06-16T10:00:00Z"),
        _carrier(coral_id=2, coral="Narrow Coral", vendor_id=20, price=Decimal("250"), at="2026-06-15T12:00:00Z"),
        _carrier(coral_id=2, coral="Narrow Coral", vendor_id=21, price=Decimal("230"), at="2026-06-15T11:00:00Z"),
    ]
    coral, vendor_count, items = select_f9_lineage(_FakeConn(rows))
    assert coral == "Narrow Coral"     # not the starved wider coral, not None
    assert vendor_count == 2 and len(items) == 2
    # When NO >= 2-vendor coral has a priced inner -> None.
    assert select_f9_lineage(_FakeConn(rows[:3])) is None


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
