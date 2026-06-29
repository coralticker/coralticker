"""scrapers/tests/test_biota_parse.py — CTK-212 parse-layer tests for Biota
(The Biota Group)'s Shopify /products.json shape against locked fixture
scrapers/tests/fixtures/biota/products.sample.json.

Built on scrapers/tests/vendor_parse_harness.py (CTK-208). The shared scaffolding
(_load_fixture, the _keep/_normalize/_tag_denylist_norm production-call wrappers,
_by_title, the pytest fixture shim, main(), and the two common tests —
html_hash_first_product_keys + yaml_mirror_parity) lives in the harness, driven by
the CONFIG below. The Biota-specific regressions are the bespoke half.

Parse-only — no DB, no network. Validates parse_shopify._normalize_product output
shape + html_hash sentinel + the HYBRID category_filter (product_type_allowlist +
the "" empty bucket + title_denylist) AND the CTK-212 normalize._CATEGORY_PATTERNS
change (clam relocated below invert + invert/softie token adds).

WHY THIS TEST EXISTS (the regressions it pins):

  Finding A — the "" empty-bucket coral rescue. The page-1 pre-flight read
  "249/250 cleanly tagged" but the FULL 615-row walk has a 27-row empty-
  product_type tail holding 14 REAL Biota corals (13 own-brand "Biota Palau ...
  Acropora Mini-colony" + "Shrek Lobo Devil's Hand Coral"). A pure 4-type allowlist
  drops every one (invisible-coral-out). "" is added to keep them;
  test_empty_bucket_corals_survive pins that removing "" drops them. The same ""
  admits 13 ∅ non-corals (pumps/acclimation/feeder/frozen-food/gobies + 4 tank
  BUNDLES) that the title_denylist drops — test_empty_bucket_noncorals_drop pins
  the exact 13-row drop set with zero coral collateral.

  Finding B — invert vs clam precedence. Biota tags EVERY clam AND EVERY invert
  with the shared tag "Cultured Clams & Invertebrates", so `\\bclams?\\b` fired on
  the tag for every shrimp/crab/urchin/snail/nudibranch; with clam previously above
  invert in _CATEGORY_PATTERNS, all the real inverts stole into `clam` (crabs under
  the clam filter on live traffic). CTK-212 RELOCATES clam to the tail (… fish,
  invert, clam, equipment) — NOT lifting invert (that would let a bare invert-token
  in a coral trade name like "Fiddler Crab Zoa" steal corals into invert).
  test_invert_bucket_classification + test_clam_relocation_precedence pin both
  directions. invert += nudibranch/sea slug recovers the 3 untokened inverts.

  Finding C — softie coverage. Biota gorgonian sea fans, Spaghetti Nephthea, and
  Strawberry Tree Coral were NULL-category; softie += sea fan/nephthea/tree coral.
  Pinned in test_softie_coverage_adds (and fleet-wide in test_infer_category_coverage).

INV-05 is NOT triggered: the FULL 3-page walk (615 rows, 2026-06-29 — NOT a page-1
sample, per feedback_absence_diag_full_catalog_sweep + the CTK-142 lesson) found
zero auction signal. biota.yaml carries no auction_detection block; yaml_mirror_parity
pins that absence.

Mirror-parity (CTK-115): the harness yaml_mirror_parity loads scrapers/vendors/
biota.yaml and asserts the CONFIG category_filter equals the YAML block byte-exact,
that the axis-set is exactly {product_type_allowlist, title_denylist}, and that NO
tag_allowlist appears (CONFIG.expected_absent_axes — a tag_allowlist would AND-narrow
and silently drop the no-tag corals).

Runnable as:
  python -m scrapers.tests.test_biota_parse

Fixture regen path: re-fetch shop.thebiotagroup.com/products.json?limit=250 across
pages (the Session-1 walk shape: 615 rows / 3 pages) and re-dump the
{"products": [...]} payload. NOTE: re-pinning moves the kept count + drop inventory
+ coverage-floor NULL rows as the live catalog drifts — update EXPECTED_TOTAL/
EXPECTED_KEPT/DROPPED_TITLES + the NULL set to match the snapshot.
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


# Hand-mirror of scrapers/vendors/biota.yaml category_filter — kept BYTE-EXACT with
# the YAML (order included); yaml_mirror_parity asserts the equality so a YAML
# amendment that isn't mirrored here fails loudly (CTK-115 drift class). HYBRID:
# product_type_allowlist (the 4 named types + the "" empty bucket) + title_denylist.
BIOTA_CATEGORY_FILTER = {
    "product_type_allowlist": [
        "Aquacultured Corals",
        "Cultured Coral",
        "Maricultured Corals",
        "Aquacultured Invertebrates",
        "",
    ],
    "title_denylist": [
        "Sicce", "Acclimation", "EZ Feeder", "Frozen Food", "Goby",
        "Reef Tank", "Reef-Ready Tank", "Chaeto", "Cheato", "Macroalgae",
    ],
}

CONFIG = VendorParseConfig(
    fixture_path=Path(__file__).parent / "fixtures" / "biota" / "products.sample.json",
    yaml_path=Path(__file__).parent.parent / "vendors" / "biota.yaml",
    base_url="https://shop.thebiotagroup.com",
    image_strategy="mirror",
    originator_prefix=None,   # CTK-212 — null (no Biota-attributed seed-list canonicals)
    auction_detection=None,   # CTK-212 — INV-05 not triggered; no auction_detection block
    category_filter=BIOTA_CATEGORY_FILTER,
    in_stock_only=False,
    expected_first_product_keys=[
        "body_html", "created_at", "handle", "id", "images", "options",
        "product_type", "published_at", "tags", "title", "updated_at",
        "variants", "vendor",
    ],
    html_hash_sentinel="c94c512f27be051326728462bfaf34b4b4cb3f2595a3eafbe44ba45a672aad70",
    expected_filter_keys=frozenset({"product_type_allowlist", "title_denylist"}),
    # A tag_allowlist would AND-narrow the keep gate and silently drop the no-tag /
    # empty-bucket corals — its absence is load-bearing for Finding A.
    expected_absent_axes=frozenset({"tag_allowlist"}),
    expect_in_stock_only_absent=True,
    expect_auction_detection_none=True,
)

_keep = make_keep(CONFIG)
_normalize = make_normalize(CONFIG)


# Expected keep/drop counts on the LOCKED 2026-06-29 fixture (615 rows). 320 kept:
# 306 from the 4-type allowlist + the 14 real ∅ corals; 295 dropped (211 Cultured
# Fish + 32 Feeds + ~40 merch + 1 Live Animals + 1 Animals&Pet + the 13 ∅ non-corals
# the title_denylist removes).
EXPECTED_TOTAL = 615
EXPECTED_KEPT = 320

# The exact 13 ∅ non-corals the title_denylist drops (the only "" -admitted drops).
EMPTY_BUCKET_DROPPED = {
    "Breeder's Blend Frozen Food Biota x Rogger's Reef Foods",
    "Yellow Clown Goby",
    "Cosmic Nano Goby",
    "Custom Biota Acclimation Box - PNWCustom",
    "Tanklimate Acclimation Box - Eshopps",
    "EZ Feeder - Eshopps",
    "Sicce Ultra Zero Solids Handling and Utility Pump",
    "Sicce Multipurpose Pump",
    "Sicce Syncra Silent Pump",
    "Biota Aquarium 2.0 - Lomalo Reef Tank 35.2",
    "Biota Aquarium 2.0 - Nano Reef Tank",
    "Biota Aquarium Kit 2.0 - Lau'ipala Reef Tank",
    "Biota Custom Micro Reef-Ready Tank 40oz Desktop Aquarium - with Livestock",
}

# The 14 real corals in the "" empty bucket that "" rescues (Finding A). A pure
# 4-type allowlist drops all of these.
EMPTY_BUCKET_CORALS = {
    'Biota Palau "Firecracker" Acropora Mini-colony Grade A',
    "Biota Palau Table Acropora Mini-colony",
    "Biota Palau Slime Mold Acropora Mini-Colony",
    "Biota Palau Turtle Bay Acropora mini-colony",
    "Biota Palau Mutated Meatball Acropora Mini-colony",
    "Biota Palau LSP (Lumpy Space Princess) Acropora Mini-colony",
    "Biota Palau Pastel Goth Acropora Mini-colony",
    "Biota Palau Royal Boba Acropora Mini-colony",
    "Biota Palau Bubble's Valida Acropora Mini-colony",
    "Biota Palau Helen's Elegant Smoothskin Acropora Mini-colony Grade A",
    "Biota Palau Green Branching Acropora Mini-Colony",
    "Biota Palau Manu's Blue Bottlebrush Acropora Mini-colony Grade A",
    "Biota Palauberry Acropora Mini-colony",
    "Shrek Lobo Devil's Hand Coral",
}

# Coverage-floor (CTK-212): over the KEPT set, infer_category leaves 6 rows NULL —
# all genus-opaque coral trade names (NPS polyps, brain, faviids, a chalice trade
# name, a misspelled zoanthid, a "papaya" trade name). 6/320 = 1.88% < 10%, so
# _CATEGORY_PATTERNS is NOT further edited for them.
COVERAGE_NULL_THRESHOLD_PCT = 10.0
EXPECTED_NULL_TITLES = {
    "Assorted Palau Faviids",
    "Gold NPS Polyps",
    "Green Center Brain Coral",
    "Green Papaya Coral LIMITED",
    "Hollywood Stunner",
    "Oompa Loompa Zooanthid Frag",
}

CORAL_ANCHOR = "Squamosa Clam"   # a kept clam with image + price


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


# Test 2: total kept = 320 on the locked 615-row fixture
def test_total_kept_is_320(products):
    assert len(products) == EXPECTED_TOTAL, f"fixture drifted: expected {EXPECTED_TOTAL}, got {len(products)}"
    kept = sum(1 for p in products if _keep(p))
    assert kept == EXPECTED_KEPT, f"expected {EXPECTED_KEPT} kept, got {kept}"


# Test 3 (FINDING A regression): the 14 ∅ corals survive via the "" empty bucket
def test_empty_bucket_corals_survive(products):
    """The load-bearing Finding A regression. 14 real Biota corals sit in the empty
    product_type bucket (13 Palau Acropora mini-colonies + Shrek Lobo). The ""
    allowlist entry keeps them; a pure 4-type allowlist drops every one
    (invisible-coral-out). Pin that all 14 survive AND isolate the axis: a ∅ coral
    is kept, but the SAME row fails a 4-type-only allowlist."""
    kept_empty = {p["title"] for p in products
                  if (p.get("product_type") or "") == "" and _keep(p)}
    assert EMPTY_BUCKET_CORALS <= kept_empty, (
        f"∅ corals wrongly dropped (was \"\" removed from the allowlist?): "
        f"{EMPTY_BUCKET_CORALS - kept_empty}"
    )
    # Isolate the axis: a ∅, coral-tagged row is kept ONLY because of "".
    from scrapers.common.parse_shopify import _should_keep
    four_type_only = {"product_type_allowlist": BIOTA_CATEGORY_FILTER["product_type_allowlist"][:4]}
    palau = _by_title(products, "Biota Palau Table Acropora Mini-colony")
    assert _keep(palau) is True
    assert _should_keep(palau, four_type_only) is False, (
        "a pure 4-type allowlist must drop the ∅ Palau coral — that is the "
        'invisible-coral-out failure "" exists to fix'
    )


# Test 4 (FINDING A): the 13 ∅ non-corals drop, with zero coral collateral
def test_empty_bucket_noncorals_drop(products):
    """The "" entry admits 13 ∅ non-corals (3 Sicce pumps, 2 acclimation boxes, EZ
    feeder, frozen food, 2 gobies, 4 tank BUNDLES). The title_denylist drops exactly
    those 13 — pin the set so a denylist coarsening (or a coral title that starts
    matching a denylist term) surfaces loudly. The 4 "Reef Tank" rows are livestock-
    bundle SETUPS (full tanks), not coral drops."""
    dropped_empty = {p["title"] for p in products
                     if (p.get("product_type") or "") == "" and not _keep(p)}
    assert dropped_empty == EMPTY_BUCKET_DROPPED, (
        f"∅ drop set drifted.\n  unexpected: {dropped_empty - EMPTY_BUCKET_DROPPED}\n"
        f"  missing: {EMPTY_BUCKET_DROPPED - dropped_empty}"
    )


# Test 5 (FINDING B regression): the invert bucket classifies correctly
def test_invert_bucket_classification(products):
    """The load-bearing Finding B regression. The 'Aquacultured Invertebrates'
    product_type bucket carries the shared tag 'Cultured Clams & Invertebrates' on
    EVERY row, so `\\bclams?\\b` fired on the tag and (pre-CTK-212, clam-above-invert)
    stole every shrimp/crab/urchin/snail/nudibranch into `clam`. After the clam
    relocation + nudibranch/sea-slug tokens: real inverts -> invert, real clams ->
    clam, BTAs -> anemone. If a crab/shrimp starts reading `clam` again, clam was
    moved back above invert."""
    real_inverts = [
        "Arrow Crab", "Peppermint Shrimp", "White Urchin", "Purple Urchin",
        "Tuxedo Urchin", "Jewel Urchin", "Purple Zebra Porcelain Crab",
        '"Mini Trochus" Collonista Snails', "Long Arm Shrimp", "Harlequin Shrimp",
        "Elegant Rockpool Shrimp", "Fancy Peppermint Shrimp",
        "Spurilla Nudibranch - Aiptasia Eater",   # \bnudibranch (CTK-212 add)
        "Berghia Nudibranch - Aiptasia Eater",
        "Lettuce Sea Slug",                        # \bsea slug (CTK-212 add)
    ]
    for t in real_inverts:
        assert infer_category(_by_title(products, t)) == "invert", (
            f"{t!r} did not classify invert (clam relocated back above invert?)"
        )
    # Real clams sharing the SAME tag still floor to clam (relocation correctness).
    for t in ["Derasa Clam", "Squamosa Clam", "Ultra Grade Maxima Clam",
              "First Grade Crocea Clam", "Gigas Clam",
              "Bear Claw Clam - Cultured Hippopus Clam Grade A"]:
        assert infer_category(_by_title(products, t)) == "clam", f"{t!r} did not classify clam"
    # BTAs in the invert bucket -> anemone (anemone runs above invert/clam).
    assert infer_category(_by_title(products, "Mini Rose Bubble Tip Anemone")) == "anemone"


# Test 6 (FINDING B, precedence guard): clam was RELOCATED, invert was NOT lifted
def test_clam_relocation_precedence(products):
    """The relocation must not become an invert-lift. A coral trade name carrying a
    bare invert token ("Fiddler Crab Zoa") must still classify by its CORAL pattern
    (zoa), NOT invert — proving clam moved DOWN rather than invert moving UP above
    the coral patterns. Synthetic rows isolate the precedence."""
    assert infer_category({"title": "Fiddler Crab Zoa", "product_type": "", "tags": []}) == "zoa"
    assert infer_category({"title": "Crab Claw Acropora", "product_type": "", "tags": []}) == "sps"
    # The shared-tag mechanism, isolated: a crab with the Clams&Inverts tag -> invert.
    assert infer_category({"title": "Arrow Crab", "product_type": "Aquacultured Invertebrates",
                           "tags": ["Cultured Clams & Invertebrates"]}) == "invert"
    # ...and a real clam with the same tag -> clam (no coral token to steal it).
    assert infer_category({"title": "Derasa Clam", "product_type": "Aquacultured Invertebrates",
                           "tags": ["Cultured Clams & Invertebrates"]}) == "clam"


# Test 7 (FINDING C): softie coverage adds
def test_softie_coverage_adds(products):
    """CTK-212 softie token adds (sea fan / nephthea / tree coral) recover Biota's
    gorgonian sea fans + Nephthea + tree coral from NULL-category. Pin the real rows
    + the FP boundary (the tokens are phrase/whole-word, not bare 'fan'/'tree')."""
    for t in ["Net Sea Fan Panama", "Tangerine Sea Fan", "Yellow Mopsella Sea Fan",
              "Red Swiftia Sea Fan", "Biota Palau Pink Sea Fan",
              "Spaghetti Nephthea", "Green Strawberry Tree Coral"]:
        assert infer_category(_by_title(products, t)) == "softie", f"{t!r} did not classify softie"
    # FP boundary — bare "fan"/"tree" must not force softie.
    assert infer_category({"title": "Cooling Fan Mount", "product_type": "", "tags": []}) is None
    assert infer_category({"title": "Family Tree Acropora", "product_type": "", "tags": []}) == "sps"


# Test 8: coverage floor — NULL-category ratio over the KEPT set under threshold
def test_category_coverage_floor(products):
    """Over the KEPT set (production parser output), infer_category leaves exactly 6
    rows NULL — all genus-opaque trade names. 6/320 = 1.88% < 10% threshold, so
    _CATEGORY_PATTERNS is NOT further edited. Pins the decision + the exact NULL set
    (a different NULL row appearing is a coverage regression)."""
    kept = [p for p in products if _keep(p)]
    null_titles = [p.get("title") for p in kept if infer_category(p) is None]
    ratio = len(null_titles) / len(kept) * 100
    assert ratio <= COVERAGE_NULL_THRESHOLD_PCT, (
        f"category coverage regressed: {ratio:.2f}% NULL > {COVERAGE_NULL_THRESHOLD_PCT}% "
        f"(NULL: {collections.Counter(null_titles)})"
    )
    assert set(null_titles) == EXPECTED_NULL_TITLES, (
        f"NULL set drifted — expected {EXPECTED_NULL_TITLES}, got {set(null_titles)}"
    )


# Test 9: no auction null-out — INV-05 not triggered at the normalize layer
def test_normalize_no_auction_nulling(products):
    """biota.yaml carries no auction_detection (AUCTION_DETECTION=None), so a coral
    normalizes with is_auction=False and keeps its real price. Pins INV-05-not-
    triggered at the _normalize_product layer (full 3-page walk found zero auction
    signal)."""
    p = _by_title(products, CORAL_ANCHOR)
    norm = _normalize(p)
    assert norm["is_auction"] is False
    assert norm["current_price"] is not None, "non-auction coral price must not be nulled"


# Test 10: _normalize_product output shape — coral product, absolute store URL
def test_normalize_output_shape(products):
    """_normalize_product on a coral — output dict shape per arch §1.4 vendor_listings
    columns + absolute product_url on the STORE domain (CTK-033 D1; never the parked
    biota.com / biotaaquariums.com)."""
    p = _by_title(products, CORAL_ANCHOR)
    norm = _normalize(p)
    assert norm["raw_title"] == CORAL_ANCHOR
    assert norm["product_url"].startswith("https://shop.thebiotagroup.com/products/")
    assert norm["currency"] == "USD"
    assert norm["vendor_image_url"] is not None
    assert "cdn.shopify.com" in norm["vendor_image_url"]
    assert infer_category(p) == "clam"


# Test 11 (COMMON, harness, MIRROR-PARITY CTK-115): CONFIG == biota.yaml
def test_yaml_mirror_parity():
    check_yaml_mirror_parity(CONFIG)


def main() -> int:
    return run_main(
        CONFIG,
        tests=[
            test_html_hash_first_product_keys,
            test_total_kept_is_320,
            test_empty_bucket_corals_survive,
            test_empty_bucket_noncorals_drop,
            test_invert_bucket_classification,
            test_clam_relocation_precedence,
            test_softie_coverage_adds,
            test_category_coverage_floor,
            test_normalize_no_auction_nulling,
            test_normalize_output_shape,
            test_yaml_mirror_parity,
        ],
        no_param={test_yaml_mirror_parity},
    )


if __name__ == "__main__":
    sys.exit(main())
