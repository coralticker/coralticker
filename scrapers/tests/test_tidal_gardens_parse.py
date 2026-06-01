"""scrapers/tests/test_tidal_gardens_parse.py — CTK-087 parse-layer tests for
Tidal Gardens' Magento shape against locked fixtures
scrapers/tests/fixtures/tidal_gardens/{sps_p1, anemones_p1, clams_p1}.sample.html.

Parse-only — no DB, no network. Validates tidal_gardens._parse_one_page output
shape + field extraction, the toolbar-based _is_last_page terminator + Magento
clamp guard (the load-bearing platform divergence — Magento serves page 1 again
past the last page rather than emptying), html_hash skeleton stability across
per-product numeric class suffixes, the {path, category}-hint config shape, and
the anemone/clam-KEEP policy (CTK-087 Jon 2026-05-28).

Three representative fixtures per Jon's 2026-05-26 directive (2-3 fixtures, not
one-per-genus): a coral page (sps, multi-page toolbar), an anemone page (KEEP),
a clam page (KEEP).

Runnable as:
  python -m scrapers.tests.test_tidal_gardens_parse
"""

from __future__ import annotations

import inspect
import sys
import traceback
from decimal import Decimal
from pathlib import Path

import yaml

from scrapers.common import normalize
from scrapers.common.errors import ConfigError
from scrapers.common.http import FetchResult
from scrapers.common.parse_shopify import SchemaChangeError
from scrapers.vendors import tidal_gardens
from scrapers.vendors.tidal_gardens import (
    _compute_card_skeleton_hash,
    _is_last_page,
    _parse_one_page,
    fetch_and_parse,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "tidal_gardens"
YAML_PATH = Path(__file__).parent.parent / "vendors" / "tidal_gardens.yaml"
BASE_URL = "https://tidalgardens.com"

# The category-hint -> arch §1.4 enum contract that tidal-gardens.yaml's
# per-path hints depend on. The scraper passes each path's hint to
# normalize.infer_category as a product_type proxy; the ratified 0%-NULL-
# category claim (337/337 at 2026-05-28 verify-pass) rests on every hint
# resolving to a non-NULL enum. These pins make a future normalize.py
# _CATEGORY_PATTERNS tweak that silently breaks a hint mapping (e.g. dropping
# the `(?:nthid)?` group, which would send all 63 zoanthid-path items to NULL)
# fail a test instead of degrading prod silently. CTK-087 /code-review Finding
# 2 (Tier 3).
EXPECTED_HINT_ENUM = {
    "sps": "sps",
    "lps": "lps",
    "softie": "softie",
    "zoanthid": "zoa",     # lexically divergent — relies on the (?:nthid)? regex
    "mushroom": "mushroom",
    "anemone": "anemone",
    "clam": "clam",
}


def _load(name: str) -> bytes:
    return (FIXTURE_DIR / name).read_bytes()


def _card(title="Test Coral", href="https://tidalgardens.com/stock-test.html",
          price="42.00", img="https://tidalgardens.com/media/catalog/product/x/y/z.jpg",
          price_type="finalPrice"):
    """Synthetic Magento card matching the WeltPixel grid contract."""
    price_span = (
        f'<span class="price-wrapper" data-price-amount="{price}" data-price-type="{price_type}">'
        f'<span class="price">${price}</span></span>' if price is not None else ""
    )
    return (
        '<li class="item product product-item">'
        '<div class="product-item-info"><div class="product_image">'
        f'<span class="product-image-container product-image-container-221">'
        f'<img class="product-image-photo lazy" data-original="{img}" '
        'src="https://tidalgardens.com/static/Loader.gif"/></span></div>'
        '<div class="product details product-item-details">'
        f'<h2 class="product name product-item-name"><a class="product-item-link" href="{href}">{title}</a></h2>'
        f'<div class="price-box price-final_price"><span class="price-container">{price_span}</span></div>'
        '</div></div></li>'
    )


def _page(cards_html: str, toolbar_nums=None) -> bytes:
    tb = ""
    if toolbar_nums is not None:
        spans = "".join(f'<span class="toolbar-number">{n}</span>' for n in toolbar_nums)
        tb = f'<p class="toolbar-amount">{spans}</p>'
    return (
        f'<html><body><div class="column main">{tb}'
        f'<ol class="products list items product-items">{cards_html}</ol>{tb}'
        '</div></body></html>'
    ).encode("utf-8")


# ─── Test 1: sps fixture yields 3 items ──────────────────────────────────────
def test_sps_three_cards_parsed():
    items, first_card_html, page_first_title = _parse_one_page(
        _load("sps_p1.sample.html"), "/corals/sps.html", "sps", None,
    )
    assert len(items) == 3, f"expected 3 items, got {len(items)}"
    assert first_card_html is not None
    assert page_first_title == "24K Leptoseris"


# ─── Test 2: item dict shape matches diff.py expected keys ───────────────────
def test_item_shape():
    items, _, _ = _parse_one_page(_load("sps_p1.sample.html"), "/corals/sps.html", "sps", None)
    expected_keys = {
        "raw_title", "normalized_title", "product_url", "vendor_sku",
        "current_price", "compare_at_price",  # CTK-100 Wave-2 — unconditional key (F9)
        "currency", "in_stock", "vendor_image_url",
        "category", "lineage_flag",
    }
    got = set(items[0].keys())
    assert got == expected_keys, f"key shape drift — missing={expected_keys - got} extra={got - expected_keys}"


# ─── Test 3: first sps card field-by-field ───────────────────────────────────
def test_sps_first_card_field_extraction():
    items, _, _ = _parse_one_page(_load("sps_p1.sample.html"), "/corals/sps.html", "sps", None)
    item = items[0]
    assert item["raw_title"] == "24K Leptoseris"
    assert item["normalized_title"] == "24k leptoseris"
    assert item["product_url"] == "https://tidalgardens.com/stock-24k-leptoseris.html"
    assert item["current_price"] == Decimal("40")
    assert item["currency"] == "USD"
    assert item["in_stock"] is True
    assert item["vendor_sku"] is None
    assert item["category"] == "sps"


# ─── Test 4: image from data-original, resize params stripped ─────────────────
def test_image_data_original_params_stripped():
    """Grid <img src> is a /static/ Loader.gif placeholder; the real /media/
    URL is in data-original. Resize query params are stripped to the canonical
    URL (probe 2026-05-28: bare == param'd bytes)."""
    items, _, _ = _parse_one_page(_load("sps_p1.sample.html"), "/corals/sps.html", "sps", None)
    for item in items:
        assert item["vendor_image_url"].startswith("https://tidalgardens.com/media/catalog/product/")
        assert "?" not in item["vendor_image_url"], f"resize params not stripped: {item['vendor_image_url']!r}"
        assert "/static/" not in item["vendor_image_url"], "lazy-loader placeholder leaked into vendor_image_url"


# ─── Test 5: lazy-loader placeholder only → vendor_image_url None ─────────────
def test_image_placeholder_only_is_none():
    html = _page(
        '<li class="item product product-item"><div class="product-item-details">'
        '<a class="product-item-link" href="https://tidalgardens.com/stock-x.html">X</a>'
        '<span class="price-wrapper" data-price-amount="10" data-price-type="finalPrice"></span>'
        '<img class="product-image-photo" src="https://tidalgardens.com/static/Loader.gif"/>'
        '</div></li>'
    )
    items, _, _ = _parse_one_page(html, "/corals/sps.html", "sps", None)
    assert items[0]["vendor_image_url"] is None, "static placeholder must coerce to None"


# ─── Test 6: product_url absolute ────────────────────────────────────────────
def test_product_url_absolute():
    items, _, _ = _parse_one_page(_load("sps_p1.sample.html"), "/corals/sps.html", "sps", None)
    for item in items:
        assert item["product_url"].startswith("https://tidalgardens.com/"), (
            f"non-absolute product_url: {item['product_url']!r}"
        )


# ─── Test 7: URL prefix is NOT uniformly /stock-*.html ───────────────────────
def test_url_prefix_mixed_stock_and_wysiwyg():
    """Plan assumed /stock-<name>.html universally; the sps fixture carries both
    /stock-*.html and /wysiwyg-*.html. Pins that the parser takes href verbatim
    (no prefix filter)."""
    items, _, _ = _parse_one_page(_load("sps_p1.sample.html"), "/corals/sps.html", "sps", None)
    prefixes = {i["product_url"].rsplit("/", 1)[-1].split("-", 1)[0] for i in items}
    assert "stock" in prefixes and "wysiwyg" in prefixes, (
        f"expected both /stock- and /wysiwyg- URLs in fixture; got {prefixes}"
    )


# ─── Test 8: category hint resolves; title-specific pattern can win ───────────
def test_category_hint_resolves_and_title_wins():
    # sps hint → 'sps'
    items, _, _ = _parse_one_page(_load("sps_p1.sample.html"), "/corals/sps.html", "sps", None)
    assert all(i["category"] == "sps" for i in items)
    # LPS-path "Chalice" title → chalice wins over the lps hint (pattern order)
    html = _page(_card(title="Asgard Lightning Chalice", price="395.00"))
    chal, _, _ = _parse_one_page(html, "/corals/lps.html", "lps", None)
    assert chal[0]["category"] == "chalice", f"title-specific chalice should win over lps hint; got {chal[0]['category']!r}"


# ─── Test 9: price from finalPrice data-price-amount ─────────────────────────
def test_price_from_final_price_amount():
    html = _page(_card(price="135.00"))
    items, _, _ = _parse_one_page(html, "/corals/lps.html", "lps", None)
    assert items[0]["current_price"] == Decimal("135.00")


# ─── Test 10: in_stock all True (Magento hides OOS) ──────────────────────────
def test_in_stock_all_true():
    items, _, _ = _parse_one_page(_load("sps_p1.sample.html"), "/corals/sps.html", "sps", None)
    for item in items:
        assert item["in_stock"] is True, f"Magento hides OOS; every card in_stock=True; got {item['in_stock']!r}"


# ─── Test 11: anemones KEPT (CTK-087 Jon 2026-05-28) ─────────────────────────
def test_anemones_kept():
    """Anemones are named premium morphs (Nexus Burst BTA $445) — KEEP, no
    exclusion. category=anemone."""
    items, _, _ = _parse_one_page(_load("anemones_p1.sample.html"), "/corals/anemones.html", "anemone", None)
    assert len(items) == 3, f"all 3 anemones kept; got {len(items)}"
    assert items[0]["raw_title"] == "Nexus Burst Bubble Tip Anemone"
    assert items[0]["current_price"] == Decimal("445")
    for item in items:
        assert item["category"] == "anemone"


# ─── Test 12: clams KEPT via /inverts/clams.html ─────────────────────────────
def test_clams_kept():
    items, _, _ = _parse_one_page(_load("clams_p1.sample.html"), "/inverts/clams.html", "clam", None)
    assert len(items) == 1
    assert items[0]["raw_title"] == "Flame Scallop"
    assert items[0]["category"] == "clam"
    assert items[0]["current_price"] == Decimal("50")


# ─── Test 13: _is_last_page — multi-page False, single-page True ──────────────
def test_is_last_page_multipage_false():
    # sps fixture toolbar: Items 1-48 of 105 → not last (48 < 105)
    assert _is_last_page(_load("sps_p1.sample.html")) is False


def test_is_last_page_singlepage_true():
    # anemones toolbar: count-only [3]; clams [1] → single page → last
    assert _is_last_page(_load("anemones_p1.sample.html")) is True
    assert _is_last_page(_load("clams_p1.sample.html")) is True


def test_is_last_page_final_page_true():
    # Synthetic final page: Items 337-338 of 338 → 338 >= 338 → last
    assert _is_last_page(_page(_card(), toolbar_nums=[337, 338, 338])) is True


def test_is_last_page_no_toolbar_true():
    # No toolbar at all → treat as last (don't loop forever)
    assert _is_last_page(_page(_card(), toolbar_nums=None)) is True


# ─── Test 14: clamp guard — past-the-end page returns page 1, parser stops ────
def test_clamp_guard_stops_on_repeated_first_title():
    """THE load-bearing Magento divergence: ?p=N past the last page returns
    page 1 again (not empty, not 404). With a non-last toolbar, the loop would
    otherwise re-fetch page 1 forever. The first-title-repeat clamp guard breaks
    WITHOUT re-adding page-1 items."""
    # Body has a non-last toolbar (48 of 105) so the toolbar terminator does NOT
    # fire — only the clamp guard can stop the loop. Every fetch returns the
    # SAME body (the clamp behavior).
    body = _page(_card(title="First Coral", href="https://tidalgardens.com/stock-first.html"),
                 toolbar_nums=[1, 48, 105])
    original = tidal_gardens.http.fetch
    tidal_gardens.http.fetch = lambda url, request_delay_sec=2.0: FetchResult(
        body=body, status_code=200, error_class=None, error_message=None,
    )
    try:
        config = {"base_url": BASE_URL, "category_paths": ["/corals/sps.html"],
                  "max_pages": 10, "request_delay_sec": 0}
        result = fetch_and_parse(config)
        assert len(result.items) == 1, (
            f"clamp must stop after page 1's items; got {len(result.items)} "
            "(loop re-added the clamped page)"
        )
    finally:
        tidal_gardens.http.fetch = original


# ─── Test 15: toolbar terminator stops at last page (no clamp fetch) ──────────
def test_toolbar_terminator_stops_without_extra_fetch():
    """Single-page toolbar ([3]) → _is_last_page True → loop breaks after one
    fetch, never requesting ?p=2 (which would clamp)."""
    body = _page(_card() + _card(title="B", href="https://tidalgardens.com/stock-b.html")
                 + _card(title="C", href="https://tidalgardens.com/stock-c.html"),
                 toolbar_nums=[3])
    calls = {"n": 0}

    def stub(url, request_delay_sec=2.0):
        calls["n"] += 1
        return FetchResult(body=body, status_code=200, error_class=None, error_message=None)

    original = tidal_gardens.http.fetch
    tidal_gardens.http.fetch = stub
    try:
        config = {"base_url": BASE_URL, "category_paths": ["/corals/sps.html"],
                  "max_pages": 10, "request_delay_sec": 0}
        result = fetch_and_parse(config)
        assert len(result.items) == 3
        assert calls["n"] == 1, f"single-page toolbar must stop after 1 fetch; got {calls['n']}"
    finally:
        tidal_gardens.http.fetch = original


# ─── Test 16: html_hash stable across per-product numeric class suffix ────────
def test_html_hash_stable_across_product_id_class_suffix():
    """WeltPixel bakes the product id into product-image-container-<id>. The
    skeleton hash strips the numeric suffix so two cards with different ids
    (and different titles/prices) collapse to the same hash."""
    card_221 = (
        '<li class="item product product-item">'
        '<span class="product-image-container product-image-container-221"></span>'
        '<a class="product-item-link">A</a></li>'
    )
    card_999 = (
        '<li class="item product product-item">'
        '<span class="product-image-container product-image-container-999"></span>'
        '<a class="product-item-link">B</a></li>'
    )
    assert _compute_card_skeleton_hash(card_221) == _compute_card_skeleton_hash(card_999), (
        "hash must be stable across the per-product numeric class suffix"
    )


# ─── Test 17: html_hash flips on structural class change ─────────────────────
def test_html_hash_flips_on_structural_class_change():
    card1 = '<li class="item product product-item"><a class="product-item-link"></a></li>'
    card2 = '<li class="item product product-item"><a class="product-item-link new-class"></a></li>'
    assert _compute_card_skeleton_hash(card1) != _compute_card_skeleton_hash(card2)


# ─── Test 18: html_hash deterministic against fixture ────────────────────────
def test_html_hash_deterministic():
    _, fc1, _ = _parse_one_page(_load("sps_p1.sample.html"), "/corals/sps.html", "sps", None)
    _, fc2, _ = _parse_one_page(_load("sps_p1.sample.html"), "/corals/sps.html", "sps", None)
    assert _compute_card_skeleton_hash(fc1) == _compute_card_skeleton_hash(fc2)


# ─── Test 19: cards present but all skipped → SchemaChangeError ───────────────
def test_cards_present_all_skipped_raises():
    """li.item.product.product-item wrappers present but every card lacks a
    product-item-link — loud-fail (class rename) vs silent empty page."""
    html = _page(
        '<li class="item product product-item"></li>'
        '<li class="item product product-item"></li>'
    )
    raised = False
    try:
        _parse_one_page(html, "/corals/sps.html", "sps", None, page_number=2)
    except SchemaChangeError as e:
        raised = True
        assert "2 cards present" in str(e)
        assert "page 2" in str(e)
        assert "/corals/sps.html" in str(e)
    assert raised, "cards-present-all-skipped must raise SchemaChangeError"


# ─── Test 20: empty category_paths → ConfigError ─────────────────────────────
def test_empty_category_paths_raises_config_error():
    config = {"base_url": BASE_URL, "category_paths": [], "max_pages": 5, "request_delay_sec": 0}
    raised_config = raised_schema = False
    try:
        fetch_and_parse(config)
    except ConfigError as e:
        raised_config = True
        assert "category_paths" in str(e)
    except SchemaChangeError:
        raised_schema = True
    assert raised_config and not raised_schema, "empty category_paths must raise ConfigError"


# ─── Test 21: page-1 404 → SchemaChangeError ─────────────────────────────────
def test_page1_404_raises_schema_change():
    original = tidal_gardens.http.fetch
    tidal_gardens.http.fetch = lambda url, request_delay_sec=2.0: FetchResult(
        body=None, status_code=404, error_class="other", error_message="HTTP 404",
    )
    try:
        config = {"base_url": BASE_URL, "category_paths": ["/corals/sps.html"], "max_pages": 5, "request_delay_sec": 0}
        raised = False
        try:
            fetch_and_parse(config)
        except SchemaChangeError as e:
            raised = True
            assert "/corals/sps.html" in str(e) and "page 1" in str(e)
        assert raised, "page-1 404 must raise SchemaChangeError"
    finally:
        tidal_gardens.http.fetch = original


# ─── Test 22: page>=2 404 → natural terminator, items preserved ──────────────
def test_page2_404_natural_terminator():
    original = tidal_gardens.http.fetch
    page1 = _page(_card(), toolbar_nums=[1, 48, 105])  # non-last toolbar → loop wants page 2
    calls = {"n": 0}

    def stub(url, request_delay_sec=2.0):
        calls["n"] += 1
        if calls["n"] == 1:
            return FetchResult(body=page1, status_code=200, error_class=None, error_message=None)
        return FetchResult(body=None, status_code=404, error_class="other", error_message="HTTP 404")

    tidal_gardens.http.fetch = stub
    try:
        config = {"base_url": BASE_URL, "category_paths": ["/corals/sps.html"], "max_pages": 5, "request_delay_sec": 0}
        result = fetch_and_parse(config)
        assert len(result.items) == 1, f"page-1 items survive page-2 404; got {len(result.items)}"
        assert result.http_status_last == 404
    finally:
        tidal_gardens.http.fetch = original


# ─── Test 23: all-paths zero cards → SchemaChangeError ───────────────────────
def test_all_paths_empty_raises():
    original = tidal_gardens.http.fetch
    empty = _page("", toolbar_nums=None)
    tidal_gardens.http.fetch = lambda url, request_delay_sec=2.0: FetchResult(
        body=empty, status_code=200, error_class=None, error_message=None,
    )
    try:
        config = {"base_url": BASE_URL, "category_paths": ["/corals/sps.html", "/corals/lps.html"],
                  "max_pages": 3, "request_delay_sec": 0}
        raised = False
        try:
            fetch_and_parse(config)
        except SchemaChangeError as e:
            raised = True
            assert "zero items" in str(e)
        assert raised, "all-empty paths must raise SchemaChangeError"
    finally:
        tidal_gardens.http.fetch = original


# ─── Test 24: NaN / Infinity price coerced to None ───────────────────────────
def test_nan_infinity_price_coerced_none():
    for bad in ("NaN", "Infinity"):
        html = _page(_card(price=bad))
        items, _, _ = _parse_one_page(html, "/corals/sps.html", "sps", None)
        assert items[0]["current_price"] is None, f"{bad} price must coerce None; got {items[0]['current_price']!r}"


# ─── Test 25: missing price → None (not a crash) ─────────────────────────────
def test_missing_price_is_none():
    html = _page(_card(price=None))
    items, _, _ = _parse_one_page(html, "/corals/sps.html", "sps", None)
    assert items[0]["current_price"] is None


# ─── Test 26: dict-shaped {path, category} vs plain-string config entries ─────
def test_dict_and_string_path_entries():
    original = tidal_gardens.http.fetch
    sps_body = _load("sps_p1.sample.html")

    def stub(url, request_delay_sec=2.0):
        # First page returns sps fixture (toolbar 1-48 of 105 → not last), then
        # 404 terminates so we don't clamp-loop.
        if "p=1" in url:
            return FetchResult(body=sps_body, status_code=200, error_class=None, error_message=None)
        return FetchResult(body=None, status_code=404, error_class="other", error_message="HTTP 404")

    tidal_gardens.http.fetch = stub
    try:
        # dict-shaped with category hint
        r1 = fetch_and_parse({"base_url": BASE_URL, "request_delay_sec": 0, "max_pages": 3,
                              "category_paths": [{"path": "/corals/sps.html", "category": "sps"}]})
        assert all(i["category"] == "sps" for i in r1.items)
        # plain-string falls back to title-only inference (acropora title → sps)
        r2 = fetch_and_parse({"base_url": BASE_URL, "request_delay_sec": 0, "max_pages": 3,
                              "category_paths": ["/corals/sps.html"]})
        assert len(r2.items) == 3
    finally:
        tidal_gardens.http.fetch = original


# ─── Test 27: dict entry missing 'path' → ConfigError ────────────────────────
def test_dict_entry_missing_path_raises_config_error():
    config = {"base_url": BASE_URL, "request_delay_sec": 0,
              "category_paths": [{"category": "sps"}]}
    raised = False
    try:
        fetch_and_parse(config)
    except ConfigError as e:
        raised = True
        assert "path" in str(e)
    assert raised, "dict entry without 'path' must raise ConfigError"


# ─── Test 28: dedup by product_url, first-seen wins ──────────────────────────
def test_dedup_by_product_url():
    original = tidal_gardens.http.fetch
    # Two paths return a body with the SAME product_url; dedup collapses to 1.
    dup = _page(_card(title="Dup", href="https://tidalgardens.com/stock-dup.html"), toolbar_nums=[1])

    def stub(url, request_delay_sec=2.0):
        if "p=1" in url:
            return FetchResult(body=dup, status_code=200, error_class=None, error_message=None)
        return FetchResult(body=None, status_code=404, error_class="other", error_message="HTTP 404")

    tidal_gardens.http.fetch = stub
    try:
        config = {"base_url": BASE_URL, "request_delay_sec": 0, "max_pages": 2,
                  "category_paths": ["/corals/sps.html", "/corals/lps.html"]}
        result = fetch_and_parse(config)
        assert len(result.items) == 1, f"duplicate product_url across paths must dedup; got {len(result.items)}"
    finally:
        tidal_gardens.http.fetch = original


# ─── Test 29: lineage_flag vendor-named for ALL-CAPS prefix ──────────────────
def test_lineage_flag_vendor_named_for_caps_prefix():
    html = _page(_card(title="TGC Cherry Bomb Acropora"))
    items, _, _ = _parse_one_page(html, "/corals/sps.html", "sps", None)
    assert items[0]["lineage_flag"] == "vendor-named"


def test_lineage_flag_unknown_for_bare_title():
    items, _, _ = _parse_one_page(_load("sps_p1.sample.html"), "/corals/sps.html", "sps", None)
    assert items[0]["lineage_flag"] == "unknown"  # "24K Leptoseris" has no ALL-CAPS prefix


# ─── Test 30: zoanthid hint → 'zoa' (the lexically-divergent mapping) ────────
def test_hint_zoanthid_maps_to_zoa():
    """The fragile one: 'zoanthid' resolves to 'zoa' ONLY via normalize.py's
    `\\bzoa(?:nthid)?s?\\b` regex. A tweak that drops the (?:nthid)? group would
    silently send all 63 zoanthid-path items to NULL category. Tested in
    isolation (empty title) so this is purely the hint path."""
    assert normalize.infer_category({"product_type": "zoanthid", "tags": [], "title": ""}) == "zoa"


# ─── Test 31: softie hint → 'softie' (soft-corals path) ──────────────────────
def test_hint_softie_maps_to_softie():
    assert normalize.infer_category({"product_type": "softie", "tags": [], "title": ""}) == "softie"


# ─── Test 32: mushroom hint → 'mushroom' (corallimorphs path) ────────────────
def test_hint_mushroom_maps_to_mushroom():
    """The /corals/corallimorphs.html path uses the 'mushroom' hint (the enum
    value), NOT 'corallimorph' (which matches no pattern and would resolve
    NULL). Pins that the YAML hint is the pattern-matching token, not the
    biological label."""
    assert normalize.infer_category({"product_type": "mushroom", "tags": [], "title": ""}) == "mushroom"


# ─── Test 33: direct hints (sps / lps / anemone / clam) ──────────────────────
def test_hint_direct_mappings():
    for hint in ("sps", "lps", "anemone", "clam"):
        got = normalize.infer_category({"product_type": hint, "tags": [], "title": ""})
        assert got == EXPECTED_HINT_ENUM[hint], f"hint {hint!r} → {got!r}, expected {EXPECTED_HINT_ENUM[hint]!r}"


# ─── Test 34: every YAML category hint is pinned AND resolves non-NULL ────────
def test_yaml_category_hints_all_pinned_and_non_null():
    """Ties the pins above to the live tidal-gardens.yaml. Loads the real
    config's per-path hints and asserts each (a) is pinned in EXPECTED_HINT_ENUM
    — so a future YAML hint addition without a regression assertion fails here
    — and (b) resolves to the expected non-NULL enum. This is the guard behind
    the 0%-NULL-category claim."""
    cfg = yaml.safe_load(YAML_PATH.read_text(encoding="utf-8"))
    hints = [e["category"] for e in cfg["category_paths"]
             if isinstance(e, dict) and e.get("category")]
    assert hints, "tidal-gardens.yaml category_paths carry no category hints — expected dict-shaped entries"
    for hint in hints:
        assert hint in EXPECTED_HINT_ENUM, (
            f"YAML hint {hint!r} is not pinned in EXPECTED_HINT_ENUM — add a regression assertion"
        )
        got = normalize.infer_category({"product_type": hint, "tags": [], "title": ""})
        assert got is not None, f"YAML hint {hint!r} resolves to NULL category — 0%-NULL guarantee broken"
        assert got == EXPECTED_HINT_ENUM[hint], (
            f"YAML hint {hint!r} → {got!r}, expected {EXPECTED_HINT_ENUM[hint]!r}"
        )


def main() -> int:
    tests = [
        obj for name, obj in inspect.getmembers(sys.modules[__name__], inspect.isfunction)
        if name.startswith("test_")
    ]
    failures: list[tuple[str, str]] = []
    for fn in tests:
        try:
            fn()
            print(f"  [PASS] {fn.__name__}")
        except AssertionError as e:
            print(f"  [FAIL] {fn.__name__}: {e}")
            failures.append((fn.__name__, str(e)))
        except Exception as e:  # noqa: BLE001
            print(f"  [ERROR] {fn.__name__}: {type(e).__name__}: {e}")
            traceback.print_exc()
            failures.append((fn.__name__, f"{type(e).__name__}: {e}"))
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
