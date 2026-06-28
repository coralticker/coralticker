"""scrapers/tests/test_austinaquafarms_parse.py — CTK-149 parse-layer tests for
Austin Aqua Farms's Shopify /products.json shape against locked fixture
scrapers/tests/fixtures/austinaquafarms/products.sample.json.

Parse-only — no DB, no network. Validates parse_shopify._normalize_product output
shape + html_hash sentinel + the NO-ALLOWLIST category_filter that makes Austin
Aqua Farms a no-product_type_allowlist vendor (the second after Reef Regeneration).

WHY THIS TEST EXISTS (the regression it pins):
AAF's product_type is NOT a coral taxonomy and NOT a coral/non-coral
discriminator. The Session-1 full-catalog walk (2026-06-28, the full catalog
locked as this fixture, 2303 rows across 10 pages — NOT a page-1 sample, per
feedback_absence_diag_full_catalog_sweep) found just THREE product_type buckets:
    '' (empty)               = 2177   coral
    'Animals & Pet Supplies' =  125   ALL CORAL (torches, mushrooms, euphyllia) —
                                       a GOOGLE-MERCHANT-FEED taxonomy value AAF's
                                       feed app stamps on coral, NOT a non-coral
                                       signal.
    'Gift Cards'             =    1   the ONLY non-coral row in 2303.

The pre-flight (page-1 only) read "Animals & Pet Supplies" as non-coral; the full
walk shows it is 125 real coral. So the decision (CTK-149 #1, Jon-ratified
2026-06-28) is NO product_type_allowlist at all, sharpened past Reef
Regeneration's CTK-148 #1 by AAF's FEED-RELABEL mode: the "Animals & Pet Supplies"
values are a Google Shopping feed-app output that can relabel product_type
catalog-wide at any time. Under a product_type_allowlist a feed relabel would
silently drop the ENTIRE 2300-coral catalog to zero coverage (the allowlist-miss
WARN is in_stock_only-gated, which AAF doesn't set). Under no-allowlist a PT
relabel is a no-op. The only gate is the single gift card by title +
a chaeto/macroalgae title_denylist forward-bind.

Three regressions a future "tidy" would silently cause, all caught here:
  - Treating 'Animals & Pet Supplies' as non-coral (an allowlist of [''] or a
    product_type drop) silently loses 125 real coral —
    test_animals_pet_supplies_bucket_all_survive pins every APS row survives.
  - Adding ANY product_type_allowlist silently drops the next feed-relabeled or
    new product_type — test_no_allowlist_feed_relabel_survives pins a
    never-before-seen product_type survives.
  - Coarsening / dropping the chaeto/macroalgae forward-bind (AAF's only junk gate
    besides the gift card) — test_chaeto_macroalgae_forward_bind pins it fires on
    synthetic macroalgae while leaving all 2302 kept coral rows.

INV-05 is NOT triggered: the full-catalog walk found zero auction signal (no
wk_end_auction/auc/bid tags, no product_type:Auction, no 'auction' in any
title/handle). austinaquafarms.yaml carries no auction_detection block;
test_yaml_mirror_parity pins that absence so a future block can't land unmirrored.

Mirror-parity (CTK-115 convention): test loads scrapers/vendors/
austinaquafarms.yaml and asserts the in-test AAF_CATEGORY_FILTER equals the YAML
block byte-exact, AND that the YAML carries NO product_type_allowlist and NO
tag_allowlist (the load-bearing absences) — either landing later fails
test_yaml_mirror_parity loudly.

Runnable as:
  python -m scrapers.tests.test_austinaquafarms_parse

Fixture regen path: re-walk austinaquafarms.com/products.json?limit=250&page=N
for N=1.. until a short page (the Session-1 walk shape: 10 pages, 2303 rows) and
re-dump the concatenated {"products": [...]} payload. NOTE: re-pinning will move
the kept count + the bucket inventory as the live catalog drifts — update
EXPECTED_TOTAL/EXPECTED_KEPT, the APS-bucket count guard, and the coverage-floor
NULL rows to match the new snapshot. This is the fleet's deepest catalog
(multi-page), so a re-walk MUST page to the short-page terminator, not stop at
page 1.
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


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "austinaquafarms" / "products.sample.json"
YAML_PATH = Path(__file__).parent.parent / "vendors" / "austinaquafarms.yaml"
BASE_URL = "https://austinaquafarms.com"
ORIGINATOR_PREFIX = None  # CTK-149 — null (no AAF-attributed seed-list canonicals)
IMAGE_STRATEGY = "mirror"
AUCTION_DETECTION = None   # CTK-149 — INV-05 not triggered; no auction_detection block in the YAML

# Hand-mirror of scrapers/vendors/austinaquafarms.yaml category_filter — kept
# byte-exact with the YAML; test_yaml_mirror_parity asserts the equality so a
# YAML amendment that isn't mirrored here fails loudly (CTK-115 drift class).
# NOTE the deliberate ABSENCE of product_type_allowlist AND tag_allowlist — AAF
# is a no-allowlist vendor (CTK-149 #1). Only the gift card + chaeto/macroalgae
# forward-bind are denied, all by title.
AAF_CATEGORY_FILTER = {
    "title_denylist": ["Gift Card", "Chaeto", "Cheato", "Macroalgae", "Macro Algae", "Macro-Algae"],
}

# Expected keep/drop counts on the LOCKED 2026-06-28 fixture (2303 rows). Exactly
# ONE row drops (the gift card); the chaeto/macroalgae forward-bind fires on ZERO
# real rows (AAF stocks no macroalgae today). Any allowlist regression that drops
# coral, or a denylist that false-fires on a coral title, moves these counts.
EXPECTED_TOTAL = 2303
EXPECTED_KEPT = 2302
EXPECTED_DROPPED = 1

# The catalog's ONE non-coral row — drops by the "Gift Card" title entry (it
# carries ZERO tags, so a tag axis is inert; title-only).
GIFT_CARD_TITLE = "Austin Aqua Farms Gift Card"

# The 'Animals & Pet Supplies' product_type bucket — a Google-merchant-feed value
# AAF stamps on 125 REAL CORAL rows. Treating it as non-coral (the pre-flight's
# page-1 misread) would drop 125 coral. This count guards the bucket.
APS_BUCKET = "Animals & Pet Supplies"
APS_BUCKET_COUNT = 125

# Coverage-floor decision (CTK-149): infer_category leaves exactly TWO KEPT rows
# NULL on the locked fixture — both the genus-less "Australian Premium
# Balanophyllia" trade name (zero-tagged). 2/2302 = 0.09%, far under the 10%
# pre-flight threshold, so _CATEGORY_PATTERNS is NOT edited for it (Williamson's /
# RR one-off precedent). Computed over the KEPT set (the production parser output),
# NOT all rows — the gift card is also NULL-category but it is DROPPED, so it never
# reaches the classifier in production.
COVERAGE_NULL_THRESHOLD_PCT = 10.0
EXPECTED_NULL_TITLE = "Australian Premium Balanophyllia"
EXPECTED_NULL_KEPT_COUNT = 2

# A unique coral title in the '' bucket with an image + price — the normalize
# shape + no-auction anchors.
CORAL_ANCHOR = "Indonesian Premium Lemon Pepper Fungia"


def _tag_denylist_norm() -> set[str]:
    """Mirror the production hoist in fetch_and_parse: normalize the YAML
    tag_denylist into the set _should_keep consumes as its 4th positional arg.
    AAF carries no tag_denylist, so this is the empty set — the tag axis is
    structurally inert here (the gift card has no tags). Kept for production-call
    parity."""
    return {_normalize_tag(e) for e in (AAF_CATEGORY_FILTER.get("tag_denylist") or [])}


def _keep(p: dict) -> bool:
    """_should_keep called exactly as production does — category_filter +
    in_stock_only=False (AAF has no in_stock_only) + the normalized tag_denylist."""
    return _should_keep(p, AAF_CATEGORY_FILTER, False, _tag_denylist_norm())


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
    """Arch §2.6 Shopify variant: hash sorted key set of first product. Matches
    the 13-key Shopify-fleet anchor. Sentinel flips only when keys add/remove."""
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
    sha = hashlib.sha256(",".join(keys).encode("utf-8")).hexdigest()
    assert len(sha) == 64


# Test 2: total kept = 2302 (2303 - the 1 gift card)
def test_total_kept_is_2302(products):
    """Full-catalog keep count on the locked 2303-row fixture: 2302 kept, 1
    dropped (the gift card). With no product_type_allowlist and a chaeto/macroalgae
    forward-bind that matches zero real rows, the entire coral catalog survives and
    only the lone non-coral row drops. Any allowlist regression that drops coral,
    or a denylist that false-fires on a coral title, moves these counts."""
    assert len(products) == EXPECTED_TOTAL, f"fixture drifted: expected {EXPECTED_TOTAL} rows, got {len(products)}"
    kept = sum(1 for p in products if _keep(p))
    dropped = len(products) - kept
    assert kept == EXPECTED_KEPT, f"expected {EXPECTED_KEPT} kept, got {kept}"
    assert dropped == EXPECTED_DROPPED, f"expected {EXPECTED_DROPPED} dropped, got {dropped}"


# Test 3: the lone non-coral row (gift card) drops via the title axis
def test_gift_card_dropped_by_title(products):
    """AAF's ONLY non-coral row in 2303 is the gift card. It carries ZERO tags
    (so a tag_denylist would be inert) and drops via the "Gift Card" title entry
    alone. A synthetic gift card with an innocuous-but-denied title still drops;
    the same shape without 'gift card' in the title survives — isolating the
    title axis as the sole mechanism."""
    real = _by_title(products, GIFT_CARD_TITLE)
    assert not (real.get("tags") or []), "fixture drift: the gift card gained tags (re-confirm the tag axis is still inert)"
    assert _keep(real) is False, "the gift card should have dropped via the 'Gift Card' title entry"

    # Isolate the title axis: an allowlisted-PT row with a denied title drops; the
    # same row with a clean title survives.
    denied = {"title": "Reef Store Gift Card", "product_type": "", "tags": []}
    assert _keep(denied) is False, "'Gift Card' title entry not firing"
    control = {"title": "Australian Premium Holy Grail Torch", "product_type": "Gift Cards", "tags": []}
    assert _keep(control) is True, (
        "FP control: a coral with a non-denied title must survive even with a "
        "'Gift Cards' product_type — PT is ungated (no-allowlist), so the bucket "
        "name alone never drops a row"
    )


# Test 4 (THE AAF REGRESSION, part A): the 125-row 'Animals & Pet Supplies'
# bucket is coral and MUST fully survive
def test_animals_pet_supplies_bucket_all_survive(products):
    """The load-bearing AAF regression: 'Animals & Pet Supplies' is a
    Google-merchant-feed product_type AAF stamps on 125 REAL CORAL rows (torches,
    mushrooms, euphyllia), NOT a non-coral signal. The pre-flight's page-1 sample
    misread it as non-coral. Every APS-bucket row MUST survive — a future 'tidy'
    that treats APS as non-coral (a product_type drop, or an allowlist of ['']
    that excludes APS) would silently lose all 125 coral. If this test fails,
    someone treated the Google-feed taxonomy value as a junk signal."""
    aps = [p for p in products if (p.get("product_type") or "") == APS_BUCKET]
    assert len(aps) == APS_BUCKET_COUNT, (
        f"fixture drift: expected {APS_BUCKET_COUNT} 'Animals & Pet Supplies' rows, got {len(aps)}"
    )
    dropped = [p["title"] for p in aps if not _keep(p)]
    assert dropped == [], (
        f"'Animals & Pet Supplies' is a coral bucket — these were wrongly dropped "
        f"(treated as non-coral?): {dropped}"
    )


# Test 5 (THE AAF REGRESSION, part B): a feed-relabeled / never-before-seen
# product_type survives
def test_no_allowlist_feed_relabel_survives(products):
    """The feed-relabel catastrophe guard. AAF's product_type is a Google
    Shopping feed-app output that can relabel catalog-wide at any time. Under the
    no-allowlist decision, a never-before-seen product_type (a relabel to a more
    specific Google category, or a new bucket) MUST survive — a synthetic coral
    with a brand-new product_type and a clean title is kept. This is exactly what
    a product_type_allowlist would silently drop catalog-wide on a feed relabel.
    If this test starts failing, someone added an allowlist; that is the CTK-149
    #1 regression."""
    relabeled = {
        "title": "Australian Premium Rainbow Acan",
        "product_type": "Animals & Pet Supplies > Pet Supplies > Fish Supplies",  # a more specific Google category string
        "tags": ["acans", "LPS Coral"],
    }
    assert _keep(relabeled) is True, (
        "a feed-relabeled coral was dropped — a product_type_allowlist must have "
        "been added; that silently drops the catalog on a feed relabel (CTK-149 #1)"
    )
    # And a wholly novel non-Google bucket survives too.
    novel = {"title": "Aquacultured Premium Mystery Coral", "product_type": "BrandNewBucket", "tags": []}
    assert _keep(novel) is True, "a novel product_type bucket was dropped — no-allowlist violated"


# Test 6: chaeto/macroalgae forward-bind fires on synthetic, no-op on real catalog
def test_chaeto_macroalgae_forward_bind(products):
    """Besides the gift card, AAF's only junk gate is the chaeto/macroalgae
    title_denylist forward-bind. On the locked catalog it matches ZERO rows (AAF
    stocks no macroalgae) — pure forward-bind. Pin that it WOULD fire on synthetic
    macroalgae rows (so a future leak is caught) while a control coral survives,
    and confirm the only real-catalog drop is the gift card (no macroalgae
    false-fire on coral)."""
    for junk_title in [
        "Premium Chaetomorpha Algae Ball",   # 'Chaeto' substring
        "Cheato Macro Refugium Starter",     # 'Cheato' misspelling
        "Mixed Macroalgae Pack",             # 'Macroalgae'
        "Refugium Macro Algae Bundle",       # 'Macro Algae'
        "Display Macro-Algae Cluster",       # 'Macro-Algae' hyphen variant
    ]:
        junk = {"title": junk_title, "product_type": "", "tags": []}
        assert _keep(junk) is False, f"macroalgae forward-bind failed to drop: {junk_title!r}"

    # A control coral with an innocuous title survives the denylist.
    control = {"title": "Indonesian Premium Sun God Torch", "product_type": "", "tags": ["euphyllia"]}
    assert _keep(control) is True, "FP control: a coral with no denied substring must survive"

    # The only real-catalog drop is the gift card — the chaeto entries false-fire
    # on zero coral rows.
    dropped = [p["title"] for p in products if not _keep(p)]
    assert dropped == [GIFT_CARD_TITLE], (
        f"unexpected real-catalog drops (chaeto forward-bind false-firing on coral?): {dropped}"
    )


# Test 7: no auction null-out — INV-05 not triggered at the normalize layer
def test_normalize_no_auction_nulling(products):
    """austinaquafarms.yaml carries no auction_detection (AUCTION_DETECTION=None),
    so coral normalizes with is_auction=False and keeps its real price — no
    collateral null-out. Pins the INV-05-not-triggered decision at the
    _normalize_product layer."""
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
    assert norm["product_url"].startswith("https://austinaquafarms.com/products/")
    assert norm["currency"] == "USD"
    assert norm["vendor_image_url"] is not None
    assert "cdn.shopify.com" in norm["vendor_image_url"]


# Test 9: coverage floor — NULL-category ratio over the KEPT set under threshold
def test_category_coverage_floor(products):
    """CTK-149 coverage decision: over the KEPT set (the production parser output,
    NOT all rows — the gift card is NULL-category but DROPPED), infer_category
    leaves exactly TWO rows NULL, both the genus-less 'Australian Premium
    Balanophyllia' trade name. 2/2302 = 0.09% < 10% threshold, so
    _CATEGORY_PATTERNS is NOT edited for it. This pins the decision: if a future
    _CATEGORY_PATTERNS change pushes AAF's NULL ratio over threshold, this fails
    and forces a conscious re-look. Also asserts the lone NULL title is Balanophyllia
    (a different NULL row appearing is a coverage regression)."""
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
    assert set(null_titles) == {EXPECTED_NULL_TITLE}, (
        f"NULL-category set drifted — expected only {EXPECTED_NULL_TITLE!r}, got {set(null_titles)}"
    )


# Test 10 (MIRROR-PARITY, CTK-115): in-test filter == austinaquafarms.yaml byte-exact
def test_yaml_mirror_parity():
    """CTK-115 mirror-parity: the in-test AAF_CATEGORY_FILTER must equal the
    scrapers/vendors/austinaquafarms.yaml category_filter byte-exact, the YAML
    must carry NO product_type_allowlist AND NO tag_allowlist (the load-bearing
    CTK-149 #1 absences), NO auction_detection block (INV-05 not triggered), and
    NO in_stock_only.

    The keys-exact assertion is load-bearing: this test (and _keep()) model only
    the single axis AAF uses today (title_denylist) with in_stock_only=False. If a
    future maintainer adds product_type_allowlist (the exact regression this ticket
    exists to prevent — it would silently zero the catalog on a feed relabel),
    tag_allowlist, or any other axis, the locked-fixture keep count would NOT
    reflect it and the suite would stay green against diverged production behavior.
    So we fail loudly the moment the YAML's filter-axis set — or the in_stock_only
    flag — drifts from what this test models."""
    cfg = yaml.safe_load(YAML_PATH.read_text(encoding="utf-8"))
    yaml_filter = cfg["category_filter"]
    assert yaml_filter.get("title_denylist", []) == AAF_CATEGORY_FILTER["title_denylist"], (
        "title_denylist drift between austinaquafarms.yaml and the test mirror"
    )
    # The load-bearing absences: NO product_type_allowlist, NO tag_allowlist (CTK-149 #1).
    assert "product_type_allowlist" not in yaml_filter, (
        "austinaquafarms.yaml grew a product_type_allowlist — that is the CTK-149 #1 "
        "regression (silent catalog-zeroing on a Google-feed relabel). Re-walk + re-decide."
    )
    assert "tag_allowlist" not in yaml_filter, (
        "austinaquafarms.yaml grew a tag_allowlist — it would drop the 2 zero-tag "
        "Balanophyllia corals; rejected per CTK-149 #1"
    )
    # Keys-exact: no unmodeled filter axis may appear.
    assert set(yaml_filter.keys()) == set(AAF_CATEGORY_FILTER.keys()), (
        f"austinaquafarms.yaml category_filter grew/changed an axis the test mirror "
        f"doesn't model: YAML={sorted(yaml_filter.keys())} vs "
        f"mirror={sorted(AAF_CATEGORY_FILTER.keys())} — extend AAF_CATEGORY_FILTER + _keep()"
    )
    assert "in_stock_only" not in cfg, (
        "austinaquafarms.yaml set in_stock_only — _keep() hardcodes False and the "
        "locked count would no longer reflect production; thread it through the test"
    )
    assert cfg.get("auction_detection") is None, (
        "austinaquafarms.yaml grew an auction_detection block — INV-05 disposition changed; "
        "re-confirm the walk + update this test mirror"
    )


def main() -> int:
    products = _load_fixture()
    no_param = {test_yaml_mirror_parity}
    tests = [
        test_html_hash_first_product_keys,
        test_total_kept_is_2302,
        test_gift_card_dropped_by_title,
        test_animals_pet_supplies_bucket_all_survive,
        test_no_allowlist_feed_relabel_survives,
        test_chaeto_macroalgae_forward_bind,
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
