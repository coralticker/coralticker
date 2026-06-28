"""scrapers/tests/test_reefundertheroof_parse.py — CTK-207 parse-layer tests for
Reef Under The Roof's Shopify /products.json shape against locked fixture
scrapers/tests/fixtures/reefundertheroof/products.sample.json.

CTK-208: migrated onto scrapers/tests/vendor_parse_harness.py. The shared scaffolding
(_load_fixture, the _keep/_normalize/_tag_denylist_norm production-call wrappers,
_by_title, the pytest fixture shim, main(), and the two common tests —
html_hash_first_product_keys + yaml_mirror_parity) now lives in the harness, driven by
the CONFIG below. The RUTR-specific regressions are kept textually unchanged.

Parse-only — no DB, no network. Validates parse_shopify._normalize_product output
shape + html_hash sentinel + the NO-ALLOWLIST title_denylist-only category_filter
that makes Reef Under The Roof a no-product_type_allowlist vendor (RR/AAF shape).

WHY THIS TEST EXISTS (the regressions it pins):
RUTR's product_type is blank store-wide (79/82 rows '', the other 3 = 2
'Aquarium Supplement' + 1 'service', all non-coral), so it is NOT a coral
taxonomy and NOT a coral/non-coral discriminator. The decision (CTK-207 #1) is NO
product_type_allowlist; the only gate is a title_denylist set from the Session-1
full-catalog walk (2026-06-28, the full catalog locked as this fixture, 82 rows on
a single page — NOT a page-1 sample, per feedback_absence_diag_full_catalog_sweep).

The RUTR-specific load-bearing regression (distinct from AAF's APS-bucket one):
the "Cut to Order Frag" corals (~bulk of the catalog) must survive the
Frag Plug / Frag Disk / Frag Pack denylist entries. Those entries are 2-word and
must NEVER bleed into the bare "Frag" in "<name> - Cut to Order Frag" — denylisting
bare "Frag" would silently drop the majority of the coral catalog
(test_cut_to_order_frag_corals_survive pins this).

Other regressions pinned:
  - Adding ANY product_type_allowlist silently drops the next feed-relabeled or
    new product_type — test_no_allowlist_feed_relabel_survives pins a
    never-before-seen product_type survives.
  - Coarsening / dropping the chaeto/macroalgae forward-bind — pinned by
    test_chaeto_macroalgae_forward_bind.

INV-05 is NOT triggered: the full-catalog walk found zero auction signal (no
wk_end_auction/auc/bid tags, no product_type:Auction, no 'auction' in any
title/handle). reefundertheroof.yaml carries no auction_detection block;
yaml_mirror_parity pins that absence so a future block can't land unmirrored.

Mirror-parity (CTK-115 convention): the harness yaml_mirror_parity loads
scrapers/vendors/reefundertheroof.yaml and asserts the CONFIG category_filter equals
the YAML block byte-exact, AND that the YAML carries NO product_type_allowlist and NO
tag_allowlist (the load-bearing absences via CONFIG.expected_absent_axes) — either
landing later fails loudly.

Runnable as:
  python -m scrapers.tests.test_reefundertheroof_parse

Fixture regen path: re-fetch reefundertheroof.com/products.json?limit=250&page=1
(single page, the Session-1 walk shape: 82 rows) and re-dump the
{"products": [...]} payload. NOTE: re-pinning will move the kept count + the drop
inventory + the coverage-floor NULL rows as the live catalog drifts — update
EXPECTED_TOTAL/EXPECTED_KEPT/DROPPED_TITLES + the NULL set to match the snapshot.
"""

from __future__ import annotations

import collections
import sys
from pathlib import Path

from scrapers.common.normalize import infer_category
from scrapers.tests.vendor_parse_harness import (
    VendorParseConfig,
    by_title as _by_title,
    check_html_hash_first_product_keys,
    check_yaml_mirror_parity,
    make_keep,
    make_normalize,
    run_main,
)


# Hand-mirror of scrapers/vendors/reefundertheroof.yaml category_filter — kept
# byte-exact with the YAML; yaml_mirror_parity asserts the equality so a YAML
# amendment that isn't mirrored here fails loudly (CTK-115 drift class). NOTE the
# deliberate ABSENCE of product_type_allowlist AND tag_allowlist — RUTR is a
# no-allowlist vendor (CTK-207 #1). Only the 15-row non-coral tail + the chaeto
# forward-bind are denied, all by title.
RUTR_CATEGORY_FILTER = {
    "title_denylist": [
        "Macroalgae", "Mangrove", "Frag Plug", "Frag Disk", "Frag Pack",
        "Aquarium Supplement", "Aquarium Management", "Coaching Session",
        "Consultation", "Chaeto", "Cheato",
    ],
}

CONFIG = VendorParseConfig(
    fixture_path=Path(__file__).parent / "fixtures" / "reefundertheroof" / "products.sample.json",
    yaml_path=Path(__file__).parent.parent / "vendors" / "reefundertheroof.yaml",
    base_url="https://reefundertheroof.com",
    image_strategy="mirror",
    originator_prefix=None,   # CTK-207 — null (no RUTR-attributed seed-list canonicals)
    auction_detection=None,   # CTK-207 — INV-05 not triggered; no auction_detection block
    category_filter=RUTR_CATEGORY_FILTER,
    in_stock_only=False,      # RUTR has no in_stock_only
    expected_first_product_keys=[
        "body_html", "created_at", "handle", "id", "images", "options",
        "product_type", "published_at", "tags", "title", "updated_at",
        "variants", "vendor",
    ],
    html_hash_sentinel="c94c512f27be051326728462bfaf34b4b4cb3f2595a3eafbe44ba45a672aad70",
    expected_filter_keys=frozenset({"title_denylist"}),
    expected_absent_axes=frozenset({"product_type_allowlist", "tag_allowlist"}),
    expect_in_stock_only_absent=True,
    expect_auction_detection_none=True,
)

_keep = make_keep(CONFIG)
_normalize = make_normalize(CONFIG)


# Expected keep/drop counts on the LOCKED 2026-06-28 fixture (82 rows). Exactly
# 15 rows drop (the non-coral tail); the chaeto forward-bind's Cheato entry fires
# on ZERO real rows. Any allowlist regression that drops coral, or a denylist that
# false-fires on a coral title (e.g. bare "Frag"), moves these counts.
EXPECTED_TOTAL = 82
EXPECTED_KEPT = 67
EXPECTED_DROPPED = EXPECTED_TOTAL - EXPECTED_KEPT  # 15; derived so a re-pin can't desync it

# The exact 15-row non-coral tail (the only drops on the locked fixture).
DROPPED_TITLES = {
    "Dragon's Breath Macroalgae",
    "Chaetomorpha Macroalgae",
    "Caulerpa Brachypus Macroalgae",
    "Red Pom Pom Gracilaria Macroalgae",
    "Caulerpa Prolifera Macroalgae",
    "Red Mangrove",
    "Professional Aquarium Management Services",
    'White XXL 3" Coral Frag Disks - 6 Pack',
    'White Large 1 3/4" Coral Frag Plugs - 20 Pack',
    'White Small 3/4" Coral Frag Plugs - 30 Pack',
    "10 Piece Mixed Frag Pack (FREE SHIPPING)",
    "10 Piece SPS Frag Pack (FREE SHIPPING)",
    "Coaching Session - 1 hour Consultation",
    "Phosphate - Aquarium Supplement",
    "Nitrate - Aquarium Supplement",
}

# Coverage-floor decision (CTK-207): infer_category leaves exactly TWO KEPT rows
# NULL on the locked fixture — both genus-less trade names. 2/67 = 3.0%, far under
# the 10% pre-flight threshold, so _CATEGORY_PATTERNS is NOT edited for them.
COVERAGE_NULL_THRESHOLD_PCT = 10.0
EXPECTED_NULL_TITLES = {"Dino Fury", "RR The Vinh - Cut to Order Frag"}
EXPECTED_NULL_KEPT_COUNT = 2

# A unique coral title with image + price — exercises the CTK-207 \btort\b token
# AND the "Cut to Order Frag" survival (bare Frag not denylisted) in one anchor.
CORAL_ANCHOR = "Cali Tort Acro - Cut to Order Frag"


try:
    import pytest

    @pytest.fixture(scope="module")
    def products():
        from scrapers.tests.vendor_parse_harness import load_fixture
        return load_fixture(CONFIG)
except ImportError:
    pass


# Test 1 (COMMON, harness): html_hash sentinel — sorted-keys-of-first-product SHA256
def test_html_hash_first_product_keys(products):
    check_html_hash_first_product_keys(products, CONFIG)


# Test 2: total kept = 67 (82 - the 15-row non-coral tail)
def test_total_kept_is_67(products):
    """Full-catalog keep count on the locked 82-row fixture: 67 kept, 15 dropped.
    With no product_type_allowlist and a title_denylist that hits only the
    non-coral tail, the entire coral catalog survives. Any allowlist regression
    that drops coral, or a denylist that false-fires on a coral title (e.g. bare
    "Frag"), moves these counts."""
    assert len(products) == EXPECTED_TOTAL, f"fixture drifted: expected {EXPECTED_TOTAL} rows, got {len(products)}"
    kept = sum(1 for p in products if _keep(p))
    dropped = len(products) - kept
    assert kept == EXPECTED_KEPT, f"expected {EXPECTED_KEPT} kept, got {kept}"
    assert dropped == EXPECTED_DROPPED, f"expected {EXPECTED_DROPPED} dropped, got {dropped}"


# Test 3: the exact non-coral tail drops, nothing else
def test_exact_drop_set(products):
    """The 15 dropped titles are exactly the non-coral tail — no coral collateral.
    Pins the drop set so a denylist coarsening (or a coral title that starts
    matching a denylist term) surfaces loudly."""
    dropped = {p["title"] for p in products if not _keep(p)}
    assert dropped == DROPPED_TITLES, (
        f"drop set drifted.\n  unexpected drops: {dropped - DROPPED_TITLES}\n"
        f"  missing drops: {DROPPED_TITLES - dropped}"
    )


# Test 4 (THE RUTR REGRESSION): "Cut to Order Frag" corals survive the Frag* denylist
def test_cut_to_order_frag_corals_survive(products):
    """The load-bearing RUTR regression: the Frag Plug / Frag Disk / Frag Pack
    denylist entries are 2-word and must NEVER bleed into the bare "Frag" in
    "<name> - Cut to Order Frag" — the form most of RUTR's coral catalog uses.
    Denylisting bare "Frag" would silently drop the majority of the catalog. Every
    "Cut to Order Frag" coral MUST survive; pin a representative set + assert none
    drop. If this fails, someone denylisted bare "Frag"."""
    ctof = [p for p in products if "cut to order frag" in p["title"].lower()]
    assert len(ctof) >= 40, (
        f"fixture drift: expected the bulk of the catalog to be 'Cut to Order "
        f"Frag' corals, got {len(ctof)}"
    )
    dropped = [p["title"] for p in ctof if not _keep(p)]
    assert dropped == [], (
        f"'Cut to Order Frag' corals were wrongly dropped (bare 'Frag' "
        f"denylisted?): {dropped}"
    )
    # Isolate the axis: a real frag-plug PACK drops, but the same-shaped coral with
    # "Cut to Order Frag" survives.
    assert _keep({"title": 'White Small 3/4" Coral Frag Plugs - 30 Pack', "product_type": "", "tags": []}) is False
    assert _keep({"title": "Rainbow Loom Acro - Cut to Order Frag", "product_type": "", "tags": []}) is True


# Test 5: a feed-relabeled / never-before-seen product_type survives (no-allowlist)
def test_no_allowlist_feed_relabel_survives(products):
    """The feed-relabel guard. Under the no-allowlist decision, a never-before-seen
    product_type (a relabel to a Google category, or a new bucket) MUST survive — a
    synthetic coral with a brand-new product_type and a clean title is kept. This is
    exactly what a product_type_allowlist would silently drop catalog-wide on a feed
    relabel. If this starts failing, someone added an allowlist (the CTK-207 #1
    regression)."""
    relabeled = {
        "title": "Rainbow Splice Acro - Cut to Order Frag",
        "product_type": "Animals & Pet Supplies > Pet Supplies > Fish Supplies",
        "tags": [],
    }
    assert _keep(relabeled) is True, (
        "a feed-relabeled coral was dropped — a product_type_allowlist must have "
        "been added; that silently drops the catalog on a feed relabel (CTK-207 #1)"
    )
    novel = {"title": "RUTR Mystery Acro", "product_type": "BrandNewBucket", "tags": []}
    assert _keep(novel) is True, "a novel product_type bucket was dropped — no-allowlist violated"


# Test 6: chaeto/macroalgae forward-bind fires on synthetic + the real macroalgae
def test_chaeto_macroalgae_forward_bind(products):
    """The macroalgae + chaeto title_denylist. On the locked catalog it drops the 5
    real macroalgae rows (all carry 'Macroalgae'); the 'Cheato' misspelling entry
    is pure forward-bind (zero rows today). Pin that it WOULD fire on a synthetic
    'Cheato' row while a control coral survives."""
    for junk_title in [
        "Cheato Macro Refugium Starter",   # 'Cheato' misspelling forward-bind
        "Chaetomorpha Macroalgae",         # real row, 'Chaeto' + 'Macroalgae'
        "Mixed Macroalgae Pack",           # 'Macroalgae'
    ]:
        junk = {"title": junk_title, "product_type": "", "tags": []}
        assert _keep(junk) is False, f"macroalgae/chaeto forward-bind failed to drop: {junk_title!r}"

    control = {"title": "Bali Green Slimer - Cut to Order Frag", "product_type": "", "tags": []}
    assert _keep(control) is True, "FP control: a coral with no denied substring must survive"


# Test 7: no auction null-out — INV-05 not triggered at the normalize layer
def test_normalize_no_auction_nulling(products):
    """reefundertheroof.yaml carries no auction_detection (AUCTION_DETECTION=None),
    so coral normalizes with is_auction=False and keeps its real price. Pins the
    INV-05-not-triggered decision at the _normalize_product layer."""
    p = _by_title(products, CORAL_ANCHOR)
    norm = _normalize(p)
    assert norm["is_auction"] is False
    assert norm["current_price"] is not None, "non-auction coral price must not be nulled"


# Test 8: _normalize_product output shape — coral product
def test_normalize_output_shape(products):
    """_normalize_product on a coral — validates output dict shape per arch §1.4
    vendor_listings columns + absolute product_url (CTK-033 D1)."""
    p = _by_title(products, CORAL_ANCHOR)
    norm = _normalize(p)
    assert norm["raw_title"] == CORAL_ANCHOR
    assert norm["product_url"].startswith("https://reefundertheroof.com/products/")
    assert norm["currency"] == "USD"
    assert norm["vendor_image_url"] is not None
    assert "cdn.shopify.com" in norm["vendor_image_url"]
    # CTK-207 classifier patch: "Cali Tort" -> sps via the new \btort\b token.
    assert infer_category(p) == "sps"


# Test 9: coverage floor — NULL-category ratio over the KEPT set under threshold
def test_category_coverage_floor(products):
    """CTK-207 coverage decision: over the KEPT set (the production parser output),
    infer_category leaves exactly TWO rows NULL — both genus-less trade names
    ('Dino Fury', 'RR The Vinh'). 2/67 = 3.0% < 10% threshold, so
    _CATEGORY_PATTERNS is NOT edited for them. Pins the decision + the exact NULL
    set (a different NULL row appearing is a coverage regression)."""
    kept = [p for p in products if _keep(p)]
    null_titles = [p.get("title") for p in kept if infer_category(p) is None]
    ratio = len(null_titles) / len(kept) * 100
    assert ratio <= COVERAGE_NULL_THRESHOLD_PCT, (
        f"category coverage regressed: {ratio:.2f}% NULL > {COVERAGE_NULL_THRESHOLD_PCT}% "
        f"(NULL titles: {collections.Counter(null_titles)})"
    )
    assert len(null_titles) == EXPECTED_NULL_KEPT_COUNT, (
        f"expected {EXPECTED_NULL_KEPT_COUNT} NULL-category kept rows, got {len(null_titles)}"
    )
    assert set(null_titles) == EXPECTED_NULL_TITLES, (
        f"NULL-category set drifted — expected {EXPECTED_NULL_TITLES}, got {set(null_titles)}"
    )


# Test 10 (COMMON, harness, MIRROR-PARITY CTK-115): CONFIG == reefundertheroof.yaml
def test_yaml_mirror_parity():
    check_yaml_mirror_parity(CONFIG)


def main() -> int:
    return run_main(
        CONFIG,
        tests=[
            test_html_hash_first_product_keys,
            test_total_kept_is_67,
            test_exact_drop_set,
            test_cut_to_order_frag_corals_survive,
            test_no_allowlist_feed_relabel_survives,
            test_chaeto_macroalgae_forward_bind,
            test_normalize_no_auction_nulling,
            test_normalize_output_shape,
            test_category_coverage_floor,
            test_yaml_mirror_parity,
        ],
        no_param={test_yaml_mirror_parity},
    )


if __name__ == "__main__":
    sys.exit(main())
