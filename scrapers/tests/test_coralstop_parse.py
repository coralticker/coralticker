"""scrapers/tests/test_coralstop_parse.py — CTK-209 parse-layer tests for Coral
Stop's Shopify /products.json shape against locked fixture
scrapers/tests/fixtures/coralstop/products.sample.json.

Parse-only — no DB, no network. Validates parse_shopify._normalize_product output
shape + html_hash sentinel + the NO-ALLOWLIST title_denylist-only category_filter
that makes Coral Stop a no-product_type_allowlist / no-tag_allowlist vendor
(RR/AAF/RUTR shape).

WHY THIS TEST EXISTS (the regressions it pins):
Coral Stop's product_type is blank store-wide (939/939 rows ''), so it is NOT a
coral taxonomy and NOT a coral/non-coral discriminator. The decision (CTK-209 #1)
is NO product_type_allowlist AND NO tag_allowlist; the only gate is a title_denylist
set from the Session-1 full-catalog walk (2026-06-28, the full catalog locked as
this fixture, 939 rows across 4 pages — NOT a page-1 sample, per
feedback_absence_diag_full_catalog_sweep).

The Coral-Stop-specific load-bearing regression (the reason tag_allowlist is
banned): the "DOOR BUSTER" flash-sale corals carry NO 'CORAL' tag and NO
product_type. A tag_allowlist or product_type_allowlist would silently drop them —
exactly the corals a coverage product most wants. test_door_buster_corals_survive
pins that all 13 DOOR BUSTER rows survive.

Other regressions pinned:
  - Adding ANY product_type_allowlist/tag_allowlist silently drops the next
    feed-relabeled or no-tag product — test_no_allowlist_feed_relabel_survives.
  - The CTK-209 fox-coral lps fold — test_fox_coral_classifies_lps.
  - The denylist must not coarsen into coral trade names: "Frag Plug"/"Frag Plate"
    are 2-word and must not touch a bare-"Frag" coral; "Booster" must not become
    bare "Polyp" — test_denylist_specificity.
  - The "Leather Patch Hat" apparel row (which infer_category mis-buckets softie via
    \bleather) must drop — test_exact_drop_set + test_leather_patch_hat_drops.

INV-05 is NOT triggered: the full-catalog walk found zero auction signal (no
wk_end_auction/auc/bid tags, no product_type:Auction, no 'auction' in any
title/handle; DOOR BUSTER = fixed-price flash sale, not a bid surface).
coralstop.yaml carries no auction_detection block; test_yaml_mirror_parity pins
that absence.

Mirror-parity (CTK-115 convention): test loads scrapers/vendors/coralstop.yaml and
asserts the in-test CORALSTOP_CATEGORY_FILTER equals the YAML block byte-exact, AND
that the YAML carries NO product_type_allowlist and NO tag_allowlist (the
load-bearing absences) — either landing later fails test_yaml_mirror_parity loudly.

Runnable as:
  python -m scrapers.tests.test_coralstop_parse

Fixture regen path: re-fetch coralstop.com/products.json?limit=250 across pages
(the Session-1 walk shape: 939 rows / 4 pages) and re-dump the {"products": [...]}
payload. NOTE: re-pinning will move the kept count + the drop inventory + the
coverage-floor NULL rows as the live catalog drifts — update
EXPECTED_TOTAL/EXPECTED_KEPT/DROPPED_TITLES + the NULL set to match the snapshot.
"""

from __future__ import annotations

import collections
import hashlib
import json
import sys
import traceback
from pathlib import Path

import yaml

from scrapers.common.normalize import infer_category
from scrapers.common.parse_shopify import (
    _normalize_product,
    _normalize_tag,
    _should_keep,
)


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "coralstop" / "products.sample.json"
YAML_PATH = Path(__file__).parent.parent / "vendors" / "coralstop.yaml"
BASE_URL = "https://coralstop.com"
ORIGINATOR_PREFIX = None  # CTK-209 — null (no Coral-Stop-attributed seed-list canonicals)
IMAGE_STRATEGY = "mirror"
AUCTION_DETECTION = None   # CTK-209 — INV-05 not triggered; no auction_detection block

# Hand-mirror of scrapers/vendors/coralstop.yaml category_filter — kept byte-exact
# with the YAML; test_yaml_mirror_parity asserts the equality so a YAML amendment
# that isn't mirrored here fails loudly (CTK-115 drift class). NOTE the deliberate
# ABSENCE of product_type_allowlist AND tag_allowlist — Coral Stop is a no-allowlist
# vendor (CTK-209 #1). Only the 51-row non-coral tail is denied, all by title.
CORALSTOP_CATEGORY_FILTER = {
    "title_denylist": [
        "Amino", "Supplement", "Dry Powder", "Probiotic", "Live Bacteria",
        "Bacterial", "Phyto", "Mysis", "Reef-Roids", "Growth", "Power Elixir",
        "Power Food", "Liquid Vege", "Booster", "Lugol", "Iodine", "Coral Dip",
        "Glue", "Frag Plug", "Frag Plate", "T-Shirt", "Bucket Hat", "Patch Hat",
        "Towel", "Gift Card", "Shipping Module", "VorTech", "Vectra",
        "Return Pump", "Dosing Pump", "Reef Light", "Nero", "Light Fixture",
        "Test Kit", "Seaweed",
    ],
}

# Expected keep/drop counts on the LOCKED 2026-06-28 fixture (939 rows). Exactly 51
# rows drop (the non-coral tail); every coral — including the 13 no-tag DOOR BUSTER
# rows — survives. Any allowlist regression that drops coral, or a denylist that
# false-fires on a coral title, moves these counts.
EXPECTED_TOTAL = 939
EXPECTED_KEPT = 888
EXPECTED_DROPPED = EXPECTED_TOTAL - EXPECTED_KEPT  # 51; derived so a re-pin can't desync it

# The exact 51-row non-coral tail (the only drops on the locked fixture).
DROPPED_TITLES = {
    "'-NP Pro Liquid Bacterial Growth Polymer - 50ml",
    "AF Amino Mix Amino Acids - 50ml",
    "AF Build Coral Growth Enhancement - 50ml",
    "AF Energy Growth Acceleration Food - 50ml",
    "AF Growth Boost Amino Acids - 35g",
    "AF Liquid Mysis - 250ml",
    "AF Liquid Vege - 250ml",
    "AF Phyto Mix - 250ml",
    "AF Power Elixir - 200ml",
    "AF Power Food - 20g",
    "AI Hydra 32 HD LED Reef Light - Black Body",
    "AI Hydra 32 HD LED Reef Light - White Body",
    "AI NERO 5",
    "BioDigest Live Bacteria",
    "CORAL GLUE GEL - 20 GRAM",
    "CORAL STOP CIRCLE LOGO LEATHER PATCH HAT",
    "CORAL STOP LOGO AQUARIUM TOWEL",
    "CORAL STOP LOGO BUCKET HAT",
    "CORAL STOP RETRO LOGO T-SHIRT",
    "Ca Plus Calcium Supplement - 250ml",
    "Calcium Dry Powder - 850g",
    "Coral Stop Gift Card",
    "EcoTech Marine 4-Pack of Versa Dosing Pumps with Base Station",
    "EcoTech Marine VorTech MP10W",
    "EcoTech Marine VorTech MP40W",
    "EcoTech Marine VorTech MP60W",
    "Green Sea Veggies Seaweed Sheets - 30g",
    "KH Buffer Dry Powder - 1200g",
    "KH Plus Alkalinity Supplement - 250ml",
    "Lugol's Solution - Advanced Iodine - 30ml",
    "Magnesium Dry Powder - 750g",
    "Mg Plus Magnesium Supplement - 250ml",
    "Polyp Lab Polyp-Booster",
    "Potassium Chloride Coral Dip Powder – 250g (USP Grade)",
    "Premium Ceramic Coral Frag Plugs – 10 Pack",
    "Premium Ceramic Square Frag Plate - 3 Pack",
    "Pro Bio S Probiotic Bacteria - 50ml",
    "Purple Sea Veggies Seaweed Sheets - 30g",
    "RADION G6 XR15 BLUE LED LIGHT FIXTURE - ECOTECH MARINE",
    "RADION G6 XR15 PRO LED LIGHT FIXTURE - ECOTECH MARINE",
    "RADION G6 XR30 BLUE LED LIGHT FIXTURE - ECOTECH MARINE",
    "RADION G6 XR30 PRO LED LIGHT FIXTURE - ECOTECH MARINE",
    "Red Sea Veggies Seaweed - 30g",
    "Reef-Roids Nano",
    "SHIPPING MODULE",
    "Salifert Calcium Aquarium Test Kit",
    "Salifert Magnesium Aquarium Test Kit",
    "Salifert kH/Alkalinity Aquarium Test Kit",
    "VECTRA L2 RETURN PUMP",
    "VECTRA M2 RETURN PUMP",
    "VECTRA S2 RETURN PUMP",
}

# Coverage-floor decision (CTK-209): after the fox-coral fold, infer_category leaves
# exactly TWO KEPT rows NULL on the locked fixture — both genus-less DOOR BUSTER
# trade names. 2/888 = 0.23%, far under the 10% pre-flight threshold, so
# _CATEGORY_PATTERNS is NOT edited for them. (Before the fold it was 3/888 = 0.34%;
# "Baby Fox Coral" was the third, now lps.)
COVERAGE_NULL_THRESHOLD_PCT = 10.0
EXPECTED_NULL_TITLES = {
    "GONZO GOLD DRAGON BOUNCE - DOOR BUSTER",
    "BLUE RAVEN MERLETTI - DOOR BUSTER",
}
EXPECTED_NULL_KEPT_COUNT = 2

# A coral title with image + price that exercises the CTK-209 fox-coral lps fold in
# one anchor (Nemenzophyllia turbida, the Coral Stop "Baby Fox Coral").
CORAL_ANCHOR = "Baby Fox Coral"


def _tag_denylist_norm() -> set[str]:
    """Mirror the production hoist in fetch_and_parse: normalize the YAML
    tag_denylist into the set _should_keep consumes. Coral Stop carries no
    tag_denylist, so this is the empty set — the tag axis is structurally inert
    here. Kept for production-call parity."""
    return {_normalize_tag(e) for e in (CORALSTOP_CATEGORY_FILTER.get("tag_denylist") or [])}


def _keep(p: dict) -> bool:
    """_should_keep called exactly as production does — category_filter +
    in_stock_only=False (Coral Stop has no in_stock_only) + the normalized
    tag_denylist."""
    return _should_keep(p, CORALSTOP_CATEGORY_FILTER, False, _tag_denylist_norm())


def _normalize(p: dict) -> dict:
    return _normalize_product(p, BASE_URL, IMAGE_STRATEGY, ORIGINATOR_PREFIX, AUCTION_DETECTION)


def _load_fixture() -> list[dict]:
    with FIXTURE_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)["products"]


try:
    import pytest
    @pytest.fixture(scope="module")
    def products():
        return _load_fixture()
except ImportError:
    pass


def _by_title(products: list[dict], title: str) -> dict:
    for p in products:
        if p["title"] == title:
            return p
    raise KeyError(f"fixture missing product titled {title!r}")


# Test 1: html_hash sentinel — sorted-keys-of-first-product SHA256
def test_html_hash_first_product_keys(products):
    """Arch §2.6 Shopify variant: hash sorted key set of first product. Matches the
    13-key Shopify-fleet anchor. Sentinel flips only when keys add/remove."""
    first = products[0]
    keys = sorted(first.keys())
    expected_keys = [
        "body_html", "created_at", "handle", "id", "images", "options",
        "product_type", "published_at", "tags", "title", "updated_at",
        "variants", "vendor",
    ]
    assert keys == expected_keys, (
        f"first-product key set drift — expected {expected_keys}, got {keys}"
    )
    # The exact sentinel digest (sha256 of the comma-joined sorted key set) — the
    # production html_hash for the Shopify first_product_keys anchor (arch §2.6),
    # identical to the rest of the Shopify fleet's 13-key shape.
    sha = hashlib.sha256(",".join(keys).encode("utf-8")).hexdigest()
    assert sha == "c94c512f27be051326728462bfaf34b4b4cb3f2595a3eafbe44ba45a672aad70", (
        f"first-product-keys html_hash sentinel drift — got {sha}"
    )


# Test 2: total kept = 888 (939 - the 51-row non-coral tail)
def test_total_kept_is_888(products):
    """Full-catalog keep count on the locked 939-row fixture: 888 kept, 51 dropped.
    With no product_type_allowlist / no tag_allowlist and a title_denylist that hits
    only the non-coral tail, the entire coral catalog (incl. no-tag DOOR BUSTERs)
    survives."""
    assert len(products) == EXPECTED_TOTAL, f"fixture drifted: expected {EXPECTED_TOTAL} rows, got {len(products)}"
    kept = sum(1 for p in products if _keep(p))
    dropped = len(products) - kept
    assert kept == EXPECTED_KEPT, f"expected {EXPECTED_KEPT} kept, got {kept}"
    assert dropped == EXPECTED_DROPPED, f"expected {EXPECTED_DROPPED} dropped, got {dropped}"


# Test 3: the exact non-coral tail drops, nothing else
def test_exact_drop_set(products):
    """The 51 dropped titles are exactly the non-coral tail — no coral collateral.
    Pins the drop set so a denylist coarsening (or a coral title that starts
    matching a denylist term) surfaces loudly. Includes the "Leather Patch Hat"
    apparel row that would otherwise infer softie via \\bleather."""
    dropped = {p["title"] for p in products if not _keep(p)}
    assert dropped == DROPPED_TITLES, (
        f"drop set drifted.\n  unexpected drops: {dropped - DROPPED_TITLES}\n"
        f"  missing drops: {DROPPED_TITLES - dropped}"
    )


# Test 4 (THE CORAL STOP REGRESSION): no-tag DOOR BUSTER corals survive
def test_door_buster_corals_survive(products):
    """The load-bearing Coral Stop regression: "DOOR BUSTER" flash-sale corals carry
    NO 'CORAL' tag and NO product_type. A product_type_allowlist OR tag_allowlist
    would silently drop them. Every DOOR BUSTER row MUST survive; pin the full set +
    assert none drop. If this fails, someone added an allowlist."""
    door = [p for p in products if "door buster" in p["title"].lower()]
    assert len(door) >= 10, (
        f"fixture drift: expected the DOOR BUSTER flash-sale cohort, got {len(door)}"
    )
    dropped = [p["title"] for p in door if not _keep(p)]
    assert dropped == [], (
        f"DOOR BUSTER corals were wrongly dropped (an allowlist was added?): {dropped}"
    )
    # Isolate the axis: a no-tag, blank-product_type DOOR BUSTER coral survives.
    assert _keep({"title": "MYSTERY RAINBOW ACRO - DOOR BUSTER", "product_type": "", "tags": []}) is True


# Test 5: a feed-relabeled / never-before-seen product_type AND a no-tag row survive
def test_no_allowlist_feed_relabel_survives(products):
    """The feed-relabel + no-tag guard. Under the no-allowlist decision, a
    never-before-seen product_type (a relabel to a Google category) AND a no-tag row
    MUST survive — exactly what a product_type_allowlist or tag_allowlist would
    silently drop. If this starts failing, someone added an allowlist (the CTK-209
    #1 regression)."""
    relabeled = {
        "title": "Rainbow Splice Acro",
        "product_type": "Animals & Pet Supplies > Pet Supplies > Fish Supplies",
        "tags": [],
    }
    assert _keep(relabeled) is True, (
        "a feed-relabeled coral was dropped — a product_type_allowlist must have "
        "been added; that silently drops the catalog on a feed relabel (CTK-209 #1)"
    )
    no_tag = {"title": "Coral Stop Mystery Zoa", "product_type": "", "tags": []}
    assert _keep(no_tag) is True, "a no-tag coral was dropped — a tag_allowlist was added (CTK-209 #1)"


# Test 6 (CTK-209 FOLD): fox-coral classifies lps
def test_fox_coral_classifies_lps(products):
    """The CTK-209 fox-coral lps fold (Nemenzophyllia turbida). "Baby Fox Coral" was
    a kept-but-NULL row before the fold; now lps. Pins the new token AND the
    critical FP boundary: the token is the PHRASE "fox coral", never bare "fox"
    (which collides with the Jason Fox vendor across hundreds of unrelated titles)."""
    p = _by_title(products, "Baby Fox Coral")
    assert infer_category(p) == "lps"
    # FP boundary — bare "Fox" must NOT force lps; a real "Jason Fox" SPS stays sps.
    assert infer_category({"title": "Jason Fox Acropora", "product_type": "", "tags": []}) == "sps"
    assert infer_category({"title": "JF Fox Flame Zoa", "product_type": "", "tags": []}) == "zoa"


# Test 7: denylist specificity — multiword entries don't coarsen into coral words
def test_denylist_specificity(products):
    """The denylist's multiword entries are deliberately narrow. "Frag Plug"/"Frag
    Plate" must NOT touch a bare-"Frag" coral; "Booster" (Polyp-Booster food) must
    NOT become bare "Polyp" (a coral word). Pin both with synthetic rows since the
    locked catalog happens to carry no bare-"Frag"/"Polyp" coral titles today."""
    # Real non-coral hardware drops...
    assert _keep({"title": "Premium Ceramic Coral Frag Plugs - 10 Pack", "product_type": "", "tags": []}) is False
    assert _keep({"title": "Premium Ceramic Square Frag Plate - 3 Pack", "product_type": "", "tags": []}) is False
    assert _keep({"title": "Polyp Lab Polyp-Booster", "product_type": "", "tags": []}) is False
    # ...but the same-rooted corals survive (bare "Frag" / bare "Polyp" not denied).
    assert _keep({"title": "Rainbow Acro Frag", "product_type": "", "tags": []}) is True
    assert _keep({"title": "Green Star Polyps", "product_type": "", "tags": []}) is True


# Test 8: the leather "Patch Hat" apparel drops (the \bleather -> softie FP)
def test_leather_patch_hat_drops(products):
    """infer_category mis-buckets "...LEATHER PATCH HAT" as softie via \\bleather.
    The "Patch Hat" title_denylist entry drops it before it can show as a softcoral.
    Pin both the real row drop and the isolated mechanism."""
    assert _keep(_by_title(products, "CORAL STOP CIRCLE LOGO LEATHER PATCH HAT")) is False
    # A real leather-toadstool coral must NOT be collateral (no "Patch Hat" substring).
    assert _keep({"title": "Toadstool Leather Coral", "product_type": "", "tags": []}) is True


# Test 9: no auction null-out — INV-05 not triggered at the normalize layer
def test_normalize_no_auction_nulling(products):
    """coralstop.yaml carries no auction_detection (AUCTION_DETECTION=None), so coral
    normalizes with is_auction=False and keeps its real price — including the
    fixed-price DOOR BUSTER flash-sale rows. Pins the INV-05-not-triggered decision
    at the _normalize_product layer."""
    p = _by_title(products, CORAL_ANCHOR)
    norm = _normalize(p)
    assert norm["is_auction"] is False
    assert norm["current_price"] is not None, "non-auction coral price must not be nulled"


# Test 10: _normalize_product output shape — coral product
def test_normalize_output_shape(products):
    """_normalize_product on a coral — validates output dict shape per arch §1.4
    vendor_listings columns + absolute product_url (CTK-033 D1)."""
    p = _by_title(products, CORAL_ANCHOR)
    norm = _normalize(p)
    assert norm["raw_title"] == CORAL_ANCHOR
    assert norm["product_url"].startswith("https://coralstop.com/products/")
    assert norm["currency"] == "USD"
    assert norm["vendor_image_url"] is not None
    assert "cdn.shopify.com" in norm["vendor_image_url"]
    # CTK-209 fold: "Baby Fox Coral" -> lps via the new \bfox\s+corals?\b token.
    assert infer_category(p) == "lps"


# Test 11: coverage floor — NULL-category ratio over the KEPT set under threshold
def test_category_coverage_floor(products):
    """CTK-209 coverage decision: over the KEPT set (the production parser output),
    infer_category leaves exactly TWO rows NULL after the fox-coral fold — both
    genus-less DOOR BUSTER trade names ('Gonzo Gold Dragon Bounce', 'Blue Raven
    Merletti'). 2/888 = 0.23% < 10% threshold, so _CATEGORY_PATTERNS is NOT edited
    for them. Pins the decision + the exact NULL set (a different NULL row appearing
    is a coverage regression)."""
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


# Test 12 (MIRROR-PARITY, CTK-115): in-test filter == coralstop.yaml byte-exact
def test_yaml_mirror_parity():
    """CTK-115 mirror-parity: the in-test CORALSTOP_CATEGORY_FILTER must equal the
    scrapers/vendors/coralstop.yaml category_filter byte-exact, the YAML must carry
    NO product_type_allowlist AND NO tag_allowlist (the load-bearing CTK-209 #1
    absences), NO auction_detection block (INV-05 not triggered), and NO
    in_stock_only.

    The keys-exact assertion is load-bearing: this test (and _keep()) model only the
    single axis Coral Stop uses today (title_denylist) with in_stock_only=False. If a
    future maintainer adds product_type_allowlist or tag_allowlist (the regressions
    this ticket exists to prevent — they would silently zero the catalog on a feed
    relabel / drop the no-tag DOOR BUSTERs), the locked-fixture keep count would NOT
    reflect it and the suite would stay green against diverged production behavior.
    So we fail loudly the moment the YAML's filter-axis set — or the in_stock_only
    flag — drifts from what this test models."""
    cfg = yaml.safe_load(YAML_PATH.read_text(encoding="utf-8"))
    yaml_filter = cfg["category_filter"]
    assert yaml_filter.get("title_denylist", []) == CORALSTOP_CATEGORY_FILTER["title_denylist"], (
        "title_denylist drift between coralstop.yaml and the test mirror"
    )
    assert "product_type_allowlist" not in yaml_filter, (
        "coralstop.yaml grew a product_type_allowlist — that is the CTK-209 #1 "
        "regression (silent catalog-zeroing on a feed relabel). Re-walk + re-decide."
    )
    assert "tag_allowlist" not in yaml_filter, (
        "coralstop.yaml grew a tag_allowlist — rejected per CTK-209 #1 (would drop "
        "the no-tag DOOR BUSTER corals)"
    )
    assert set(yaml_filter.keys()) == set(CORALSTOP_CATEGORY_FILTER.keys()), (
        f"coralstop.yaml category_filter grew/changed an axis the test mirror "
        f"doesn't model: YAML={sorted(yaml_filter.keys())} vs "
        f"mirror={sorted(CORALSTOP_CATEGORY_FILTER.keys())} — extend "
        f"CORALSTOP_CATEGORY_FILTER + _keep()"
    )
    assert "in_stock_only" not in cfg, (
        "coralstop.yaml set in_stock_only — _keep() hardcodes False and the locked "
        "count would no longer reflect production; thread it through the test"
    )
    assert cfg.get("auction_detection") is None, (
        "coralstop.yaml grew an auction_detection block — INV-05 disposition changed; "
        "re-confirm the walk + update this test mirror"
    )


def main() -> int:
    products = _load_fixture()
    no_param = {test_yaml_mirror_parity}
    tests = [
        test_html_hash_first_product_keys,
        test_total_kept_is_888,
        test_exact_drop_set,
        test_door_buster_corals_survive,
        test_no_allowlist_feed_relabel_survives,
        test_fox_coral_classifies_lps,
        test_denylist_specificity,
        test_leather_patch_hat_drops,
        test_normalize_no_auction_nulling,
        test_normalize_output_shape,
        test_category_coverage_floor,
        test_yaml_mirror_parity,
    ]
    failed = 0
    for t in tests:
        try:
            t() if t in no_param else t(products)
            print(f"PASS  {t.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL  {t.__name__}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
