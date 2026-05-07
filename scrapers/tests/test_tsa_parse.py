"""scrapers/tests/test_tsa_parse.py — CTK-026 parse-layer tests for TSA's
Shopify /products.json shape against locked fixture
scrapers/tests/fixtures/tsa/products.sample.json.

Parse-only — no DB, no network. Validates parse_shopify._normalize_product
output shape + html_hash sentinel computation across seven curated TSA
products covering: TSA-prefix coral OOS, TSA-prefix coral in-stock, no-
prefix coral OOS (matcher §3.4 stage 3 case), no-prefix coral in-stock,
fish (non-coral category-inference path), multi-variant merch (variant-
list logic), no-SKU edge case (sku=None).

Runnable as:
  python -m scrapers.tests.test_tsa_parse

Fixture regen path documented in scrapers/vendors/tsa.py docstring (CTK-024/
025/026 convention).

Coverage:
  test_html_hash_first_product_keys                      arch §2.6 sentinel
  test_tsa_prefix_coral_normalize_preserves_prefix       decision #18
  test_no_prefix_coral_normalize_no_synthesis            stage 3 input shape
  test_oos_product_in_stock_false                        variants.available
  test_in_stock_product_in_stock_true                    variants.available
  test_multi_variant_merch_in_stock_any                  any-available logic
  test_no_sku_product_sku_none                           sku selection edge
  test_product_url_absolute                              CTK-033 D1 anchor
  test_vendor_image_url_first_image                      images[0].src
  test_currency_usd_default                              Q1-3 lock
  test_lineage_flag_vendor_named_on_caps_prefix          infer_lineage_flag
  test_category_inference                                arch §1.4 enum
"""

from __future__ import annotations

import hashlib
import json
import sys
import traceback
from pathlib import Path

from scrapers.common.parse_shopify import _normalize_product


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "tsa" / "products.sample.json"
BASE_URL = "https://topshelfaquatics.com"
ORIGINATOR_PREFIX = "tsa"  # matches scrapers/vendors/tsa.yaml D3-equivalent lock
IMAGE_STRATEGY = "mirror"


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


# ─── Test 1: html_hash sentinel — sorted-keys-of-first-product SHA256 ─────────
def test_html_hash_first_product_keys(products):
    """Arch §2.6 Shopify variant: hash sorted key set of first product object.
    F5 fold (sort-before-hash) in parse_shopify.py:82 — Shopify can change JSON
    key emission order across versions without a real schema change; sorting
    collapses ordering noise. The hash flips ONLY when keys are added/removed.
    """
    first = products[0]
    keys = sorted(first.keys())
    expected = hashlib.sha256(",".join(keys).encode("utf-8")).hexdigest()
    # Empirical anchor: 13 keys per smoke 2026-05-07. PE+WWC also have 13 keys.
    assert len(keys) == 13, (
        f"expected 13 keys on first product (matches PE+WWC empirical anchor), "
        f"got {len(keys)}: {keys}"
    )
    expected_keys = [
        "body_html", "created_at", "handle", "id", "images", "options",
        "product_type", "published_at", "tags", "title", "updated_at",
        "variants", "vendor",
    ]
    assert keys == expected_keys, (
        f"first-product key set drift — expected {expected_keys}, got {keys}. "
        f"If a key was added/removed, the html_hash sentinel will flip and "
        f"scraper_runs.error_class='html_schema_change' will fire next scrape."
    )
    assert len(expected) == 64, f"SHA256 hex digest is 64 chars; got {len(expected)}"


# ─── Test 2: TSA-prefix coral — normalize PRESERVES prefix per decision #18 ───
def test_tsa_prefix_coral_normalize_preserves_prefix(products):
    """Per decision #18 (§3.2 cascade fix): vendor prefix is preserved in
    normalized_title. The matcher §3.4 stage 3 prepends originator_prefix at
    match-time for no-prefix titles; it does NOT strip an existing prefix from
    prefix-bearing titles. originator_prefix YAML config does not affect
    normalize_title output (decision #23 + decision #18 interaction).
    """
    p = _by_title(products, "TSA Deep Soul Favia Coral")
    out = _normalize(p)
    assert out["raw_title"] == "TSA Deep Soul Favia Coral"
    assert out["normalized_title"] == "tsa deep soul favia coral", (
        f"prefix should be preserved (lowercase only); got {out['normalized_title']!r}"
    )


# ─── Test 3: no-prefix coral — normalize_title is bare (matcher §3.4 stage 3) ─
def test_no_prefix_coral_normalize_no_synthesis(products):
    """Per matcher §3.4 stage 3: no-prefix titles are normalized to bare
    ("beast boy favia coral"). Stage 3 SYNTHESIZES "tsa beast boy favia coral"
    against canonical-prefix patterns at match-time; that synthesis lives in
    matcher.py, not parse_shopify. This test pins the parse-layer contract.
    """
    p = _by_title(products, "Beast Boy Favia Coral")
    out = _normalize(p)
    assert out["normalized_title"] == "beast boy favia coral", (
        f"no-prefix title should normalize bare; got {out['normalized_title']!r}"
    )


# ─── Test 4: OOS product — variants.available all false → in_stock=False ──────
def test_oos_product_in_stock_false(products):
    """Arch §2.1 stage 4 in_stock semantics: any(v.get('available')) across
    variants. Between-drop window TSA corals are typically OOS — fixture
    captures this realistic state. price_history diff logic depends on
    in_stock toggling correctly so price-changed-while-OOS doesn't trip a
    stock-changed event."""
    p = _by_title(products, "TSA Deep Soul Favia Coral")
    out = _normalize(p)
    assert out["in_stock"] is False, f"expected in_stock=False, got {out['in_stock']!r}"


# ─── Test 5: in-stock product → in_stock=True ─────────────────────────────────
def test_in_stock_product_in_stock_true(products):
    p = _by_title(products, "Krak God Zoanthids Coral")
    out = _normalize(p)
    assert out["in_stock"] is True, f"expected in_stock=True, got {out['in_stock']!r}"


# ─── Test 6: multi-variant merch — any-available decides in_stock ─────────────
def test_multi_variant_merch_in_stock_any(products):
    """T-shirt with 6 size variants. in_stock=True if ANY variant available;
    in_stock=False only if ALL variants are unavailable. Phase 1 stock-flip
    de-duplication depends on this any-semantics — a single-size restock
    on a multi-variant product flips in_stock True without false-positive
    'all sizes restocked'."""
    p = _by_title(products, "TSA Coral Pattern Outline UV Reactive T-Shirt")
    variants = p.get("variants") or []
    assert len(variants) > 1, f"fixture multi-variant pick should have >1 variants; got {len(variants)}"
    out = _normalize(p)
    expected = any(v.get("available") for v in variants)
    assert out["in_stock"] is expected, (
        f"in_stock={out['in_stock']!r} doesn't match any(available)={expected!r}"
    )


# ─── Test 7: no-SKU product → vendor_sku=None ─────────────────────────────────
def test_no_sku_product_sku_none(products):
    """Hydros Duet variant emits sku=None (or empty). parse_shopify picks the
    first non-empty SKU across variants; if none, returns None. NOT NULL on
    vendor_listings.vendor_sku is not enforced (per arch §1.4 + CTK-024 0002
    drop-vendor-sku-unique migration), so None lands cleanly."""
    p = _by_title(products, "Hydros Duet Dosing Pump & Aquarium Controller - Hydros")
    out = _normalize(p)
    assert out["vendor_sku"] is None, (
        f"expected vendor_sku=None for no-SKU product; got {out['vendor_sku']!r}"
    )


# ─── Test 8: product_url is absolute (CTK-033 D1 anchor) ──────────────────────
def test_product_url_absolute(products):
    """Per CTK-033 D1 + arch §2.1 stage 4 normalize lock: product_url is
    ABSOLUTE (base_url joined to /products/<handle>). The diff.classify()
    lookup against existing_by_url depends on this — relative URLs would
    miss the dict and force-classify every existing listing as 'new' on the
    next-day scrape (price_history explosion + redundant re-mirroring)."""
    for p in products:
        out = _normalize(p)
        assert out["product_url"].startswith(BASE_URL + "/products/"), (
            f"product_url not absolute for {p['title']!r}: {out['product_url']!r}"
        )
        assert out["product_url"].endswith(p["handle"]), (
            f"product_url missing handle suffix for {p['title']!r}: {out['product_url']!r}"
        )


# ─── Test 9: vendor_image_url is images[0].src (raw, pre-mirror) ──────────────
def test_vendor_image_url_first_image(products):
    """Phase B mirror queue pulls vendor_image_url and writes image_url after
    R2 storage. Parse layer just hands over the raw vendor URL untouched."""
    p = _by_title(products, "TSA Deep Soul Favia Coral")
    out = _normalize(p)
    expected_src = p["images"][0]["src"]
    assert out["vendor_image_url"] == expected_src, (
        f"vendor_image_url should be images[0].src; expected {expected_src!r}, "
        f"got {out['vendor_image_url']!r}"
    )


# ─── Test 10: currency = USD per Q1-3 lock ────────────────────────────────────
def test_currency_usd_default(products):
    """Phase 1 vendors all USD per Q1-3 (arch §1.4 / decision register). Parse
    layer hardcodes USD; currency-aware logic re-opens at Phase 2 if any vendor
    ships non-USD."""
    for p in products:
        out = _normalize(p)
        assert out["currency"] == "USD", (
            f"currency drift on {p['title']!r}: expected 'USD', got {out['currency']!r}"
        )


# ─── Test 11: lineage_flag — vendor-named on ALL-CAPS prefix ──────────────────
def test_lineage_flag_vendor_named_on_caps_prefix(products):
    """infer_lineage_flag fires 'vendor-named' on 2-4 char ALL-CAPS prefix
    followed by title-case (matches "TSA Deep Soul..." pattern). 'unknown'
    otherwise. Cheap heuristic; matcher §3 does real lineage work."""
    tsa_prefix = _by_title(products, "TSA Deep Soul Favia Coral")
    no_prefix = _by_title(products, "Beast Boy Favia Coral")
    fish = _by_title(products, "Powder Blue Tang")

    assert _normalize(tsa_prefix)["lineage_flag"] == "vendor-named", (
        "TSA-prefix coral should flip lineage_flag to vendor-named"
    )
    assert _normalize(no_prefix)["lineage_flag"] == "unknown", (
        "no-prefix coral should be lineage_flag=unknown (matcher §3 does real work)"
    )
    assert _normalize(fish)["lineage_flag"] == "unknown", (
        "fish (non-coral) should be lineage_flag=unknown"
    )


# ─── Test 12: category inference per arch §1.4 enum ───────────────────────────
def test_category_inference(products):
    """infer_category matches against product_type + tags + title. Arch §1.4
    enum: ('sps','lps','softie','zoa','mushroom','anemone','clam','chalice',
    'fish','invert','equipment','other'). First-hit wins; more specific
    before generic. Favia/Acan → lps; Zoanthids → zoa; Tang → fish."""
    favia = _by_title(products, "TSA Deep Soul Favia Coral")
    zoa = _by_title(products, "Krak God Zoanthids Coral")
    tang = _by_title(products, "Powder Blue Tang")

    assert _normalize(favia)["category"] == "lps", (
        f"Favia should match lps; got {_normalize(favia)['category']!r}"
    )
    assert _normalize(zoa)["category"] == "zoa", (
        f"Zoanthids should match zoa; got {_normalize(zoa)['category']!r}"
    )
    assert _normalize(tang)["category"] == "fish", (
        f"Tang should match fish; got {_normalize(tang)['category']!r}"
    )


def main() -> int:
    products = _load_fixture()
    print(f"loaded fixture: {len(products)} products from {FIXTURE_PATH}")

    tests = [
        test_html_hash_first_product_keys,
        test_tsa_prefix_coral_normalize_preserves_prefix,
        test_no_prefix_coral_normalize_no_synthesis,
        test_oos_product_in_stock_false,
        test_in_stock_product_in_stock_true,
        test_multi_variant_merch_in_stock_any,
        test_no_sku_product_sku_none,
        test_product_url_absolute,
        test_vendor_image_url_first_image,
        test_currency_usd_default,
        test_lineage_flag_vendor_named_on_caps_prefix,
        test_category_inference,
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
