"""scrapers/tests/test_wwc_parse.py — CTK-037 parse-layer tests for WWC's
Shopify /products.json shape against locked fixture
scrapers/tests/fixtures/wwc/products.sample.json.

Parse-only — no DB, no network. Covers:
  - parse_shopify._normalize_product output shape per CTK-025 lock
  - parse_shopify._should_keep CTK-037 category-filter gate (WWC allowlist —
    Frag / VP Frags / WYSIWYG Frag / WWC Colony / Pack / etc; tag_denylist
    empty because Fish has its own product_type)
  - html_hash sentinel computation per arch §2.6

Inherits CTK-026 test_tsa_parse.py fixture-precedent shape. Closes
open-items.md line 48 "WWC parse-layer test retrofit" as CTK-037 co-benefit.

Runnable as:
  python -m scrapers.tests.test_wwc_parse
"""

from __future__ import annotations

import hashlib
import json
import sys
import traceback
from pathlib import Path

from scrapers.common.parse_shopify import _normalize_product, _should_keep


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "wwc" / "products.sample.json"
BASE_URL = "https://worldwidecorals.com"
ORIGINATOR_PREFIX = "wwc"  # CTK-025 D3 lock — matcher §3.4 stage 3 synthesizes wwc-prefix
IMAGE_STRATEGY = "mirror"

# Mirrors scrapers/vendors/wwc.yaml category_filter block (CTK-037 2026-05-10).
WWC_CATEGORY_FILTER = {
    "product_type_allowlist": [
        "Featured Livestock", "Frag", "Frag-PoS", "Live Sale Coral", "Pack",
        "VP Colonies", "VP Frags", "Wholesale Frag", "WWC Colony", "WYSIWYG Frag",
    ],
    "tag_denylist": [],
}


def _load_fixture() -> list[dict]:
    with FIXTURE_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)["products"]


def _by_title(products: list[dict], title: str) -> dict:
    for p in products:
        if p["title"] == title:
            return p
    raise KeyError(f"fixture missing product titled {title!r}")


def _normalize(p: dict) -> dict:
    return _normalize_product(p, BASE_URL, IMAGE_STRATEGY, ORIGINATOR_PREFIX)


# Test 1: html_hash sentinel
def test_html_hash_first_product_keys(products):
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


# Test 2: filter keeps Frag (coral)
def test_filter_keeps_wwc_frag(products):
    p = _by_title(products, "WWC Avocado Smasher Zoanthids")
    assert _should_keep(p, WWC_CATEGORY_FILTER) is True


# Test 3: filter keeps VP Frags (coral)
def test_filter_keeps_wwc_vp_frags(products):
    p = _by_title(products, "JF Acid Reflux Zoanthids")
    assert _should_keep(p, WWC_CATEGORY_FILTER) is True


# Test 4: filter keeps WYSIWYG Frag (coral)
def test_filter_keeps_wwc_wysiwyg_frag(products):
    p = _by_title(products, "WYSIWYG Acropora Frag Pack")
    assert _should_keep(p, WWC_CATEGORY_FILTER) is True


# Test 5: filter rejects Fish product_type (cleanly siloed at WWC)
def test_filter_rejects_wwc_fish(products):
    """WWC's Fish product_type is the cleanest single-type denial in Phase 1.
    444 items / ~23% of catalog rejected by allowlist alone — no tag-denylist
    needed."""
    p = _by_title(products, "Yellow Tang Hawaii")
    assert _should_keep(p, WWC_CATEGORY_FILTER) is False


# Test 6: filter rejects Dry Goods (equipment)
def test_filter_rejects_wwc_dry_goods(products):
    p = _by_title(products, "Red Sea Reefer 250 Aquarium")
    assert _should_keep(p, WWC_CATEGORY_FILTER) is False


# Test 7: filter is permissive when no category_filter block
def test_filter_wwc_permissive_when_no_block(products):
    for p in products:
        assert _should_keep(p, None) is True
        assert _should_keep(p, {}) is True


# Test 8: skip-count across WWC fixture matches expected (2 of 5 denied)
def test_filter_wwc_skip_count_matches(products):
    """WWC fixture composition: 3 coral (Frag, VP Frags, WYSIWYG Frag) +
    2 non-coral (Fish, Dry Goods). Expected filter skip = 2."""
    kept = sum(1 for p in products if _should_keep(p, WWC_CATEGORY_FILTER))
    skipped = sum(1 for p in products if not _should_keep(p, WWC_CATEGORY_FILTER))
    assert kept == 3, f"expected 3 kept, got {kept}"
    assert skipped == 2, f"expected 2 skipped, got {skipped}"


# Test 9: product_url absolute per CTK-033 D1 anchor
def test_wwc_product_url_absolute(products):
    for p in products:
        out = _normalize(p)
        assert out["product_url"].startswith(BASE_URL + "/products/"), (
            f"product_url not absolute for {p['title']!r}: {out['product_url']!r}"
        )


# Test 10: currency USD default
def test_wwc_currency_usd_default(products):
    for p in products:
        assert _normalize(p)["currency"] == "USD"


# Test 11: vendor_image_url is images[0].src
def test_wwc_vendor_image_url_first_image(products):
    p = _by_title(products, "WWC Avocado Smasher Zoanthids")
    out = _normalize(p)
    assert out["vendor_image_url"] == p["images"][0]["src"]


# Test 12: in_stock toggles correctly with variants.available
def test_wwc_in_stock_semantics(products):
    p_in = _by_title(products, "WWC Avocado Smasher Zoanthids")
    p_oos = _by_title(products, "JF Acid Reflux Zoanthids")
    assert _normalize(p_in)["in_stock"] is True
    assert _normalize(p_oos)["in_stock"] is False


def main() -> int:
    products = _load_fixture()
    print(f"loaded fixture: {len(products)} products from {FIXTURE_PATH}")

    tests = [
        test_html_hash_first_product_keys,
        test_filter_keeps_wwc_frag,
        test_filter_keeps_wwc_vp_frags,
        test_filter_keeps_wwc_wysiwyg_frag,
        test_filter_rejects_wwc_fish,
        test_filter_rejects_wwc_dry_goods,
        test_filter_wwc_permissive_when_no_block,
        test_filter_wwc_skip_count_matches,
        test_wwc_product_url_absolute,
        test_wwc_currency_usd_default,
        test_wwc_vendor_image_url_first_image,
        test_wwc_in_stock_semantics,
    ]

    failures: list[tuple[str, str]] = []
    for fn in tests:
        name = fn.__name__
        try:
            fn(products)
            print(f"  [PASS] {name}")
        except AssertionError as e:
            print(f"  [FAIL] {name}: {e}")
            failures.append((name, str(e)))
        except Exception as e:  # noqa: BLE001
            print(f"  [ERROR] {name}: {type(e).__name__}: {e}")
            traceback.print_exc()
            failures.append((name, f"{type(e).__name__}: {e}"))

    print()
    if failures:
        print(f"{len(failures)}/{len(tests)} tests failed:")
        for name, msg in failures:
            print(f"  - {name}: {msg[:200]}")
        return 1
    print(f"all {len(tests)} tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
