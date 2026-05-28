"""scrapers/tests/test_vivid_aquariums_parse.py — CTK-086 Session 2
parse-layer tests for Vivid Aquariums' Shopify /products.json shape against
locked fixture scrapers/tests/fixtures/vivid_aquariums/products.sample.json.

Parse-only — no DB, no network. Validates parse_shopify._normalize_product
output shape + html_hash sentinel computation + category_filter behavior
(product_type_allowlist + tag_denylist) across 3 representative Vivid
products per F3 fold (2-3 representative fixtures per Jon's fixture
discipline; NOT one-per-product-type which would have been 8 fixtures).

Coverage parity with test_battlecorals_parse.py / test_unique_corals_parse.py
(CTK-085 precedent) at compact-fixture scale:
  - 'WYSIWYG Coral' bucket with Vivid's-possessive self-prefix (Vivid's
    Purple Panther Zoanthids) — house-piece allowlist hit
  - 'Corals and Inverts' bucket with cross-vendor TGC ALL-CAPS prefix
    (TGC Cherry Bomb Tenuis Acropora Coral) — secondary bucket allowlist
    hit + lineage_flag='vendor-named' on cross-vendor prefix
  - 'Invert' bucket reject (Peppermint Shrimp) — allowlist miss (PT not in
    allowlist) + ALSO tag_denylist hit on 'Clean Up Crew' tag, exercising
    both rejection axes on the same fixture row

Vivid-specific shape notes (vs. prior Phase 2 vendors):
  - 1840-product steady-state catalog (largest Phase 2 to date)
  - 8 distinct product_types (bucket-shape granularity, NOT taxonomic-
    genus like Battlecorals or structural-class like UC)
  - Self-prefix shape "Vivid's X" possessive (mixed case, apostrophe) —
    does NOT fire infer_lineage_flag (not ALL-CAPS-prefix)
  - originator_prefix=null (no Vivid-attributed seed-list entries)

Runnable as:
  python -m scrapers.tests.test_vivid_aquariums_parse
"""

from __future__ import annotations

import hashlib
import json
import sys
import traceback
from pathlib import Path

from scrapers.common.parse_shopify import _normalize_product, _should_keep


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "vivid_aquariums" / "products.sample.json"
BASE_URL = "https://vividaquariums.com"
ORIGINATOR_PREFIX = None  # CTK-086 Session 2 — null per seed-list absence (Vivid is a distributor, not an originator)
IMAGE_STRATEGY = "mirror"

# Mirrors scrapers/vendors/vivid-aquariums.yaml category_filter block.
# product_type_allowlist locked CTK-086 plan §Decisions Q-2; tag_denylist
# revised at Session 2 open per /lead-backend ratification 2026-05-27
# (empirical full-catalog tag-shape sweep surfaced singular→plural mismatch
# vs. /review-plan F1 fold's prescription; revised to Vivid's empirical
# invert-bucket canon). Anemones + Clams dropped at the CTK-087 sibling
# fold 2026-05-28 (fleet anemone/clam-keep policy) — 10 tags now.
VIVID_CATEGORY_FILTER = {
    "product_type_allowlist": [
        "WYSIWYG Coral",
        "Corals and Inverts",
    ],
    "tag_denylist": [
        "Clean Up Crew", "Crabs", "Cucumbers", "Lobsters", "Nudibranch",
        "Shrimp", "Snails", "Starfish", "Tube Worms", "Urchin",
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
    Matches PE+WWC+TSA+JF+Battlecorals+UC 13-key anchor (body_html,
    created_at, handle, id, images, options, product_type, published_at,
    tags, title, updated_at, variants, vendor). Sentinel flips only when
    keys add/remove."""
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


# Test 2: WYSIWYG Coral allowlist hit + Vivid's possessive house-piece
def test_filter_keeps_wysiwyg_coral_vivids_possessive(products):
    """'WYSIWYG Coral' bucket entry with "Vivid's" possessive self-prefix —
    primary coral bucket (1323 items at ship walk). Passes product_type_
    allowlist; no tag-denylist tags present (50-75, WYSIWYG Zoos)."""
    p = _by_title(products, "Vivid's Purple Panther Zoanthids")
    assert _should_keep(p, VIVID_CATEGORY_FILTER) is True


# Test 3: Corals and Inverts allowlist hit + cross-vendor TGC prefix
def test_filter_keeps_corals_and_inverts_cross_vendor(products):
    """'Corals and Inverts' bucket entry with cross-vendor TGC ALL-CAPS
    prefix — secondary coral bucket (395 items at ship walk; bucket NAME
    admits inverts but ZERO inverts present at 2026-05-27 sweep). Tags
    are coral-genus markers ('Acropora', 'SPS Coral', 'acropora-carduus');
    no tag-denylist match."""
    p = _by_title(products, "TGC Cherry Bomb Tenuis Acropora Coral")
    assert _should_keep(p, VIVID_CATEGORY_FILTER) is True


# Test 4: Invert bucket rejection — allowlist miss AND tag_denylist hit
def test_filter_rejects_invert_bucket_shrimp(products):
    """'Invert' bucket entry (Peppermint Shrimp). Rejected by allowlist
    miss (Invert not in allowlist) — short-circuits before tag_denylist
    evaluation per _should_keep's allowlist-primary semantics. ALSO
    carries 'Clean Up Crew' tag-denylist match (belt-and-suspenders
    redundancy on the same fixture row); see Test 5 for tag_denylist-
    only coverage via synthetic product."""
    p = _by_title(products, "Peppermint Shrimp")
    assert _should_keep(p, VIVID_CATEGORY_FILTER) is False


# Test 5: tag_denylist covers hypothetical Corals-and-Inverts re-curation
def test_filter_rejects_synthetic_invert_in_corals_and_inverts_bucket(products):
    """F1 belt-and-suspenders coverage validation: synthetic product
    mirroring Peppermint Shrimp's tag shape but placed in 'Corals and
    Inverts' bucket (the hypothetical Vivid re-curation event the
    denylist defends against). product_type passes allowlist; tag_denylist
    'Shrimp' / 'Clean Up Crew' co-tags reject. Confirms the denylist's
    high-order intent (catch future re-curation) is structurally wired
    correctly."""
    synthetic = {
        "title": "Synthetic Invert in Corals and Inverts bucket",
        "product_type": "Corals and Inverts",
        "tags": ["Shrimp", "Clean Up Crew", "10-25", "easy"],
    }
    assert _should_keep(synthetic, VIVID_CATEGORY_FILTER) is False


# Test 6: filter is permissive when no category_filter block
def test_filter_vivid_permissive_when_no_block(products):
    """Phase 2 vendor onboarding inheritance — vendor YAML without
    category_filter block (None or {} passes all products through)."""
    for p in products:
        assert _should_keep(p, None) is True, f"None filter rejected {p['title']!r}"
        assert _should_keep(p, {}) is True, f"empty filter rejected {p['title']!r}"


# Test 7: skip-count across Vivid fixture matches expected
def test_filter_vivid_skip_count_matches(products):
    """Vivid fixture composition: 2 coral (Vivid's Purple Panther Zoanthids,
    TGC Cherry Bomb Tenuis Acropora Coral) + 1 invert reject (Peppermint
    Shrimp). Expected: 2 kept, 1 skipped under the locked filter."""
    kept = sum(1 for p in products if _should_keep(p, VIVID_CATEGORY_FILTER))
    skipped = sum(1 for p in products if not _should_keep(p, VIVID_CATEGORY_FILTER))
    assert kept == 2, f"expected 2 kept, got {kept}"
    assert skipped == 1, f"expected 1 skipped, got {skipped}"


# Test 8: _normalize_product output shape — coral product
def test_normalize_vivids_possessive_zoanthids(products):
    """_normalize_product on Vivid's Purple Panther Zoanthids — validates
    output dict shape per arch §1.4 vendor_listings columns. Vivid's
    possessive self-prefix is preserved through normalize_title
    (lowercased + cleaned but possessive apostrophe stays)."""
    p = _by_title(products, "Vivid's Purple Panther Zoanthids")
    norm = _normalize(p)
    assert norm["raw_title"] == "Vivid's Purple Panther Zoanthids"
    assert norm["product_url"] == "https://vividaquariums.com/products/vivids-purple-panther-zoanthids"
    assert norm["vendor_sku"] == "A805"
    assert norm["in_stock"] is True
    assert str(norm["current_price"]) == "54.99"  # Decimal coercion per normalize.coerce_price
    assert norm["currency"] == "USD"
    assert norm["vendor_image_url"] is not None
    assert "cdn.shopify.com" in norm["vendor_image_url"]


# Test 9: lineage_flag fires on cross-vendor ALL-CAPS prefix, not on Vivid's possessive
def test_lineage_flag_cross_vendor_prefix_fires(products):
    """Cross-vendor TGC prefix on 'TGC Cherry Bomb Tenuis Acropora Coral'
    fires infer_lineage_flag='vendor-named' (2-4 char ALL-CAPS-prefix
    shape). Vivid's-possessive house pieces ("Vivid's X") do NOT fire
    because they're not the ALL-CAPS-prefix shape — they land 'unknown'."""
    tgc = _by_title(products, "TGC Cherry Bomb Tenuis Acropora Coral")
    vivids = _by_title(products, "Vivid's Purple Panther Zoanthids")
    tgc_norm = _normalize(tgc)
    vivids_norm = _normalize(vivids)
    assert tgc_norm["lineage_flag"] == "vendor-named", (
        f"TGC cross-vendor prefix should fire vendor-named; got {tgc_norm['lineage_flag']!r}"
    )
    assert vivids_norm["lineage_flag"] == "unknown", (
        f"Vivid's-possessive should land unknown (not ALL-CAPS-prefix); got {vivids_norm['lineage_flag']!r}"
    )


def main() -> int:
    products = _load_fixture()
    tests = [
        test_html_hash_first_product_keys,
        test_filter_keeps_wysiwyg_coral_vivids_possessive,
        test_filter_keeps_corals_and_inverts_cross_vendor,
        test_filter_rejects_invert_bucket_shrimp,
        test_filter_rejects_synthetic_invert_in_corals_and_inverts_bucket,
        test_filter_vivid_permissive_when_no_block,
        test_filter_vivid_skip_count_matches,
        test_normalize_vivids_possessive_zoanthids,
        test_lineage_flag_cross_vendor_prefix_fires,
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
