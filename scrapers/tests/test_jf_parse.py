"""scrapers/tests/test_jf_parse.py — CTK-037 parse-layer tests for Jason Fox
Signature Corals' Shopify /products.json shape against locked fixture
scrapers/tests/fixtures/jf/products.sample.json.

Pre-staged at CTK-037 Session 2 per /lead-backend F3 (review-plan disposition
2026-05-10) — CTK-027 Session 1 inherits this fixture + test verbatim. The
full scrapers/vendors/jf.yaml write is deferred to CTK-027 Session 1; the
category_filter block content lives in CTK-037 plan body §YAML schema sketch.

Parse-only — no DB, no network. Covers:
  - parse_shopify._normalize_product output shape (CTK-024/025/026 inheritance)
  - parse_shopify._should_keep CTK-037 category-filter gate (JF allowlist —
    SPS / LPS / WYSIWYG / Zoanthids/Softies / MYSTERY BOX / Chalices;
    tag_denylist empty)
  - html_hash sentinel computation per arch §2.6

ORIGINATOR_PREFIX='jf' is provisional pending CTK-027 Session 1 final decision;
sample titles ("JF Acid Reflux Zoanthids", "JF Pearl Bubble SPS Acropora")
match WWC's `JF` prefix convention so 'jf' is the empirical lean.

Runnable as:
  python -m scrapers.tests.test_jf_parse
"""

from __future__ import annotations

import hashlib
import json
import sys
import traceback
from pathlib import Path

from scrapers.common.parse_shopify import _normalize_product, _should_keep


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "jf" / "products.sample.json"
BASE_URL = "https://jasonfoxsignaturecorals.com"
ORIGINATOR_PREFIX = "jf"  # provisional — CTK-027 Session 1 finalizes against full-catalog title-shape walk
IMAGE_STRATEGY = "mirror"

# Mirrors CTK-037 plan body §YAML schema sketch — JF block content (CTK-037 2026-05-10).
# Lands at scrapers/vendors/jf.yaml when CTK-027 Session 1 writes the file.
JF_CATEGORY_FILTER = {
    "product_type_allowlist": [
        "Chalices", "LPS", "MYSTERY BOX", "SPS", "WYSIWYG", "Zoanthids/Softies",
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


# Test 2: filter keeps SPS (coral)
def test_filter_keeps_jf_sps(products):
    p = _by_title(products, "JF Pearl Bubble SPS Acropora")
    assert _should_keep(p, JF_CATEGORY_FILTER) is True


# Test 3: filter keeps Zoanthids/Softies (coral)
def test_filter_keeps_jf_zoanthids_softies(products):
    p = _by_title(products, "JF Acid Reflux Zoanthids")
    assert _should_keep(p, JF_CATEGORY_FILTER) is True


# Test 4: filter keeps WYSIWYG (coral)
def test_filter_keeps_jf_wysiwyg(products):
    p = _by_title(products, "JF Dragon Fire WYSIWYG Chalice")
    assert _should_keep(p, JF_CATEGORY_FILTER) is True


# Test 5: filter keeps MYSTERY BOX (coral pack — CTK-037 plan body decision)
def test_filter_keeps_jf_mystery_box(products):
    """Per CTK-037 plan body §YAML schema sketch — MYSTERY BOX is allowlisted
    because samples confirm coral packs ('JF MYSTERY BOX (6 mixed frags)' /
    'JF MYSTERY BOX (15 mixed frags)'). Both volumes coral; no apparel/equipment
    leaks the title pattern."""
    p = _by_title(products, "JF MYSTERY BOX (6 mixed frags)")
    assert _should_keep(p, JF_CATEGORY_FILTER) is True


# Test 6: filter rejects tshirt (apparel)
def test_filter_rejects_jf_tshirt(products):
    p = _by_title(products, "JF Logo Tee")
    assert _should_keep(p, JF_CATEGORY_FILTER) is False


# Test 7: filter is permissive when no category_filter block
def test_filter_jf_permissive_when_no_block(products):
    for p in products:
        assert _should_keep(p, None) is True
        assert _should_keep(p, {}) is True


# Test 8: skip-count across JF fixture matches expected (1 of 5 denied)
def test_filter_jf_skip_count_matches(products):
    """JF fixture composition: 4 coral (SPS, Zoanthids/Softies, WYSIWYG,
    MYSTERY BOX) + 1 non-coral (tshirt). Expected filter skip = 1."""
    kept = sum(1 for p in products if _should_keep(p, JF_CATEGORY_FILTER))
    skipped = sum(1 for p in products if not _should_keep(p, JF_CATEGORY_FILTER))
    assert kept == 4, f"expected 4 kept, got {kept}"
    assert skipped == 1, f"expected 1 skipped, got {skipped}"


# Test 9: product_url absolute per CTK-033 D1 anchor
def test_jf_product_url_absolute(products):
    for p in products:
        out = _normalize(p)
        assert out["product_url"].startswith(BASE_URL + "/products/"), (
            f"product_url not absolute for {p['title']!r}: {out['product_url']!r}"
        )


# Test 10: currency USD default
def test_jf_currency_usd_default(products):
    for p in products:
        assert _normalize(p)["currency"] == "USD"


# Test 11: JF-prefix titles preserve prefix per decision #18
def test_jf_prefix_preserved_in_normalize(products):
    """Sample titles all carry JF prefix; normalize_title preserves prefix
    (decision #18). Matcher §3.4 stage 3 may strip/synthesize at match-time
    against canonical patterns; that's matcher work, not parse work."""
    p = _by_title(products, "JF Pearl Bubble SPS Acropora")
    out = _normalize(p)
    assert out["raw_title"] == "JF Pearl Bubble SPS Acropora"
    assert out["normalized_title"].startswith("jf "), (
        f"prefix should be preserved (lowercase); got {out['normalized_title']!r}"
    )


# Test 12: in_stock toggles correctly with variants.available
def test_jf_in_stock_semantics(products):
    p_in = _by_title(products, "JF Pearl Bubble SPS Acropora")
    p_oos = _by_title(products, "JF Acid Reflux Zoanthids")
    assert _normalize(p_in)["in_stock"] is True
    assert _normalize(p_oos)["in_stock"] is False


def main() -> int:
    products = _load_fixture()
    print(f"loaded fixture: {len(products)} products from {FIXTURE_PATH}")

    tests = [
        test_html_hash_first_product_keys,
        test_filter_keeps_jf_sps,
        test_filter_keeps_jf_zoanthids_softies,
        test_filter_keeps_jf_wysiwyg,
        test_filter_keeps_jf_mystery_box,
        test_filter_rejects_jf_tshirt,
        test_filter_jf_permissive_when_no_block,
        test_filter_jf_skip_count_matches,
        test_jf_product_url_absolute,
        test_jf_currency_usd_default,
        test_jf_prefix_preserved_in_normalize,
        test_jf_in_stock_semantics,
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
