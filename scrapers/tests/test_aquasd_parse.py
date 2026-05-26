"""scrapers/tests/test_aquasd_parse.py — CTK-090 parse-layer tests for
AquaSD's BigCommerce Stencil shape against locked fixtures
scrapers/tests/fixtures/aquasd/{acropora_p1, clearance_p1, empty}.sample.html.

Parse-only — no DB, no network. Validates parse_bigcommerce._parse_one_page
output shape, html_hash sentinel computation, auction_detection permissive-
default + path-match path, pagination-terminate empty-set path, and
normalize.infer_category / infer_lineage_flag inheritance against three
representative fixtures:
  - acropora_p1.sample.html (5 trimmed cards, SPS-genus catalog)
  - clearance_p1.sample.html (1 card, small bucket)
  - empty.sample.html (0 cards, pagination terminator)

Coverage mirrors per-vendor convention from test_battlecorals_parse.py
(CTK-085 precedent) with BC-Stencil-specific adjustments — BC has no
JSON product object so html_hash strategy + auction-detection path-based
shape + silent-OOS in_stock=True invariant are the new pins. Per Jon's
2026-05-26 directive: 2-3 representative fixtures, NOT 22 per-genus
fixtures (test-infra rot for ~99% redundant parser coverage).

Runnable as:
  python -m scrapers.tests.test_aquasd_parse
"""

from __future__ import annotations

import inspect
import sys
import traceback
from decimal import Decimal
from pathlib import Path

from scrapers.common import parse_bigcommerce
from scrapers.common.http import FetchResult
from scrapers.common.parse_bigcommerce import (
    _compute_card_skeleton_hash,
    _is_auction_category,
    _parse_one_page,
    fetch_and_parse,
)
from scrapers.common.parse_shopify import SchemaChangeError


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "aquasd"
BASE_URL = "https://aquasd.com"


def _load(name: str) -> bytes:
    return (FIXTURE_DIR / name).read_bytes()


# ─── Test 1: 5-card acropora fixture yields 5 items ──────────────────────────
def test_acropora_5_cards_parsed():
    items, first_card_html = _parse_one_page(
        _load("acropora_p1.sample.html"), BASE_URL, "/acropora/", None, None,
    )
    assert len(items) == 5, f"expected 5 items, got {len(items)}"
    assert first_card_html is not None, "first_card_html should be set when cards exist"


# ─── Test 2: item dict shape matches diff.py expected keys ───────────────────
def test_acropora_item_shape():
    """Item dict matches diff.py expected keys (mirrors parse_shopify
    _normalize_product output). Pins parser/persist contract — additive shape
    drift on either side breaks the contract loudly."""
    items, _ = _parse_one_page(
        _load("acropora_p1.sample.html"), BASE_URL, "/acropora/", None, None,
    )
    expected_keys = {
        "raw_title", "normalized_title", "product_url", "vendor_sku",
        "current_price", "currency", "in_stock", "vendor_image_url",
        "category", "lineage_flag",
    }
    got = set(items[0].keys())
    assert got == expected_keys, (
        f"key shape drift — missing={expected_keys - got} extra={got - expected_keys}"
    )


# ─── Test 3: first acropora card — field-by-field extraction ─────────────────
def test_acropora_first_card_field_extraction():
    """First trimmed card is Strawberry Tort Acropora - 4034CF3F4 ($39.59).
    Pins data-name / data-product-price / card-figure__link href / data-
    product-category extraction shape."""
    items, _ = _parse_one_page(
        _load("acropora_p1.sample.html"), BASE_URL, "/acropora/", None, None,
    )
    item = items[0]
    assert item["raw_title"] == "Strawberry Tort Acropora - 4034CF3F4"
    assert item["normalized_title"] == "strawberry tort acropora - 4034cf3f4"
    assert item["product_url"] == "https://aquasd.com/strawberry-tort-acropora-4034cf3f4/"
    assert item["current_price"] == Decimal("39.59"), (
        f"expected $39.59 from data-product-price, got {item['current_price']!r}"
    )
    assert item["currency"] == "USD"
    assert item["in_stock"] is True, "Stencil hides OOS; every parsed card is in_stock=True"
    assert item["vendor_image_url"] is not None
    assert item["vendor_image_url"].startswith("https://cdn11.bigcommerce.com/"), (
        f"vendor_image_url should be CDN-hosted; got {item['vendor_image_url']!r}"
    )
    assert item["vendor_sku"] is None, "BC entity_id is internal, not a vendor SKU"


# ─── Test 4: product_url is absolute (CTK-033 D1 anchor) ─────────────────────
def test_product_url_absolute():
    """Per CTK-033 D1 + arch §2.1 stage 4 normalize lock: product_url is
    ABSOLUTE so diff.classify lookup against existing_by_url hits. Relative
    URLs would miss the dict and force-classify every existing listing as
    'new' on the next-day scrape (price_history explosion + redundant
    re-mirroring)."""
    items, _ = _parse_one_page(
        _load("acropora_p1.sample.html"), BASE_URL, "/acropora/", None, None,
    )
    for item in items:
        assert item["product_url"].startswith("https://aquasd.com/"), (
            f"non-absolute product_url: {item['product_url']!r}"
        )


# ─── Test 5: category inference — acropora-genus titles → "sps" ──────────────
def test_category_inference_sps_for_acropora():
    """normalize.infer_category matches against the synthetic product dict
    {product_type=data-product-category, tags=[], title=data-name}. Acropora-
    bearing titles fire \\bacropora\\b → 'sps' per arch §1.4 enum."""
    items, _ = _parse_one_page(
        _load("acropora_p1.sample.html"), BASE_URL, "/acropora/", None, None,
    )
    for item in items:
        assert item["category"] == "sps", (
            f"expected 'sps' for {item['raw_title']!r}, got {item['category']!r}"
        )


# ─── Test 6: clearance fixture — small-bucket single card ────────────────────
def test_clearance_single_card():
    """clearance_p1.sample.html captures the bucket at the small-bucket-edge
    case (1 card observed at 2026-05-26 probe). Pins parser doesn't choke on
    page with only 1 li.product wrapper."""
    items, first_card_html = _parse_one_page(
        _load("clearance_p1.sample.html"), BASE_URL, "/clearance/", None, None,
    )
    assert len(items) == 1, f"expected 1 item from small-bucket fixture, got {len(items)}"
    assert first_card_html is not None
    assert items[0]["current_price"] is not None, "data-product-price should parse on single card"
    assert items[0]["in_stock"] is True


# ─── Test 7: empty page — 0 cards → ([], None) ───────────────────────────────
def test_empty_page_zero_cards():
    """empty.sample.html has 0 li.product cards; parser yields ([], None).
    fetch_and_parse's caller breaks the pagination loop on empty page_items —
    natural terminator alongside HTTP 404."""
    items, first_card_html = _parse_one_page(
        _load("empty.sample.html"), BASE_URL, "/acropora/", None, None,
    )
    assert items == []
    assert first_card_html is None


# ─── Test 8: auction_detection None → no-op (permissive default) ─────────────
def test_auction_detection_no_op_when_absent():
    """auction_detection=None mirrors parse_shopify's None=no-op shape.
    current_price preserved from data-product-price."""
    items, _ = _parse_one_page(
        _load("acropora_p1.sample.html"), BASE_URL, "/acropora/", None, None,
    )
    assert items[0]["current_price"] == Decimal("39.59")


# ─── Test 9: auction_detection path match → nulls current_price ──────────────
def test_auction_detection_path_match_nulls_price():
    """auction_detection.category_paths includes current iterating path →
    parser nulls current_price per project_auctions_in_scope memory. v1
    AquaSD doesn't ship this config block (eBay-widget auctions out of
    scope), but the plumbing must work for future BC vendors with literal-
    URL auction subpaths."""
    auction = {"category_paths": ["/acropora/"]}
    items, _ = _parse_one_page(
        _load("acropora_p1.sample.html"), BASE_URL, "/acropora/", auction, None,
    )
    for item in items:
        assert item["current_price"] is None, (
            f"expected null current_price under auction path, got {item['current_price']!r}"
        )


# ─── Test 10: auction_detection path miss → preserves current_price ──────────
def test_auction_detection_path_miss_preserves_price():
    """auction_detection.category_paths does NOT match current path →
    current_price preserved. Pins the gate is path-specific, not blanket."""
    auction = {"category_paths": ["/auctions/"]}
    items, _ = _parse_one_page(
        _load("acropora_p1.sample.html"), BASE_URL, "/acropora/", auction, None,
    )
    assert items[0]["current_price"] == Decimal("39.59")


# ─── Test 11: trailing-slash invariant on auction path comparison ────────────
def test_auction_detection_trailing_slash_invariant():
    """Trailing slash on category_path vs config-side is normalized in
    _is_auction_category — comparison is shape-insensitive to slash.
    Prevents a Stencil URL-normalization surprise from silently bypassing
    the auction gate."""
    assert _is_auction_category("/auctions/", {"category_paths": ["/auctions"]}) is True
    assert _is_auction_category("/auctions", {"category_paths": ["/auctions/"]}) is True
    assert _is_auction_category("/auctions/", {"category_paths": ["/auctions/"]}) is True
    assert _is_auction_category("/acropora/", {"category_paths": ["/auctions/"]}) is False


# ─── Test 12: html_hash stable across data-* variance (skeleton-only) ────────
def test_html_hash_first_card_skeleton_stable_across_data_prop_changes():
    """Hash flips ONLY on structural tag/class change. data-name / data-
    product-price / data-entity-id / href variance per card collapses to
    the same hash — theme-engine template-stable per arch §2.6 BC Stencil."""
    card1 = (
        '<li class="product">'
        '<article class="card" data-name="Coral A" data-product-price="10.00">'
        '<span class="price">$10</span></article></li>'
    )
    card2 = (
        '<li class="product">'
        '<article class="card" data-name="Coral B" data-product-price="20.00">'
        '<span class="price">$20</span></article></li>'
    )
    assert _compute_card_skeleton_hash(card1) == _compute_card_skeleton_hash(card2), (
        "hash should be stable across data-attr variance; flipped on data-prop change"
    )


# ─── Test 13: html_hash flips on structural class change (theme refresh) ─────
def test_html_hash_flips_on_structural_class_change():
    """Theme refresh changes the card markup skeleton — hash flips, scrape
    fails fast with error_class='html_schema_change' per arch §2.6 sentinel."""
    card1 = '<li class="product"><article class="card"></article></li>'
    card2 = '<li class="product"><article class="card card--variant"></article></li>'
    assert _compute_card_skeleton_hash(card1) != _compute_card_skeleton_hash(card2)


# ─── Test 14: html_hash deterministic against acropora fixture ───────────────
def test_html_hash_acropora_fixture_deterministic():
    """Hashing the same fixture twice yields identical hash. Pins the no-
    randomness contract — html_hash flip = real schema change, not test-
    machine entropy."""
    _, fc1 = _parse_one_page(
        _load("acropora_p1.sample.html"), BASE_URL, "/acropora/", None, None,
    )
    _, fc2 = _parse_one_page(
        _load("acropora_p1.sample.html"), BASE_URL, "/acropora/", None, None,
    )
    assert _compute_card_skeleton_hash(fc1) == _compute_card_skeleton_hash(fc2)


# ─── Test 15: in_stock invariant — every parsed card lands in_stock=True ─────
def test_in_stock_all_true_at_parse():
    """Stencil hides OOS items from category view; every parsed card is by
    definition in-stock. Pins the silent-OOS posture documented in
    aquasd.yaml + flagged for /lead-backend Q-N. diff.classify's behavior
    on absent-from-scrape rows is the implicit OOS mechanism (currently
    NOT firing — gap)."""
    items, _ = _parse_one_page(
        _load("acropora_p1.sample.html"), BASE_URL, "/acropora/", None, None,
    )
    for item in items:
        assert item["in_stock"] is True, (
            f"BC parser should land every card in_stock=True; got {item['in_stock']!r}"
        )


# ─── Test 16: lineage_flag inheritance — ASD-shape unknown via 2-4 ALL-CAPS ──
def test_lineage_flag_unknown_for_bare_titles():
    """Strawberry Tort Acropora has no 2-4 char ALL-CAPS prefix; infer_lineage_flag
    returns 'unknown'. AquaSD's "ASD " house-prefix titles WOULD fire
    'vendor-named' per the regex (3 chars + Title-cased word), but the
    acropora fixture's first 5 cards are mixed-vendor (Strawberry Tort, BC
    Unicorn Bubblebath, etc.) — only the BC-prefix ones fire. Pins that the
    regex matches the AquaSD-cross-vendor-prefix shape consistent with the
    JF/WWC/TSA/Battlecorals precedent."""
    items, _ = _parse_one_page(
        _load("acropora_p1.sample.html"), BASE_URL, "/acropora/", None, None,
    )
    # First card: "Strawberry Tort Acropora - 4034CF3F4" — no ALL-CAPS prefix
    assert items[0]["lineage_flag"] == "unknown"


def test_lineage_flag_vendor_named_for_bc_prefix():
    """Cards with 2-4 char ALL-CAPS prefix + Title-cased word fire 'vendor-
    named'. 'BC Unicorn Bubblebath Acropora' matches. AquaSD's own "ASD "
    prefix shape would fire the same way."""
    items, _ = _parse_one_page(
        _load("acropora_p1.sample.html"), BASE_URL, "/acropora/", None, None,
    )
    # Card 5 in the trimmed fixture is "BC Unicorn Bubblebath Acropora..."
    bc_items = [i for i in items if i["raw_title"].startswith("BC ")]
    assert bc_items, "expected at least one BC-prefix card in fixture"
    assert bc_items[0]["lineage_flag"] == "vendor-named"


# ─── Test 18: page=1 404 raises SchemaChangeError (F-2a) ─────────────────────
def test_fetch_and_parse_page1_404_raises_schema_change():
    """Page-1 404 = path retired/renamed since YAML write; loud-fail per arch
    §2.4. parse_bigcommerce.fetch_and_parse intercepts status_code==404 BEFORE
    error_class branch so the 404 reaches the page==1 raise rather than
    falling through to FetchError. Pins the schema-change-on-path-retire
    signal vs. the silent pagination-terminate path."""
    original_fetch = parse_bigcommerce.http.fetch
    parse_bigcommerce.http.fetch = lambda url, request_delay_sec=2.0: FetchResult(
        body=None, status_code=404, error_class="other", error_message="HTTP 404",
    )
    try:
        config = {
            "base_url": "https://aquasd.com",
            "category_paths": ["/acropora/"],
            "max_pages": 5,
            "request_delay_sec": 0,
        }
        raised = False
        try:
            fetch_and_parse(config)
        except SchemaChangeError as e:
            raised = True
            assert "/acropora/" in str(e), f"error should name retired path: {e}"
            assert "page 1" in str(e), f"error should specify page 1 retirement: {e}"
        assert raised, "page=1 404 must raise SchemaChangeError, not silently continue"
    finally:
        parse_bigcommerce.http.fetch = original_fetch


# ─── Test 19: page>=2 404 cleanly breaks + items preserved (F-2b) ────────────
def test_fetch_and_parse_page2_404_natural_terminator():
    """Page-≥2 404 = pagination overshoot beyond catalog end. parse_bigcommerce
    intercepts status_code==404 + page > 1 → break, NOT raise. Page-1 items
    already collected survive to ParseResult. Pins natural-pagination-end
    posture per arch §2.4 (404-after-content is not a failure)."""
    original_fetch = parse_bigcommerce.http.fetch
    page1_body = _load("acropora_p1.sample.html")

    call_count = {"n": 0}

    def stub_fetch(url, request_delay_sec=2.0):
        call_count["n"] += 1
        # First fetch returns the 5-card fixture; subsequent return 404.
        if call_count["n"] == 1:
            return FetchResult(body=page1_body, status_code=200, error_class=None, error_message=None)
        return FetchResult(body=None, status_code=404, error_class="other", error_message="HTTP 404")

    parse_bigcommerce.http.fetch = stub_fetch
    try:
        config = {
            "base_url": "https://aquasd.com",
            "category_paths": ["/acropora/"],
            "max_pages": 5,
            "request_delay_sec": 0,
        }
        result = fetch_and_parse(config)
        assert len(result.items) == 5, (
            f"page=1 items must survive page=2 404 terminator; got {len(result.items)}"
        )
        assert result.http_status_last == 404, (
            f"http_status_last should reflect terminating 404; got {result.http_status_last!r}"
        )
        assert result.html_hash is not None, "html_hash should land from page=1 first card"
    finally:
        parse_bigcommerce.http.fetch = original_fetch


# ─── Test 20: all-paths-empty raises SchemaChangeError (F-3) ─────────────────
def test_fetch_and_parse_all_paths_empty_raises():
    """Every iterated category_path yields 0 cards across every page →
    parse_bigcommerce raises SchemaChangeError post-loop ("zero items parsed
    across all category_paths"). Pins the all-empty trap: catalog-rewrite or
    theme-refresh that breaks card selector lands as a loud schema-change,
    not a silent zero-row insert. F-1 (Q-Backend-4) tracks the orthogonal
    risk that this raise pre-empts run.py's block-shaped canary."""
    original_fetch = parse_bigcommerce.http.fetch
    empty_body = _load("empty.sample.html")
    parse_bigcommerce.http.fetch = lambda url, request_delay_sec=2.0: FetchResult(
        body=empty_body, status_code=200, error_class=None, error_message=None,
    )
    try:
        config = {
            "base_url": "https://aquasd.com",
            "category_paths": ["/acropora/", "/zoanthids/"],
            "max_pages": 3,
            "request_delay_sec": 0,
        }
        raised = False
        try:
            fetch_and_parse(config)
        except SchemaChangeError as e:
            raised = True
            assert "zero items" in str(e), f"error should name zero-items signal: {e}"
        assert raised, "all-empty paths must raise SchemaChangeError, not return empty ParseResult"
    finally:
        parse_bigcommerce.http.fetch = original_fetch


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
