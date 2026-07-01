"""scrapers/tests/test_cherry_parse.py — CTK-143 parse-layer tests for Cherry
Corals' Shopify /products.json shape against locked fixture
scrapers/tests/fixtures/cherry/products.sample.json.

Cherry is an AUCTION HOUSE with a Coral Stop-shape catalog: product_type is
blank store-wide (1270/1272 ''), taxonomy lives in tags, and ~75% of the catalog
(958 rows) is auction inventory. The template is test_coralstop_parse.py
(no-allowlist / title_denylist-only) with Cornbred's auction handling layered on.

CTK-143 is the FIRST auction vendor to adopt the CTK-208 harness. The harness
grew (additively) a `make_keep_with_auction` wrapper — modeling the production
`_should_keep_with_auction_override` path fetch_and_parse uses when
auction_detection is set — plus an auction_detection mirror-parity branch. The
plain make_keep asserts auction_detection is None precisely so an auction vendor
lands on the auction wrapper instead of silently diverging from production.

Parse-only — no DB, no network. Validates:
  - html_hash sentinel (13-key fleet shape).
  - The NO-ALLOWLIST title_denylist-only gate (a tag_allowlist would drop all 958
    auction corals — the Coral Stop DOOR-BUSTER lesson at 20x scale).
  - The INV-05 writer contract (decisions #84 + #70): auction rows detected off
    the FIVE-tag family, current_price nulled + is_auction=true through the real
    _normalize_product call (deleting the null branch FAILS the test — the
    guarantee is exercised, not co-incidentally satisfied).
  - The browse-eligible coverage floor (non-auction NULL 3.22% <= 10%); the
    full-catalog 43.74% NULL is sanctioned absence-of-signal (auction morphs).

THE LOAD-BEARING REGRESSION (why auction_detection.tags is the full five-tag
family, not just `auctions`): the walk found one auction row —
"OG Colorado Sunburst Anemone #2" — tagged ['auction2', 'Fresh Cherries'] with
NO `auctions` tag. Detecting on `auctions` alone would MISS it and write its $250
live bid through as a buy-price (INV-05 obligation #1 breach, the 1B trust
hazard). test_auction_orphan_round_tag_detected pins that the round tags close
this gap.

Runnable as:
  python -m scrapers.tests.test_cherry_parse

Fixture regen path: re-fetch cherrycorals.com/products.json?limit=250 across all
pages (Session-1 walk shape: 1,272 rows / 6 pages — the FULL catalog, not a
page-1 sample, per feedback_absence_diag_full_catalog_sweep) and re-dump the
{"products": [...]} payload. Re-pinning moves EXPECTED_TOTAL/KEPT + the drop set
+ the coverage NULL set as the live catalog drifts (auction inventory churns per
round) — update the constants to match the snapshot.
"""

from __future__ import annotations

import sys
from pathlib import Path

from scrapers.common.normalize import infer_category
from scrapers.common.parse_shopify import _is_auction
from scrapers.tests.vendor_parse_harness import (
    VendorParseConfig,
    by_title as _by_title,
    check_html_hash_first_product_keys,
    check_yaml_mirror_parity,
    make_keep_with_auction,
    make_normalize,
    run_main,
)


# Hand-mirror of scrapers/vendors/cherry.yaml category_filter — kept byte-exact
# with the YAML; yaml_mirror_parity asserts the equality so a YAML amendment that
# isn't mirrored here fails loudly (CTK-115 drift class). NOTE the deliberate
# ABSENCE of product_type_allowlist AND tag_allowlist — Cherry is a no-allowlist
# vendor (CTK-143 Q1 ruling). Only the 3-row non-coral tail + the fleet chaeto
# forward-bind are denied, all by title.
CHERRY_CATEGORY_FILTER = {
    "title_denylist": [
        "Shipping", "Gift Card", "Chaeto", "Cheato", "Macroalgae", "Macro Algae",
    ],
}

# Cherry's five-tag auction family (CTK-143). auctions = class tag; auction1-4 =
# per-round markers that catch the one orphan row carrying a round tag without
# `auctions` (see THE LOAD-BEARING REGRESSION in the module docstring).
CHERRY_AUCTION_DETECTION = {
    "tags": ["auctions", "auction1", "auction2", "auction3", "auction4"],
}

CONFIG = VendorParseConfig(
    fixture_path=Path(__file__).parent / "fixtures" / "cherry" / "products.sample.json",
    yaml_path=Path(__file__).parent.parent / "vendors" / "cherry.yaml",
    base_url="https://cherrycorals.com",
    image_strategy="mirror",
    originator_prefix=None,                       # CTK-143 — null (no Cherry-attributed seed-list canonicals)
    auction_detection=CHERRY_AUCTION_DETECTION,   # CTK-143 — INV-05 triggered; five-tag family
    category_filter=CHERRY_CATEGORY_FILTER,
    in_stock_only=False,
    expected_first_product_keys=[
        "body_html", "created_at", "handle", "id", "images", "options",
        "product_type", "published_at", "tags", "title", "updated_at",
        "variants", "vendor",
    ],
    html_hash_sentinel="c94c512f27be051326728462bfaf34b4b4cb3f2595a3eafbe44ba45a672aad70",
    expected_filter_keys=frozenset({"title_denylist"}),
    expected_absent_axes=frozenset({"product_type_allowlist", "tag_allowlist"}),
    expect_in_stock_only_absent=True,
    expect_auction_detection_none=False,          # auction vendor — the parity branch asserts the block matches
)

# Auction vendor: model the production _should_keep_with_auction_override path.
_keep = make_keep_with_auction(CONFIG)
_normalize = make_normalize(CONFIG)


# Expected keep/drop on the LOCKED 2026-07-01 fixture (1,272 rows). Exactly 3
# rows drop (the non-coral tail); every coral — incl. all 958 auction corals —
# survives. Any allowlist regression that drops auction coral, or a denylist that
# false-fires on a coral morph name, moves these counts.
EXPECTED_TOTAL = 1272
EXPECTED_KEPT = 1269
EXPECTED_DROPPED = EXPECTED_TOTAL - EXPECTED_KEPT  # 3; derived so a re-pin can't desync it

# The exact 3-row non-coral tail (the only drops on the locked fixture): 2
# Auction-Shipping service SKUs + 1 Gift Card. The 2 dev test SKUs ('test' /
# 'TEST') are NOT dropped — bare "test" collides with "Greatest Show" zoanthids
# (project_anchor_denylist tokens), so they ride as sanctioned NULL noise.
DROPPED_TITLES = {
    "Cherry Corals Auction Shipping - FAR States Only - Your corals arrive the NEXT day!",
    "Cherry Corals Auction Shipping - NEAR States Only - Your corals arrive the NEXT day!",
    "Cherry Corals Gift Card",
}

# Coverage decision (CTK-143 Q1 ruling): the gate is measured over the
# BROWSE-ELIGIBLE (non-auction) set — auctions are CTK-042-gated off every browse
# surface, so their NULL category can't vanish a coral. Non-auction kept = 311,
# NULL = 10 = 3.22% < 10% threshold. The full-catalog 43.74% NULL is sanctioned
# (545 genus-less auction morphs = absence-of-signal, not a missing-genera miss).
COVERAGE_NULL_THRESHOLD_PCT = 10.0
EXPECTED_NON_AUCTION_KEPT = 311
EXPECTED_NON_AUCTION_NULL = 10
EXPECTED_NON_AUCTION_NULL_TITLES = {
    "Brian's CC Disney Jr", "Chris's SC OP", "Grace's JF Solar Flare Add On",
    "Jeff's Coral Pack", "Mike And Terra's Frag pack", "Red Hornet for Todd",
    "TEST", "WWC King Fiji #2", "Xander's Pack", "test",
}
EXPECTED_AUCTION_KEPT = 958

# Anchor rows on the locked fixture.
CORAL_ANCHOR = "Baby Tequila"                              # Fresh Cherries + Mushrooms and Ricordea -> mushroom
LIVE_AUCTION = "CC Mystery Coral #4"                       # auction4+auctions, avail True, $88.88 live bid, cat None
OOS_AUCTION = "OG Colorado Sunburst Anemone #4"            # auction4+auctions, avail False, $283, cat anemone
ORPHAN_AUCTION = "OG Colorado Sunburst Anemone #2"         # auction2 + Fresh Cherries, NO 'auctions', $250


try:
    import pytest

    @pytest.fixture(scope="module")
    def products():
        from scrapers.tests.vendor_parse_harness import load_fixture
        return load_fixture(CONFIG)
except ImportError:
    pass


def _is_auc(p: dict) -> bool:
    return _is_auction(p, CHERRY_AUCTION_DETECTION)


# Test 1 (COMMON, harness): html_hash sentinel — sorted-keys-of-first-product SHA256
def test_html_hash_first_product_keys(products):
    check_html_hash_first_product_keys(products, CONFIG)


# Test 2: total kept = 1269 (1272 - the 3-row non-coral tail)
def test_total_kept_is_1269(products):
    """Full-catalog keep count on the locked 1,272-row fixture: 1269 kept, 3
    dropped. With no allowlist and a title_denylist hitting only the non-coral
    tail, the entire coral catalog — all 958 auction corals — survives. Uses the
    production auction-override keep path (make_keep_with_auction)."""
    assert len(products) == EXPECTED_TOTAL, f"fixture drifted: expected {EXPECTED_TOTAL} rows, got {len(products)}"
    kept = sum(1 for p in products if _keep(p))
    assert kept == EXPECTED_KEPT, f"expected {EXPECTED_KEPT} kept, got {kept}"


# Test 3: the exact non-coral tail drops, nothing else
def test_exact_drop_set(products):
    """The 3 dropped titles are exactly the non-coral tail (2 Auction-Shipping +
    1 Gift Card) — no coral collateral. Pins the drop set so a denylist
    coarsening (or a coral morph that starts matching a denylist term) surfaces
    loudly."""
    dropped = {p["title"] for p in products if not _keep(p)}
    assert dropped == DROPPED_TITLES, (
        f"drop set drifted.\n  unexpected drops: {dropped - DROPPED_TITLES}\n"
        f"  missing drops: {DROPPED_TITLES - dropped}"
    )


# Test 4 (THE CHERRY REGRESSION): no-category-tag auction corals survive
def test_no_category_tag_auction_corals_survive(products):
    """The load-bearing Cherry regression: all 958 auction corals carry NO
    coral-category tag (only auctions/auctionN). A product_type_allowlist OR
    tag_allowlist would silently drop the entire auction inventory — 75% of the
    catalog. Every auction row MUST survive the gate (via the auction override)."""
    auction_rows = [p for p in products if _is_auc(p)]
    assert len(auction_rows) == EXPECTED_AUCTION_KEPT, (
        f"fixture drift: expected {EXPECTED_AUCTION_KEPT} auction rows, got {len(auction_rows)}"
    )
    dropped = [p["title"] for p in auction_rows if not _keep(p)]
    assert dropped == [], f"auction corals were wrongly dropped (an allowlist was added?): {dropped[:10]}"
    # Isolate the axis: a no-tag-except-auction, blank-product_type auction coral survives.
    assert _keep({"title": "Frozen Armageddon", "product_type": "", "tags": ["auction4", "auctions"]}) is True


# Test 5: no-allowlist — a feed-relabeled product_type + a bare non-auction coral survive
def test_no_allowlist_feed_relabel_survives(products):
    """Under the no-allowlist decision, a never-before-seen product_type (a feed
    relabel to a Google category) MUST survive — exactly what a
    product_type_allowlist would silently drop. If this fails, someone added an
    allowlist (the CTK-143 Q1 regression)."""
    relabeled = {
        "title": "Rainbow Splice Acro",
        "product_type": "Animals & Pet Supplies > Pet Supplies > Fish Supplies",
        "tags": ["Fresh Cherries", "Acropora Frags"],
    }
    assert _keep(relabeled) is True, (
        "a feed-relabeled coral was dropped — a product_type_allowlist must have been added"
    )


# Test 6: auction detection fires on the class tag
def test_auction_detected_on_auctions_tag(products):
    """The live-auction anchor carries ['auction4', 'auctions']; _is_auction
    fires on the class tag."""
    p = _by_title(products, LIVE_AUCTION)
    assert "auctions" in p["tags"]
    assert _is_auction(p, CHERRY_AUCTION_DETECTION) is True


# Test 7 (THE LOAD-BEARING TAG-SET REGRESSION): orphan round-tag row detected
def test_auction_orphan_round_tag_detected(products):
    """"OG Colorado Sunburst Anemone #2" carries ['auction2', 'Fresh Cherries']
    and NO `auctions` tag. Detecting on `auctions` alone would MISS it and write
    its $250 live bid through as a buy-price (INV-05 obligation #1 breach). The
    five-tag family catches it via `auction2`. This is the reason
    auction_detection.tags is not just ['auctions']."""
    p = _by_title(products, ORPHAN_AUCTION)
    assert "auctions" not in p["tags"], "fixture drift — the orphan row grew an 'auctions' tag"
    assert "auction2" in p["tags"]
    assert _is_auction(p, CHERRY_AUCTION_DETECTION) is True, (
        "orphan round-tag auction NOT detected — its live bid would write through as a buy-price"
    )
    # And it is nulled through the real normalize path (obligation #1).
    assert p["variants"][0]["price"] == "250.00", "fixture drift — expected the $250 orphan bid"
    assert _normalize(p)["current_price"] is None
    # Control: dropping auction2 from the detection set would re-expose the bid.
    assert _is_auction(p, {"tags": ["auctions"]}) is False


# Test 8 (THE GUARANTEE): live auction lands current_price=NULL + is_auction=true
def test_live_auction_price_nulled_and_flagged(products):
    """The live-auction anchor carries a real $88.88 bid that must NEVER write
    through (INV-05 obligation #1, decision #70). _normalize_product with the
    real auction_detection nulls current_price and sets is_auction=true.

    EXERCISES THE GUARANTEE (feedback_review_results_test_exercises_guarantee):
    asserted through the real _normalize_product null-out branch (L645-648). If
    that branch is deleted, current_price coerces to Decimal('88.88') and this
    test FAILS."""
    p = _by_title(products, LIVE_AUCTION)
    assert p["variants"][0]["price"] == "88.88", "fixture drifted — expected the $88.88 live bid"
    assert p["variants"][0]["available"] is True, "fixture drifted — expected a LIVE (available) auction"
    norm = _normalize(p)
    assert norm["current_price"] is None, (
        f"auction price not nulled: {norm['current_price']!r} — the null-price branch "
        "(parse_shopify _normalize_product L645-648) is the guarantee"
    )
    assert norm["is_auction"] is True, "is_auction not set on the auction row"
    assert norm["compare_at_price"] is None  # compare_at inherits the auction carve-out (CTK-100 L4)


# Test 9: an OOS (ended-round) auction is still kept + flagged + price-nulled
def test_oos_auction_kept_flagged_nulled(products):
    """877 of the 958 auctions are available:false (ended rounds) at the walk. An
    OOS auction is STILL kept (in_stock_only=False), still is_auction=true, still
    price-nulled — the OOS-flip itself is the persist-layer job (diff.py /
    cohort_oos_at_persist), but the parse-layer guarantees hold regardless of
    availability."""
    p = _by_title(products, OOS_AUCTION)
    assert p["variants"][0]["available"] is False, "fixture drifted — expected an ENDED (unavailable) auction"
    assert _keep(p) is True, "OOS auction wrongly dropped at parse (in_stock_only must be false)"
    norm = _normalize(p)
    assert norm["is_auction"] is True
    assert norm["current_price"] is None, "OOS auction bid must not write through"


# Test 10: non-auction coral keeps its real price (no collateral null-out)
def test_non_auction_coral_keeps_price(products):
    """The happy-path coral (Baby Tequila) — non-auction. is_auction=false and
    current_price is its real value; the null-out is scoped to auctions only, not
    a blanket coral behavior."""
    p = _by_title(products, CORAL_ANCHOR)
    norm = _normalize(p)
    assert norm["is_auction"] is False
    assert norm["current_price"] is not None, "non-auction coral price should not be nulled"


# Test 11: denylist specificity — the walk's collision tokens do NOT fire
def test_denylist_collision_tokens_do_not_fire(products):
    """The walk's token sweep confirmed most obvious non-coral words collide with
    Cherry morph names and are BANNED from the denylist. Pin that real corals
    carrying those substrings survive, while the genuine non-coral tail drops."""
    # Non-coral tail drops.
    assert _keep({"title": "Cherry Corals Gift Card", "product_type": "", "tags": ["Fresh Cherries", "Gift Card"]}) is False
    assert _keep({"title": "Cherry Corals Auction Shipping - FAR States Only", "product_type": "", "tags": ["box"]}) is False
    # ...but the collision-token corals survive (these substrings are NOT denied).
    for coral in [
        "Aussie Highlighter Hammer",     # 'light'
        "POTO El Camino #2",             # 'amino'
        "Haterade Zoanthids",            # 'hat'
        "CC Mystery Coral #1",           # 'mystery'
        "WWC Bejeweled Favia",           # 'led'
        "KH Sunburst Zoanthids",         # 'kh'
        "Greatest Show Zoanthids",       # 'test' (grea-TEST-)
    ]:
        assert _keep({"title": coral, "product_type": "", "tags": ["Fresh Cherries", "Zoanthids", "auctions"]}) is True, coral


# Test 12: fleet-wide chaeto/macroalgae forward-bind
def test_chaeto_macroalgae_forward_bind(products):
    """The fleet-wide chaeto/macroalgae title_denylist (CTK-107 D-2-quater).
    Cherry carries 0 such rows today; these entries are forward-insurance. Pin
    that they WOULD fire on synthetic rows while a control coral survives."""
    for junk_title in ["Cheato Macro Refugium", "Chaetomorpha Macroalgae", "Dragon's Breath Macro Algae"]:
        assert _keep({"title": junk_title, "product_type": "", "tags": []}) is False, junk_title
    assert _keep({"title": "Green Slimer Acro", "product_type": "", "tags": ["Fresh Cherries"]}) is True


# Test 13: _normalize_product output shape — coral product
def test_normalize_output_shape(products):
    """_normalize_product on the happy-path coral — validates output dict shape
    per arch §1.4 vendor_listings columns + absolute product_url (CTK-033 D1)."""
    p = _by_title(products, CORAL_ANCHOR)
    norm = _normalize(p)
    assert norm["raw_title"] == CORAL_ANCHOR
    assert norm["product_url"].startswith("https://cherrycorals.com/products/")
    assert norm["currency"] == "USD"
    assert norm["vendor_image_url"] is not None
    assert "cdn.shopify.com" in norm["vendor_image_url"]
    assert infer_category(p) == "mushroom"   # Mushrooms and Ricordea tag


# Test 14: coverage floor over the BROWSE-ELIGIBLE (non-auction) set
def test_category_coverage_floor_non_auction(products):
    """CTK-143 Q1 coverage ruling: the gate is measured over the browse-eligible
    (non-auction) set, NOT the full catalog. Auctions are CTK-042-gated off every
    browse surface, so their NULL category is harmless. Over the 311 non-auction
    kept rows, infer_category leaves exactly 10 NULL (3.22% < 10%). The
    full-catalog 43.74% NULL is sanctioned absence-of-signal (genus-less auction
    morphs). Pins the decision + the exact non-auction NULL set."""
    kept = [p for p in products if _keep(p)]
    non_auction = [p for p in kept if not _is_auc(p)]
    assert len(non_auction) == EXPECTED_NON_AUCTION_KEPT, (
        f"non-auction kept drifted: expected {EXPECTED_NON_AUCTION_KEPT}, got {len(non_auction)}"
    )
    null_titles = {p["title"] for p in non_auction if infer_category(p) is None}
    ratio = len(null_titles) / len(non_auction) * 100
    assert ratio <= COVERAGE_NULL_THRESHOLD_PCT, (
        f"browse-eligible coverage regressed: {ratio:.2f}% NULL > {COVERAGE_NULL_THRESHOLD_PCT}%"
    )
    assert len(null_titles) == EXPECTED_NON_AUCTION_NULL, (
        f"expected {EXPECTED_NON_AUCTION_NULL} non-auction NULL rows, got {len(null_titles)}"
    )
    assert null_titles == EXPECTED_NON_AUCTION_NULL_TITLES, (
        f"non-auction NULL set drifted — extra: {null_titles - EXPECTED_NON_AUCTION_NULL_TITLES}, "
        f"missing: {EXPECTED_NON_AUCTION_NULL_TITLES - null_titles}"
    )


# Test 15 (COMMON, harness, MIRROR-PARITY CTK-115): CONFIG == cherry.yaml, incl. auction_detection
def test_yaml_mirror_parity():
    check_yaml_mirror_parity(CONFIG)


def main() -> int:
    return run_main(
        CONFIG,
        tests=[
            test_html_hash_first_product_keys,
            test_total_kept_is_1269,
            test_exact_drop_set,
            test_no_category_tag_auction_corals_survive,
            test_no_allowlist_feed_relabel_survives,
            test_auction_detected_on_auctions_tag,
            test_auction_orphan_round_tag_detected,
            test_live_auction_price_nulled_and_flagged,
            test_oos_auction_kept_flagged_nulled,
            test_non_auction_coral_keeps_price,
            test_denylist_collision_tokens_do_not_fire,
            test_chaeto_macroalgae_forward_bind,
            test_normalize_output_shape,
            test_category_coverage_floor_non_auction,
            test_yaml_mirror_parity,
        ],
        no_param={test_yaml_mirror_parity},
    )


if __name__ == "__main__":
    sys.exit(main())
