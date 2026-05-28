"""scrapers/tests/test_reef_chasers_parse.py — CTK-086 Session 3 parse-layer
tests for Reef Chasers' Shopify /products.json shape against locked fixture
scrapers/tests/fixtures/reef_chasers/products.sample.json.

Parse-only — no DB, no network. Validates parse_shopify._normalize_product
output shape + html_hash sentinel + the Q-4 tag_allowlist category_filter
behavior across 3 representative RC products per F3 fold (2-3 representative
fixtures per Jon's fixture discipline; NOT one-per-tag).

Reef Chasers is the FIRST vendor exercising the Q-4 tag_allowlist axis
(landed CTK-086 Session 2 in scrapers/common/parse_shopify._should_keep).
RC's product_type is empty ('') universally — taxonomy lives in tags, so
tag_allowlist: ['Coral'] is the load-bearing gate (not product_type_allowlist).

Coverage (3 fixtures + 1 synthetic):
  - RC Space Invader Chalice Frag — 'Coral'-tagged coral with RC self-prefix:
    tag_allowlist hit (keep) + lineage_flag='vendor-named' on RC prefix
  - Blue Hippo Tang — Fish/Tang-tagged fish: tag_allowlist miss (no 'Coral'
    tag) → reject; ALSO carries tag_denylist Fish+Tang (redundant, but
    allowlist-miss short-circuits first)
  - Two Little Fishes AcroPower — coral-keyword title but coral-FOOD
    supplement (tags: coral food / food / liquid food; no 'Coral' tag, no
    denylist tag): tag_allowlist miss → silent reject (correct; the "Acro"
    in the title is a false-positive, the product is a supplement)
  - synthetic 'Coral' + denylist co-occurrence — exercises tag_denylist
    short-circuit AFTER tag_allowlist hit (the dormant belt-and-suspenders
    path; zero such rows in the live catalog at 2026-05-28 walk)

Runnable as:
  python -m scrapers.tests.test_reef_chasers_parse
"""

from __future__ import annotations

import hashlib
import json
import sys
import traceback
from pathlib import Path

from scrapers.common.parse_shopify import _normalize_product, _should_keep


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "reef_chasers" / "products.sample.json"
BASE_URL = "https://reefchasers.com"
ORIGINATOR_PREFIX = None  # CTK-086 Session 3 — null per seed-list absence (no RC-attributed canonicals)
IMAGE_STRATEGY = "mirror"

# Mirrors scrapers/vendors/reef-chasers.yaml category_filter block.
# tag_allowlist + tag_denylist locked CTK-086 plan §Decisions Q-2; full-
# catalog validation 2026-05-28 (zero coverage gap, all 11 denylist
# spellings verbatim-present, zero denylist co-occurrence with 'Coral').
RC_CATEGORY_FILTER = {
    "tag_allowlist": ["Coral"],
    "tag_denylist": [
        "Fish", "Tang", "Wrasse", "Goby", "Tropic Marin", "shipping",
        "module", "supplement", "fragtech", "aquarium", "sticker",
    ],
}


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
    return _normalize_product(p, BASE_URL, IMAGE_STRATEGY, ORIGINATOR_PREFIX)


# Test 1: html_hash sentinel — sorted-keys-of-first-product SHA256
def test_html_hash_first_product_keys(products):
    """Arch §2.6 Shopify variant: hash sorted key set of first product.
    Matches PE+WWC+TSA+JF+Battlecorals+UC+Vivid 13-key anchor. Sentinel
    flips only when keys add/remove."""
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


# Test 2: tag_allowlist hit — 'Coral'-tagged coral with empty product_type
def test_filter_keeps_coral_tagged_rc_self_prefix(products):
    """RC Space Invader Chalice Frag — product_type='' (RC universal empty-PT
    shape), tags include 'Coral'. tag_allowlist: ['Coral'] hit → keep.
    Validates the Q-4 tag_allowlist axis as the load-bearing gate for an
    empty-product_type vendor."""
    p = _by_title(products, "RC Space Invader Chalice Frag")
    assert p["product_type"] == "", "RC fixture should have empty product_type"
    assert "Coral" in p["tags"]
    assert _should_keep(p, RC_CATEGORY_FILTER) is True


# Test 3: tag_allowlist miss — Fish-tagged row (no 'Coral' tag)
def test_filter_rejects_fish_no_coral_tag(products):
    """Blue Hippo Tang — tags ['Fish', 'Tang'], no 'Coral' tag. tag_allowlist
    miss → short-circuit reject (before tag_denylist evaluation). The Fish +
    Tang denylist tags are redundant here; allowlist-miss is the operative
    rejection."""
    p = _by_title(products, "Blue Hippo Tang")
    assert "Coral" not in p["tags"]
    assert _should_keep(p, RC_CATEGORY_FILTER) is False


# Test 4: tag_allowlist miss — coral-keyword title but non-coral supplement
def test_filter_rejects_coral_food_false_positive(products):
    """Two Little Fishes AcroPower — title carries 'Acro' (coral-keyword
    false-positive) but the product is an SPS amino-acid supplement (tags:
    coral food / food / liquid food; no 'Coral' tag, no denylist tag).
    tag_allowlist miss → silent reject. Confirms allowlist-miss correctly
    drops non-coral rows that carry neither 'Coral' nor a denylist tag
    (the residue class)."""
    p = _by_title(products, "Two Little Fishes AcroPower")
    assert "Coral" not in p["tags"]
    assert _should_keep(p, RC_CATEGORY_FILTER) is False


# Test 5: tag_denylist short-circuits after tag_allowlist hit (dormant path)
def test_filter_rejects_synthetic_coral_with_denylist_tag(products):
    """Belt-and-suspenders coverage validation: synthetic row carrying BOTH
    'Coral' (passes tag_allowlist) AND 'Fish' (fails tag_denylist) — the
    hypothetical RC re-tagging event the denylist defends against. Zero such
    rows in the live catalog at 2026-05-28 walk (denylist dormant); this
    test confirms the denylist short-circuit is wired correctly for the
    future re-tagging case."""
    synthetic = {
        "title": "Synthetic mistagged row — Coral + Fish co-occurrence",
        "product_type": "",
        "tags": ["Coral", "Fish", "WYSIWYG"],
    }
    assert _should_keep(synthetic, RC_CATEGORY_FILTER) is False


# Test 6: filter is permissive when no category_filter block
def test_filter_rc_permissive_when_no_block(products):
    """Phase 2 vendor onboarding inheritance — vendor YAML without
    category_filter block (None or {} passes all products through)."""
    for p in products:
        assert _should_keep(p, None) is True, f"None filter rejected {p['title']!r}"
        assert _should_keep(p, {}) is True, f"empty filter rejected {p['title']!r}"


# Test 7: skip-count across RC fixture matches expected
def test_filter_rc_skip_count_matches(products):
    """RC fixture composition: 1 coral (RC Space Invader Chalice Frag) +
    2 non-coral (Blue Hippo Tang fish, Two Little Fishes AcroPower supplement).
    Expected: 1 kept, 2 skipped under the locked tag_allowlist filter."""
    kept = sum(1 for p in products if _should_keep(p, RC_CATEGORY_FILTER))
    skipped = sum(1 for p in products if not _should_keep(p, RC_CATEGORY_FILTER))
    assert kept == 1, f"expected 1 kept, got {kept}"
    assert skipped == 2, f"expected 2 skipped, got {skipped}"


# Test 8: _normalize_product output shape — coral product with empty PT
def test_normalize_rc_space_invader_chalice(products):
    """_normalize_product on RC Space Invader Chalice Frag — validates output
    dict shape per arch §1.4 vendor_listings columns. Empty product_type
    flows through normalize.infer_category (category inferred from title, not
    product_type)."""
    p = _by_title(products, "RC Space Invader Chalice Frag")
    norm = _normalize(p)
    assert norm["raw_title"] == "RC Space Invader Chalice Frag"
    assert norm["product_url"].startswith("https://reefchasers.com/products/")
    assert norm["currency"] == "USD"
    assert norm["vendor_image_url"] is not None
    assert "cdn.shopify.com" in norm["vendor_image_url"]


# Test 9: lineage_flag fires on RC self-prefix (2-char ALL-CAPS shape)
def test_lineage_flag_rc_self_prefix_fires(products):
    """RC self-prefix on 'RC Space Invader Chalice Frag' fires
    infer_lineage_flag='vendor-named' (2-char ALL-CAPS-prefix shape). RC
    originates house lineages even though seed-list has no RC canonicals
    yet (originator_prefix=null is correct today — matcher stage-3 synthesis
    has nothing to match against; the lineage_flag is parse-layer signal,
    independent of the synthesis path)."""
    p = _by_title(products, "RC Space Invader Chalice Frag")
    norm = _normalize(p)
    assert norm["lineage_flag"] == "vendor-named", (
        f"RC self-prefix should fire vendor-named; got {norm['lineage_flag']!r}"
    )


def main() -> int:
    products = _load_fixture()
    tests = [
        test_html_hash_first_product_keys,
        test_filter_keeps_coral_tagged_rc_self_prefix,
        test_filter_rejects_fish_no_coral_tag,
        test_filter_rejects_coral_food_false_positive,
        test_filter_rejects_synthetic_coral_with_denylist_tag,
        test_filter_rc_permissive_when_no_block,
        test_filter_rc_skip_count_matches,
        test_normalize_rc_space_invader_chalice,
        test_lineage_flag_rc_self_prefix_fires,
    ]
    failed = 0
    for t in tests:
        try:
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
