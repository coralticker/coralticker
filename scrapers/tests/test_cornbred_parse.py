"""scrapers/tests/test_cornbred_parse.py — CTK-142 Session 2 parse-layer tests
for Cornbred Corals' Shopify /products.json shape against locked fixture
scrapers/tests/fixtures/cornbred/products.sample.json.

Parse-only — no DB, no network. Validates parse_shopify._normalize_product
output shape + html_hash sentinel + the product_type_allowlist category_filter
behavior (Battlecorals mechanism) + the wk_end_auction null-price/is_auction
writer-side obligation (CTK-041/CTK-160).

Cornbred is a product_type-allowlist vendor (taxonomy in product_type, sparse
non-coral tags). CRITICAL divergence from Battlecorals: Cornbred's empty ''
product_type bucket is NOT coral (livestock fish + CUC inverts + 1 merch
poster, 99 rows at the Session 1 walk) — empty is DROPPED, not allowlisted.

Fixture (6 curated rows pinned from the live /products.json?limit=250 on
2026-06-20 — NOT the per-product endpoint, which returns available:null for
auction rows per the results.md endpoint-quirk note):
  - Cornbred's Utter Chaos Paly - WYSIWYG  PT='Paly' (allowlisted) coral KEEP;
    canonical Cornbred house lineage
  - Cornbred's Blue Stripe Duncan          PT='Other' (allowlisted catch-all)
    coral KEEP — the Other-bucket-is-coral case
  - Sailfin Tang                           PT='' empty bucket → fish REJECT
  - Cornbred Bloodshot Krak Sticker        PT='Sticker' → merch REJECT
  - Cornbred Corals GIFT CARD              PT='Gift Card' → merch REJECT
  - Cornbred's Red Queen Blasto - WYSIWYG  PT='Blasto' (allowlisted), tags
    ['wk_end_auction'], price 39.99 → KEEP but current_price NULL + is_auction
    true (the writer-side obligation; price 39.99 must NOT write through)

The auction test asserts current_price is None THROUGH the real
_normalize_product call with the real auction_detection — so deleting the
null-price branch (_normalize_product L586-589) FAILS this test (the guarantee
is exercised, not merely co-incidentally satisfied, per
feedback_review_results_test_exercises_guarantee).

Mirror-parity (CTK-115 convention): test loads scrapers/vendors/cornbred.yaml
and asserts the in-test CORNBRED_CATEGORY_FILTER + AUCTION_DETECTION equal the
YAML blocks byte-exact — a YAML allowlist/denylist amendment that isn't
mirrored here fails test_yaml_mirror_parity.

Runnable as:
  python -m scrapers.tests.test_cornbred_parse

Fixture regen path: re-fetch cornbredcorals.com/products.json?limit=250 and
re-pin the 6 representative rows (the script shape used at CTK-142 Session 2).
"""

from __future__ import annotations

import hashlib
import json
import sys
import traceback
from pathlib import Path

import yaml

from scrapers.common.parse_shopify import (
    _is_auction,
    _normalize_product,
    _should_keep,
    _should_keep_with_auction_override,
)


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "cornbred" / "products.sample.json"
YAML_PATH = Path(__file__).parent.parent / "vendors" / "cornbred.yaml"
BASE_URL = "https://cornbredcorals.com"
ORIGINATOR_PREFIX = None  # CTK-142 — null per seed-list absence (no Cornbred-attributed canonicals)
IMAGE_STRATEGY = "mirror"

# Hand-mirror of scrapers/vendors/cornbred.yaml category_filter — kept
# byte-exact with the YAML; test_yaml_mirror_parity asserts the equality so a
# YAML amendment that isn't mirrored here fails loudly (CTK-115 drift class).
CORNBRED_CATEGORY_FILTER = {
    "product_type_allowlist": [
        "Other", "Paly", "Chalice", "Acro", "Mushroom", "Favia", "Zoa",
        "Monti", "Milli", "Lepto", "Anemone", "Cyphastrea", "Echinata",
        "Torch", "Birdsnest", "Blasto", "Hammer", "Pectinia", "Acan",
        "Galaxia", "Leather", "Goniopora", "Diaseris", "Psammacora", "Stylo",
        "Digi", "Lobo", "Maze Brain", "Frogspawn", "Hydno", "Nem", "Anacro",
        "Bowerbanki", "Gonipora", "Grandis", "Leptastrea", "Octospawn",
        "Pavona", "Plate", "Scroll",
    ],
    "tag_denylist": [],
    "title_denylist": ["Chaeto", "Cheato", "Macroalgae", "Macro Algae"],
}
AUCTION_DETECTION = {"tags": ["wk_end_auction"]}


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


def _normalize(p: dict) -> dict:
    return _normalize_product(p, BASE_URL, IMAGE_STRATEGY, ORIGINATOR_PREFIX, AUCTION_DETECTION)


# Test 1: html_hash sentinel — sorted-keys-of-first-product SHA256
def test_html_hash_first_product_keys(products):
    """Arch §2.6 Shopify variant: hash sorted key set of first product.
    Matches the 13-key Shopify-fleet anchor. Sentinel flips only when keys
    add/remove."""
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


# Test 2: coral keep — allowlisted non-empty product_type (Paly)
def test_filter_keeps_coral_allowlisted_pt(products):
    """Cornbred's Utter Chaos Paly — product_type='Paly' (allowlisted) →
    keep. Anchor case for the dominant coral buckets; Utter Chaos is a
    canonical Cornbred house lineage."""
    p = _by_title(products, "Cornbred's Utter Chaos Paly - WYSIWYG")
    assert p["product_type"] == "Paly"
    assert _should_keep(p, CORNBRED_CATEGORY_FILTER) is True


# Test 3: Other-bucket coral keep — the 'Other' catch-all is coral
def test_filter_keeps_other_bucket_coral(products):
    """Cornbred's Blue Stripe Duncan — product_type='Other'. Session 1
    resolved the Other bucket 11/11 coral, so 'Other' is allowlisted as
    Cornbred's un-bucketed-genus coral catch-all. Distinct from a generic
    merch 'Other' — verified row-by-row at the 2026-06-20 walk."""
    p = _by_title(products, "Cornbred's Blue Stripe Duncan")
    assert p["product_type"] == "Other"
    assert _should_keep(p, CORNBRED_CATEGORY_FILTER) is True


# Test 4: empty-PT fish reject — the BC divergence (empty '' is NOT coral here)
def test_filter_rejects_empty_pt_fish(products):
    """Sailfin Tang — product_type='' (empty bucket). CRITICAL Cornbred
    divergence from Battlecorals: the empty bucket is livestock fish + CUC
    inverts + merch poster (99 rows at the Session 1 walk), NOT coral. ''
    is NOT in the allowlist → reject. This is the coverage-gap-defense
    anchor: a regression that re-added '' to the allowlist would leak ~99
    fish/invert rows and fail here."""
    p = _by_title(products, "Sailfin Tang")
    assert p["product_type"] == ""
    assert _should_keep(p, CORNBRED_CATEGORY_FILTER) is False


# Test 5: Sticker reject
def test_filter_rejects_sticker(products):
    """Cornbred Bloodshot Krak Sticker — product_type='Sticker' (merch).
    Not allowlisted → reject."""
    p = _by_title(products, "Cornbred Bloodshot Krak Sticker")
    assert p["product_type"] == "Sticker"
    assert _should_keep(p, CORNBRED_CATEGORY_FILTER) is False


# Test 6: Gift Card reject
def test_filter_rejects_gift_card(products):
    """Cornbred Corals GIFT CARD — product_type='Gift Card' (merch). Not
    allowlisted → reject."""
    p = _by_title(products, "Cornbred Corals GIFT CARD")
    assert p["product_type"] == "Gift Card"
    assert _should_keep(p, CORNBRED_CATEGORY_FILTER) is False


# Test 7: wk_end_auction detection fires on the sole auction signal
def test_auction_detected_on_wk_end_auction_tag(products):
    """Cornbred's Red Queen Blasto — tags ['wk_end_auction'], the SOLE
    auction signal (Session 1 fleet-wide tag scan). _is_auction fires."""
    p = _by_title(products, "Cornbred's Red Queen Blasto - WYSIWYG")
    assert "wk_end_auction" in p["tags"]
    assert _is_auction(p, AUCTION_DETECTION) is True


# Test 8: auction row is KEPT (PT='Blasto' is allowlisted; passes normal gate)
def test_auction_row_kept(products):
    """The two live Cornbred auctions sit in PT='Blasto' (allowlisted), so
    they pass the NORMAL gate — the CTK-160 skip_allowlists override is not
    load-bearing for these two. Confirm both the normal gate and the override
    keep the row (the override must never DROP a row the normal gate keeps)."""
    p = _by_title(products, "Cornbred's Red Queen Blasto - WYSIWYG")
    assert _should_keep(p, CORNBRED_CATEGORY_FILTER) is True
    assert _should_keep_with_auction_override(
        p, CORNBRED_CATEGORY_FILTER, AUCTION_DETECTION
    ) is True


# Test 9 (THE GUARANTEE): auction row lands current_price=NULL + is_auction=true
def test_auction_row_price_nulled_and_flagged(products):
    """Cornbred's Red Queen Blasto carries a real $39.99 placeholder bid that
    must NEVER write through (CTK-160 Option-B / CTK-042 read-gate lineage).
    _normalize_product with the real auction_detection nulls current_price and
    sets is_auction=true.

    EXERCISES THE GUARANTEE (feedback_review_results_test_exercises_guarantee):
    asserted through the real _normalize_product null-out branch (L586-589).
    If that branch is deleted, current_price coerces to Decimal('39.99') and
    this test FAILS — the test is not co-incidentally satisfied by some other
    path."""
    p = _by_title(products, "Cornbred's Red Queen Blasto - WYSIWYG")
    # Precondition: the source row carries the real placeholder bid.
    assert p["variants"][0]["price"] == "39.99", "fixture drifted — expected the $39.99 placeholder bid"
    norm = _normalize(p)
    assert norm["current_price"] is None, (
        f"auction price not nulled: {norm['current_price']!r} — the null-price "
        "branch (parse_shopify _normalize_product L586-589) is the guarantee"
    )
    assert norm["is_auction"] is True, "is_auction not set on the wk_end_auction row"
    # compare_at inherits the auction carve-out (CTK-100 L4): null when price null.
    assert norm["compare_at_price"] is None


# Test 10: non-auction coral keeps its real price (no collateral null-out)
def test_non_auction_coral_keeps_price(products):
    """Cornbred's Utter Chaos Paly — non-auction coral. is_auction=false and
    current_price is its real value (the null-out is scoped to auctions only,
    not a blanket coral behavior)."""
    p = _by_title(products, "Cornbred's Utter Chaos Paly - WYSIWYG")
    norm = _normalize(p)
    assert norm["is_auction"] is False
    assert norm["current_price"] is not None, "non-auction coral price should not be nulled"


# Test 11: title_denylist defensive chaeto/macroalgae forward-binding
def test_title_denylist_rejects_chaeto_in_other_bucket():
    """The 4 defensive chaeto/macroalgae title_denylist entries (CTK-107
    D-2-quater fleet parity; /lead-backend ratified for CTK-142). No active
    leak on Cornbred today, but the 'Other' bucket is allowlisted — a future
    Cornbred-admin chaeto row landing in 'Other' would otherwise pass the
    allowlist. Synthetic 'Other'-PT chaeto row drops on the title substring.
    Controls: each of the 4 entries rejects; a real coral title is unaffected."""
    for title in ["Green Chaeto Ball", "Cheato bundle", "Macroalgae pack", "Macro Algae lot"]:
        row = {"title": title, "product_type": "Other", "tags": []}
        assert _should_keep(row, CORNBRED_CATEGORY_FILTER) is False, title
    # FP control: a real Other-bucket coral with no denylist substring stays.
    ok = {"title": "Cornbred's Blue Stripe Duncan", "product_type": "Other", "tags": []}
    assert _should_keep(ok, CORNBRED_CATEGORY_FILTER) is True


# Test 12: skip-count across the fixture matches expected
def test_filter_skip_count_matches(products):
    """Fixture composition: 3 keep (Utter Chaos Paly, Blue Stripe Duncan,
    Red Queen Blasto auction) + 3 reject (Sailfin Tang fish, Sticker, Gift
    Card). The auction is kept via the normal gate (allowlisted PT)."""
    kept = sum(1 for p in products if _should_keep_with_auction_override(
        p, CORNBRED_CATEGORY_FILTER, AUCTION_DETECTION))
    skipped = len(products) - kept
    assert kept == 3, f"expected 3 kept, got {kept}"
    assert skipped == 3, f"expected 3 skipped, got {skipped}"


# Test 13: _normalize_product output shape — coral product
def test_normalize_output_shape(products):
    """_normalize_product on the Paly coral — validates output dict shape per
    arch §1.4 vendor_listings columns + absolute product_url (CTK-033 D1)."""
    p = _by_title(products, "Cornbred's Utter Chaos Paly - WYSIWYG")
    norm = _normalize(p)
    assert norm["raw_title"] == "Cornbred's Utter Chaos Paly - WYSIWYG"
    assert norm["product_url"].startswith("https://cornbredcorals.com/products/")
    assert norm["currency"] == "USD"
    assert norm["vendor_image_url"] is not None
    assert "cdn.shopify.com" in norm["vendor_image_url"]


# Test 14 (MIRROR-PARITY, CTK-115): in-test filter == cornbred.yaml byte-exact
def test_yaml_mirror_parity():
    """CTK-115 mirror-parity: the in-test CORNBRED_CATEGORY_FILTER +
    AUCTION_DETECTION must equal the scrapers/vendors/cornbred.yaml blocks
    byte-exact. A YAML allowlist/denylist/auction-tag amendment that isn't
    mirrored into this test file fails here — the drift class CTK-115 pins
    (the CTK-119 WWC chaeto-mirror lag was exactly this)."""
    cfg = yaml.safe_load(YAML_PATH.read_text(encoding="utf-8"))
    yaml_filter = cfg["category_filter"]
    assert yaml_filter["product_type_allowlist"] == CORNBRED_CATEGORY_FILTER["product_type_allowlist"], (
        "product_type_allowlist drift between cornbred.yaml and the test mirror"
    )
    assert yaml_filter.get("tag_denylist", []) == CORNBRED_CATEGORY_FILTER["tag_denylist"], (
        "tag_denylist drift between cornbred.yaml and the test mirror"
    )
    assert yaml_filter.get("title_denylist", []) == CORNBRED_CATEGORY_FILTER["title_denylist"], (
        "title_denylist drift between cornbred.yaml and the test mirror"
    )
    assert cfg["auction_detection"] == AUCTION_DETECTION, (
        "auction_detection drift between cornbred.yaml and the test mirror"
    )


def main() -> int:
    products = _load_fixture()
    tests = [
        test_html_hash_first_product_keys,
        test_filter_keeps_coral_allowlisted_pt,
        test_filter_keeps_other_bucket_coral,
        test_filter_rejects_empty_pt_fish,
        test_filter_rejects_sticker,
        test_filter_rejects_gift_card,
        test_auction_detected_on_wk_end_auction_tag,
        test_auction_row_kept,
        test_auction_row_price_nulled_and_flagged,
        test_non_auction_coral_keeps_price,
        test_title_denylist_rejects_chaeto_in_other_bucket,
        test_filter_skip_count_matches,
        test_normalize_output_shape,
        test_yaml_mirror_parity,
    ]
    failed = 0
    for t in tests:
        try:
            # tests with no params take none; the rest take the fixture list
            if t in (test_title_denylist_rejects_chaeto_in_other_bucket, test_yaml_mirror_parity):
                t()
            else:
                t(products)
            print(f"PASS  {t.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL  {t.__name__}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
