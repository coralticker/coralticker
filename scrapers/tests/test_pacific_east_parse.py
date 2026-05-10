"""scrapers/tests/test_pacific_east_parse.py — CTK-037 parse-layer tests for
PE's Shopify /products.json shape against locked fixture
scrapers/tests/fixtures/pacific_east/products.sample.json.

Parse-only — no DB, no network. Covers:
  - parse_shopify._normalize_product output shape per CTK-024 lock
  - parse_shopify._should_keep CTK-037 category-filter gate (D1 lean (a): coral
    + anemones + clams; PE allowlist primary, tag_denylist empty)
  - html_hash sentinel computation per arch §2.6

Inherits CTK-026 test_tsa_parse.py fixture-precedent shape. Closes
open-items.md line 48 "PE parse-layer test retrofit" as CTK-037 co-benefit.

Runnable as:
  python -m scrapers.tests.test_pacific_east_parse
"""

from __future__ import annotations

import hashlib
import json
import sys
import traceback
from pathlib import Path

from scrapers.common.parse_shopify import _normalize_product, _should_keep


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "pacific_east" / "products.sample.json"
BASE_URL = "https://pacificeastaquaculture.com"
ORIGINATOR_PREFIX = None  # CTK-024 D3 lock — PE titles use bare "Coral Colony - <Genus>" pattern
IMAGE_STRATEGY = "mirror"

# Mirrors scrapers/vendors/pacific_east.yaml category_filter block (CTK-037 2026-05-10).
PE_CATEGORY_FILTER = {
    "product_type_allowlist": [
        "Acropora", "Anemone", "Blastomussa", "Colony", "Euphyllia",
        "Gorgonian", "Grow Out", "Maxima Clam", "Under 25", "WYSIWYG",
        "WYSIWYG Frags",
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


# Test 1: html_hash sentinel — sorted-keys-of-first-product SHA256
def test_html_hash_first_product_keys(products):
    """Arch §2.6 Shopify variant: hash sorted key set of first product. Matches
    PE+WWC+TSA 13-key anchor (body_html, created_at, handle, id, images,
    options, product_type, published_at, tags, title, updated_at, variants,
    vendor). Sentinel flips only when keys add/remove."""
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


# Test 2: filter keeps Acropora (SPS coral) product_type
def test_filter_keeps_pe_acropora(products):
    p = _by_title(products, "Coral Colony - Acropora - Tricolor Stag WYSIWYG")
    assert _should_keep(p, PE_CATEGORY_FILTER) is True


# Test 3: filter keeps Euphyllia (LPS coral) product_type
def test_filter_keeps_pe_euphyllia(products):
    p = _by_title(products, "Coral Colony - Euphyllia - Hammer Gold WYSIWYG")
    assert _should_keep(p, PE_CATEGORY_FILTER) is True


# Test 4: filter keeps Maxima Clam — D1 lean (a) seed-list coverage
def test_filter_keeps_pe_maxima_clam(products):
    """Per CTK-037 D1 lean (a) locked 2026-05-10: anemones + clams are in the
    allowlist because the named-coral seed list includes ORA Maxima Clam Ultra
    Gold + ECC Sherman/Rainbow BTA. Phase 3 matcher cannot match seed entries
    that the parse-layer denied."""
    p = _by_title(products, "ORA Maxima Clam Ultra Gold WYSIWYG")
    assert _should_keep(p, PE_CATEGORY_FILTER) is True


# Test 5: filter rejects fish (TankRaised product_type — captive-bred Clownfish)
def test_filter_rejects_pe_tankraised_fish(products):
    """No fish product_types in PE allowlist; TankRaised denied (Clownfish +
    Dottyback + Angelfish). No seed-list overlap so dead-letter is fine."""
    p = _by_title(products, "Captive Bred Picasso Clownfish Pair")
    assert _should_keep(p, PE_CATEGORY_FILTER) is False


# Test 6: filter rejects live rock (Live Rock product_type — substrate)
def test_filter_rejects_pe_live_rock(products):
    p = _by_title(products, "Premium Reef Rock 20lb Box")
    assert _should_keep(p, PE_CATEGORY_FILTER) is False


# Test 7: filter is permissive when no category_filter block
def test_filter_pe_permissive_when_no_block(products):
    """Phase 2 vendor onboarding inheritance — vendor YAML without
    category_filter block (None or {} passes all products through)."""
    for p in products:
        assert _should_keep(p, None) is True, f"None filter rejected {p['title']!r}"
        assert _should_keep(p, {}) is True, f"empty filter rejected {p['title']!r}"


# Test 8: skip-count across PE fixture matches expected (2 of 5 denied)
def test_filter_pe_skip_count_matches(products):
    """PE fixture composition: 3 coral (Acropora, Euphyllia, Maxima Clam) +
    2 non-coral (TankRaised fish, Live Rock). Expected filter skip = 2."""
    kept = sum(1 for p in products if _should_keep(p, PE_CATEGORY_FILTER))
    skipped = sum(1 for p in products if not _should_keep(p, PE_CATEGORY_FILTER))
    assert kept == 3, f"expected 3 kept, got {kept}"
    assert skipped == 2, f"expected 2 skipped, got {skipped}"


# Test 9: product_url absolute per CTK-033 D1 anchor
def test_pe_product_url_absolute(products):
    for p in products:
        out = _normalize(p)
        assert out["product_url"].startswith(BASE_URL + "/products/"), (
            f"product_url not absolute for {p['title']!r}: {out['product_url']!r}"
        )


# Test 10: currency USD default per Q1-3 lock
def test_pe_currency_usd_default(products):
    for p in products:
        assert _normalize(p)["currency"] == "USD"


# Test 11: PE originator_prefix=null → normalize_title leaves bare-coral untouched
def test_pe_normalize_no_prefix_synthesis(products):
    """PE originator_prefix=null per CTK-024 D3 lock — normalize_title returns
    lowercased raw title with no prefix work. Matcher §3.4 stage 3 is a no-op
    for PE."""
    p = _by_title(products, "Coral Colony - Acropora - Tricolor Stag WYSIWYG")
    out = _normalize(p)
    assert out["normalized_title"].startswith("coral colony"), (
        f"unexpected normalize output: {out['normalized_title']!r}"
    )


# Test 12: in_stock toggles correctly with variants.available
def test_pe_in_stock_semantics(products):
    """Per arch §2.1 stage 4: any(v.get('available'))."""
    p_oos = _by_title(products, "Coral Colony - Euphyllia - Hammer Gold WYSIWYG")
    p_in = _by_title(products, "Coral Colony - Acropora - Tricolor Stag WYSIWYG")
    assert _normalize(p_oos)["in_stock"] is False
    assert _normalize(p_in)["in_stock"] is True


def main() -> int:
    products = _load_fixture()
    print(f"loaded fixture: {len(products)} products from {FIXTURE_PATH}")

    tests = [
        test_html_hash_first_product_keys,
        test_filter_keeps_pe_acropora,
        test_filter_keeps_pe_euphyllia,
        test_filter_keeps_pe_maxima_clam,
        test_filter_rejects_pe_tankraised_fish,
        test_filter_rejects_pe_live_rock,
        test_filter_pe_permissive_when_no_block,
        test_filter_pe_skip_count_matches,
        test_pe_product_url_absolute,
        test_pe_currency_usd_default,
        test_pe_normalize_no_prefix_synthesis,
        test_pe_in_stock_semantics,
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
