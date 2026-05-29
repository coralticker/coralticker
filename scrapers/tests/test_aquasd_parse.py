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
from scrapers.common.errors import ConfigError
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
    items, first_card_html, _ = _parse_one_page(
        _load("acropora_p1.sample.html"), BASE_URL, "/acropora/", None, None,
    )
    assert len(items) == 5, f"expected 5 items, got {len(items)}"
    assert first_card_html is not None, "first_card_html should be set when cards exist"


# ─── Test 2: item dict shape matches diff.py expected keys ───────────────────
def test_acropora_item_shape():
    """Item dict matches diff.py expected keys (mirrors parse_shopify
    _normalize_product output). Pins parser/persist contract — additive shape
    drift on either side breaks the contract loudly."""
    items, _, _ = _parse_one_page(
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
    items, _, _ = _parse_one_page(
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
    items, _, _ = _parse_one_page(
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
    items, _, _ = _parse_one_page(
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
    items, first_card_html, _ = _parse_one_page(
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
    items, first_card_html, _ = _parse_one_page(
        _load("empty.sample.html"), BASE_URL, "/acropora/", None, None,
    )
    assert items == []
    assert first_card_html is None


# ─── Test 8: auction_detection None → no-op (permissive default) ─────────────
def test_auction_detection_no_op_when_absent():
    """auction_detection=None mirrors parse_shopify's None=no-op shape.
    current_price preserved from data-product-price."""
    items, _, _ = _parse_one_page(
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
    items, _, _ = _parse_one_page(
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
    items, _, _ = _parse_one_page(
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
    _, fc1, _ = _parse_one_page(
        _load("acropora_p1.sample.html"), BASE_URL, "/acropora/", None, None,
    )
    _, fc2, _ = _parse_one_page(
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
    items, _, _ = _parse_one_page(
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
    items, _, _ = _parse_one_page(
        _load("acropora_p1.sample.html"), BASE_URL, "/acropora/", None, None,
    )
    # First card: "Strawberry Tort Acropora - 4034CF3F4" — no ALL-CAPS prefix
    assert items[0]["lineage_flag"] == "unknown"


def test_lineage_flag_vendor_named_for_bc_prefix():
    """Cards with 2-4 char ALL-CAPS prefix + Title-cased word fire 'vendor-
    named'. 'BC Unicorn Bubblebath Acropora' matches. AquaSD's own "ASD "
    prefix shape would fire the same way."""
    items, _, _ = _parse_one_page(
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


# ─── Test 21: overlap dedup — duplicate product_urls collapse, first-seen wins ─
def test_overlap_dedup_collapses_duplicates_first_seen_wins():
    """Two category_paths return the same fixture; without parser-level dedup
    each overlap product writes 2 price_history rows per scrape (CTK-090
    Session 4 /code-review finding #1). Dedup preserves first-seen iteration
    order — items from the first iterated category_path win the slot."""
    original_fetch = parse_bigcommerce.http.fetch
    acropora_body = _load("acropora_p1.sample.html")

    def stub_fetch(url, request_delay_sec=2.0):
        if "page=1" in url:
            return FetchResult(body=acropora_body, status_code=200, error_class=None, error_message=None)
        return FetchResult(body=None, status_code=404, error_class="other", error_message="HTTP 404")

    parse_bigcommerce.http.fetch = stub_fetch
    try:
        config = {
            "base_url": "https://aquasd.com",
            "category_paths": ["/softies/", "/zoanthids/"],
            "max_pages": 5,
            "request_delay_sec": 0,
        }
        result = fetch_and_parse(config)
        assert len(result.items) == 5, (
            f"two paths × 5 cards each must dedup to 5 unique items; got {len(result.items)}"
        )
        urls = [it["product_url"] for it in result.items]
        assert len(set(urls)) == len(urls), "deduped items must have unique product_urls"
        # First-seen wins: /softies/ iterates before /zoanthids/, so /softies/'s
        # first card (acropora_p1 fixture's first item) sits at result.items[0].
        assert result.items[0]["raw_title"] == "Strawberry Tort Acropora - 4034CF3F4", (
            f"first-seen ordering broken; first item raw_title={result.items[0]['raw_title']!r}"
        )
    finally:
        parse_bigcommerce.http.fetch = original_fetch


# ─── Test 22: NaN price coerced to None ──────────────────────────────────────
def test_nan_price_coerced_to_none():
    """Decimal('NaN') succeeds (no InvalidOperation); downstream diff.classify
    compares old != new and NaN != NaN is always True, so a single NaN-priced
    card writes one price_history row per scrape forever. is_finite() guard
    coerces non-finite to None — same shape as a missing data-product-price
    (CTK-090 Session 4 /code-review finding #6)."""
    html = (
        b'<ul>'
        b'<li class="product"><article class="card" data-name="NaN Test Coral" '
        b'data-product-category="SPS" data-product-price="NaN" '
        b'data-entity-id="1">'
        b'<a class="card-figure__link" href="/nan-test/"></a>'
        b'<img class="card-image" src="https://cdn.example.com/nan.jpg"/>'
        b'</article></li>'
        b'</ul>'
    )
    items, _, _ = _parse_one_page(html, BASE_URL, "/acropora/", None, None)
    assert len(items) == 1
    assert items[0]["current_price"] is None, (
        f"NaN price must coerce to None; got {items[0]['current_price']!r}"
    )


# ─── Test 23: Infinity price coerced to None ─────────────────────────────────
def test_infinity_price_coerced_to_none():
    """Sibling to NaN — Decimal('Infinity') is_finite() is False too."""
    html = (
        b'<ul>'
        b'<li class="product"><article class="card" data-name="Inf Test" '
        b'data-product-category="SPS" data-product-price="Infinity" '
        b'data-entity-id="2">'
        b'<a class="card-figure__link" href="/inf-test/"></a>'
        b'<img class="card-image" src="https://cdn.example.com/inf.jpg"/>'
        b'</article></li>'
        b'</ul>'
    )
    items, _, _ = _parse_one_page(html, BASE_URL, "/acropora/", None, None)
    assert len(items) == 1
    assert items[0]["current_price"] is None, (
        f"Infinity price must coerce to None; got {items[0]['current_price']!r}"
    )


# ─── Test 24: cards present but all skipped → SchemaChangeError ──────────────
def test_cards_present_all_skipped_raises_schema_change():
    """li.product wrappers in DOM but every per-card validation step skips
    (no <article>, no data-name, no card-figure__link href) — without the
    per-page validation-fail raise, parser yields ([], None) and caller
    treats as natural pagination end. Loud-fail discriminates class-rename
    theme drift from genuine empty page (CTK-090 Session 4 /code-review
    finding #2 / #7)."""
    html = (
        b'<ul>'
        b'<li class="product"></li>'
        b'<li class="product"></li>'
        b'<li class="product"></li>'
        b'</ul>'
    )
    raised = False
    try:
        _parse_one_page(html, BASE_URL, "/acropora/", None, None, page_number=2)
    except SchemaChangeError as e:
        raised = True
        assert "3 cards present" in str(e), f"error should name card count: {e}"
        assert "page 2" in str(e), f"error should name page number: {e}"
        assert "/acropora/" in str(e), f"error should name category path: {e}"
    assert raised, "cards-present-all-skipped must raise SchemaChangeError, not return empty"


# ─── Test 25: per-category min WARN on undershoot (no raise) ─────────────────
def test_expected_min_per_category_warns_when_undershoot():
    """Single category below the per-category floor logs a grep-friendly WARN
    and persists its items; the run does NOT raise. This is the CTK-090
    Session 7 downgrade (2026-05-29) of the original Session 4 finding-#3
    fatal raise — the live /cynarinas/ probe found 1 in-stock product (no
    empty-state marker, because a product IS present), which a fatal raise
    would have red-flagged as schema drift and spammed ops. The genuine
    single-category template break is already loud-failed elsewhere
    (cards-present-all-skipped in _parse_one_page, all-categories-empty
    raise at fetch_and_parse bottom, §2.6 html_hash sentinel). Mirrors the
    CTK-088 POTO buyable-drop WARN precedent. /clearance/ is also a real
    1-card small-bucket in production YAML — same WARN signal applies."""
    import logging
    original_fetch = parse_bigcommerce.http.fetch
    clearance_body = _load("clearance_p1.sample.html")  # 1 card, no marker

    def stub_fetch(url, request_delay_sec=2.0):
        if "page=1" in url:
            return FetchResult(body=clearance_body, status_code=200, error_class=None, error_message=None)
        return FetchResult(body=None, status_code=404, error_class="other", error_message="HTTP 404")

    parse_log = logging.getLogger("scrapers.common.parse_bigcommerce")
    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = _Capture(level=logging.WARNING)
    parse_log.addHandler(handler)
    prev_level = parse_log.level
    prev_propagate = parse_log.propagate
    parse_log.setLevel(logging.WARNING)
    parse_log.propagate = False  # F11: keep WARNs off stderr in script-mode runner
    parse_bigcommerce.http.fetch = stub_fetch
    try:
        config = {
            "base_url": "https://aquasd.com",
            "category_paths": ["/cynarinas/"],
            "max_pages": 3,
            "request_delay_sec": 0,
            "expected_min_per_category": 3,  # mirrors production aquasd.yaml floor
        }
        result = fetch_and_parse(config)
    finally:
        parse_bigcommerce.http.fetch = original_fetch
        parse_log.removeHandler(handler)
        parse_log.setLevel(prev_level)
        parse_log.propagate = prev_propagate

    assert len(result.items) == 1, (
        f"undershoot category's items must survive the WARN; got {len(result.items)}"
    )
    messages = [r.getMessage() for r in records]
    assert any("below per-category floor" in m for m in messages), (
        f"expected per-category-floor WARN; got: {messages}"
    )
    assert any("/cynarinas/" in m for m in messages), (
        f"WARN should name violating path; got: {messages}"
    )


# ─── Test 26: expected_min_per_category absent → no check ────────────────────
def test_expected_min_absent_skips_check():
    """expected_min_per_category absent from config → no per-category
    threshold check fires; current behavior preserved (small-bucket
    categories like /clearance/ at 1 card don't false-trigger when
    operator hasn't opted in)."""
    original_fetch = parse_bigcommerce.http.fetch
    clearance_body = _load("clearance_p1.sample.html")  # 1 card

    def stub_fetch(url, request_delay_sec=2.0):
        if "page=1" in url:
            return FetchResult(body=clearance_body, status_code=200, error_class=None, error_message=None)
        return FetchResult(body=None, status_code=404, error_class="other", error_message="HTTP 404")

    parse_bigcommerce.http.fetch = stub_fetch
    try:
        config = {
            "base_url": "https://aquasd.com",
            "category_paths": ["/clearance/"],
            "max_pages": 3,
            "request_delay_sec": 0,
        }
        result = fetch_and_parse(config)
        assert len(result.items) == 1, "absent threshold = no check; 1 item returns cleanly"
    finally:
        parse_bigcommerce.http.fetch = original_fetch


# ─── Test 27: hash anchor captured AFTER per-card validation ─────────────────
def test_hash_anchor_skips_malformed_first_card():
    """Pre-validation cards[0] could be an ad slot / promo banner that fails
    per-card validation; pre-validation anchor capture would flip the hash
    on theme cosmetic noise. Post-validation anchor sits on first VALIDATED
    card instead (CTK-090 Session 4 /code-review finding #4)."""
    html = (
        b'<ul>'
        # Malformed: li.product wrapper but no inner <article>. Skipped per-card.
        b'<li class="product" data-ad="promo"></li>'
        # Valid card.
        b'<li class="product"><article class="card" data-name="Valid Card" '
        b'data-product-category="SPS" data-product-price="42.00" '
        b'data-entity-id="42">'
        b'<a class="card-figure__link" href="/valid/"></a>'
        b'<img class="card-image" src="https://cdn.example.com/valid.jpg"/>'
        b'</article></li>'
        b'</ul>'
    )
    items, first_card_html, _ = _parse_one_page(html, BASE_URL, "/acropora/", None, None)
    assert len(items) == 1, "only the valid card should parse"
    assert first_card_html is not None, "hash anchor must capture the valid card"
    assert 'data-name="Valid Card"' in first_card_html, (
        f"hash anchor should sit on the validated card; got first_card_html={first_card_html[:200]!r}"
    )
    assert 'data-ad="promo"' not in first_card_html, (
        f"hash anchor must NOT capture the malformed cards[0]; got {first_card_html[:200]!r}"
    )


# ─── Test 28: empty category_paths → ConfigError, not SchemaChangeError ──────
def test_empty_category_paths_raises_config_error():
    """Empty category_paths is a config-side mistake (YAML hand-edit), not
    vendor-side schema drift. ConfigError routes to error_class='config'
    in run.py so on-call investigates the YAML, not the vendor surface
    (CTK-090 Session 4 /code-review finding #13)."""
    config = {
        "base_url": "https://aquasd.com",
        "category_paths": [],
        "max_pages": 5,
        "request_delay_sec": 0,
    }
    raised_config = False
    raised_schema = False
    try:
        fetch_and_parse(config)
    except ConfigError as e:
        raised_config = True
        assert "category_paths" in str(e), f"error should name the missing field: {e}"
    except SchemaChangeError:
        raised_schema = True
    assert raised_config, "empty category_paths must raise ConfigError"
    assert not raised_schema, "ConfigError must NOT be a SchemaChangeError subclass"


# ─── Test 29: empty-category marker + zero cards → per-category check skipped ─
def test_empty_category_marker_skips_threshold():
    """AquaSD's BC Stencil renders `<p data-no-products-notification>` on
    categories with zero stock (e.g., /acanthos/ on 2026-05-27 daily-cron run
    377). Without marker detection, a non-zero expected_min_per_category would
    fire a per-category WARN on every legitimate empty category. Marker-
    present + zero-cards → caller skips the per-category check entirely for
    that category (no WARN, no raise); the scrape continues across remaining
    categories (CTK-090 Session 6 daily-cron empty-category fix; per-cat
    check downgraded from raise to WARN at Session 7 2026-05-29, marker
    carve-out still load-bearing to avoid double-signal with the page-1
    marker-detected-empty log line)."""
    original_fetch = parse_bigcommerce.http.fetch
    empty_cat_body = _load("empty_category.sample.html")
    acropora_body = _load("acropora_p1.sample.html")

    def stub_fetch(url, request_delay_sec=2.0):
        if "/acanthos/" in url and "page=1" in url:
            return FetchResult(body=empty_cat_body, status_code=200, error_class=None, error_message=None)
        if "/acropora/" in url and "page=1" in url:
            return FetchResult(body=acropora_body, status_code=200, error_class=None, error_message=None)
        return FetchResult(body=None, status_code=404, error_class="other", error_message="HTTP 404")

    parse_bigcommerce.http.fetch = stub_fetch
    try:
        config = {
            "base_url": "https://aquasd.com",
            "category_paths": ["/acanthos/", "/acropora/"],
            "max_pages": 3,
            "request_delay_sec": 0,
            "expected_min_per_category": 3,  # mirrors production aquasd.yaml floor
        }
        result = fetch_and_parse(config)
        assert len(result.items) == 5, (
            f"acropora's 5 cards must survive while /acanthos/ marker-empty skips check; "
            f"got {len(result.items)} items"
        )
        urls = [it["product_url"] for it in result.items]
        for url in urls:
            assert "/acanthos" not in url, (
                f"marker-empty category must emit zero items; got {url!r}"
            )
    finally:
        parse_bigcommerce.http.fetch = original_fetch


# ─── Test 30: marker + cards present → SchemaChangeError (template bug) ──────
def test_marker_with_cards_still_raises_schema_change():
    """AND-with-zero-cards is load-bearing per CTK-090 Session 6 directive:
    a template bug rendering both the empty-state scaffold AND product cards
    is logically contradictory and must trip SchemaChangeError. Don't
    simplify marker detection to marker-only — render-layer drift needs
    human eyes."""
    html = (
        b'<html><body>'
        b'<p data-no-products-notification role="alert">There are no products listed.</p>'
        b'<ul>'
        b'<li class="product"><article class="card" data-name="Phantom Card" '
        b'data-product-category="SPS" data-product-price="10.00" '
        b'data-entity-id="1">'
        b'<a class="card-figure__link" href="/phantom/"></a>'
        b'<img class="card-image" src="https://cdn.example.com/phantom.jpg"/>'
        b'</article></li>'
        b'</ul>'
        b'</body></html>'
    )
    raised = False
    try:
        _parse_one_page(html, BASE_URL, "/acanthos/", None, None, page_number=1)
    except SchemaChangeError as e:
        raised = True
        assert "marker" in str(e).lower(), f"error should name marker conflict: {e}"
        assert "/acanthos/" in str(e), f"error should name category path: {e}"
    assert raised, "marker + cards must raise SchemaChangeError, not silently emit items"


# ─── Test 31: no marker + zero cards → per-cat WARN then raise via guard ─────
def test_no_marker_zero_cards_warns_and_then_raises_via_total_empty_guard():
    """A category producing zero items WITHOUT the empty-state marker is still
    suspicious (selector drift, silent catalog wipe, fetch-layer issue
    masquerading as a 200). Post-Session-7 downgrade (2026-05-29), the per-
    category check WARNs (not raises) and the all-categories-empty raise at
    fetch_and_parse bottom (parse_bigcommerce.py L150-151) is the load-bearing
    loud-fail. F14 tighten: assert BOTH signals fire in sequence — per-cat
    WARN names /acropora/ and below-floor; then the bottom-guard raises with
    'zero items' + 'all category_paths'. The Session 6 marker carve-out still
    narrows the per-cat WARN to vendor-emitted-empty cases (no double-signal
    with the page-1 marker log); the bottom guard catches selector-drift-
    without-marker."""
    import logging
    original_fetch = parse_bigcommerce.http.fetch
    empty_body = _load("empty.sample.html")  # 0 cards, NO marker

    def stub_fetch(url, request_delay_sec=2.0):
        if "page=1" in url:
            return FetchResult(body=empty_body, status_code=200, error_class=None, error_message=None)
        return FetchResult(body=None, status_code=404, error_class="other", error_message="HTTP 404")

    parse_log = logging.getLogger("scrapers.common.parse_bigcommerce")
    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = _Capture(level=logging.WARNING)
    parse_log.addHandler(handler)
    prev_level = parse_log.level
    prev_propagate = parse_log.propagate
    parse_log.setLevel(logging.WARNING)
    parse_log.propagate = False
    parse_bigcommerce.http.fetch = stub_fetch
    raised_schema = False
    raise_msg = ""
    try:
        config = {
            "base_url": "https://aquasd.com",
            "category_paths": ["/acropora/"],
            "max_pages": 3,
            "request_delay_sec": 0,
            "expected_min_per_category": 3,  # mirrors production aquasd.yaml floor
        }
        try:
            fetch_and_parse(config)
        except SchemaChangeError as e:
            raised_schema = True
            raise_msg = str(e)
    finally:
        parse_bigcommerce.http.fetch = original_fetch
        parse_log.removeHandler(handler)
        parse_log.setLevel(prev_level)
        parse_log.propagate = prev_propagate

    messages = [r.getMessage() for r in records]
    assert any("/acropora/" in m and "below per-category floor" in m for m in messages), (
        f"expected per-cat WARN before bottom-guard raise; got: {messages}"
    )
    assert raised_schema, "no-marker zero-cards must raise SchemaChangeError"
    assert "zero items" in raise_msg and "all category_paths" in raise_msg, (
        f"raise must come from the all-empty bottom guard; got: {raise_msg}"
    )


# ─── Test 32: multi-category partial undershoot WARN (F3 load-bearing) ───────
def test_expected_min_per_category_warns_only_on_undershoot_when_siblings_healthy():
    """F3 load-bearing scenario per /lead-backend /code-review disposition.
    The Session 7 WARN downgrade's actual production load-path is multi-
    category: 1 of 21 buckets undershoots while siblings stay healthy. The
    all-categories-empty bottom guard does NOT fire (siblings backfill
    `items`). The per-cat WARN is the ONLY signal for partial-bucket drift —
    test that it fires for the undershooting category, does NOT fire for
    healthy siblings, all items persist, and no raise. Pins the heuristic
    against a future refactor that drops L139-148."""
    import logging
    original_fetch = parse_bigcommerce.http.fetch
    short_body = _load("clearance_p1.sample.html")  # 1 card, no marker
    healthy_body = _load("acropora_p1.sample.html")  # 5 cards

    def stub_fetch(url, request_delay_sec=2.0):
        cat = url.split("aquasd.com")[1].split("?")[0]
        if "page=1" in url:
            if cat == "/short/":
                return FetchResult(body=short_body, status_code=200, error_class=None, error_message=None)
            if cat == "/healthy/":
                return FetchResult(body=healthy_body, status_code=200, error_class=None, error_message=None)
        return FetchResult(body=None, status_code=404, error_class="other", error_message="HTTP 404")

    parse_log = logging.getLogger("scrapers.common.parse_bigcommerce")
    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = _Capture(level=logging.WARNING)
    parse_log.addHandler(handler)
    prev_level = parse_log.level
    prev_propagate = parse_log.propagate
    parse_log.setLevel(logging.WARNING)
    parse_log.propagate = False
    parse_bigcommerce.http.fetch = stub_fetch
    try:
        config = {
            "base_url": "https://aquasd.com",
            "category_paths": ["/short/", "/healthy/"],
            "max_pages": 3,
            "request_delay_sec": 0,
            "expected_min_per_category": 3,  # mirrors production aquasd.yaml floor
        }
        result = fetch_and_parse(config)
    finally:
        parse_bigcommerce.http.fetch = original_fetch
        parse_log.removeHandler(handler)
        parse_log.setLevel(prev_level)
        parse_log.propagate = prev_propagate

    assert len(result.items) == 6, (
        f"healthy sibling + undershooting category items must both persist; got {len(result.items)}"
    )
    messages = [r.getMessage() for r in records]
    short_warns = [m for m in messages if "/short/" in m and "below per-category floor" in m]
    healthy_warns = [m for m in messages if "/healthy/" in m and "below per-category floor" in m]
    assert len(short_warns) == 1, (
        f"WARN must fire exactly once for /short/; got: {messages}"
    )
    assert len(healthy_warns) == 0, (
        f"healthy sibling must not WARN; got: {messages}"
    )


# ─── Test 33: WARN message preserves threshold parameter (F8 parametric pin) ──
def test_expected_min_per_category_warn_names_configured_threshold():
    """F8: pins the heuristic against a refactor that drops field-read and
    inlines a constant. Uses a non-production threshold (7) so the WARN
    message ('expected ≥7') would fail to materialize if the code stopped
    reading the YAML field. 1 card under threshold=7 fires WARN."""
    import logging
    original_fetch = parse_bigcommerce.http.fetch
    clearance_body = _load("clearance_p1.sample.html")  # 1 card, no marker

    def stub_fetch(url, request_delay_sec=2.0):
        if "page=1" in url:
            return FetchResult(body=clearance_body, status_code=200, error_class=None, error_message=None)
        return FetchResult(body=None, status_code=404, error_class="other", error_message="HTTP 404")

    parse_log = logging.getLogger("scrapers.common.parse_bigcommerce")
    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = _Capture(level=logging.WARNING)
    parse_log.addHandler(handler)
    prev_level = parse_log.level
    prev_propagate = parse_log.propagate
    parse_log.setLevel(logging.WARNING)
    parse_log.propagate = False
    parse_bigcommerce.http.fetch = stub_fetch
    try:
        config = {
            "base_url": "https://aquasd.com",
            "category_paths": ["/clearance/"],
            "max_pages": 3,
            "request_delay_sec": 0,
            "expected_min_per_category": 7,  # non-production; pins parametricity
        }
        result = fetch_and_parse(config)
    finally:
        parse_bigcommerce.http.fetch = original_fetch
        parse_log.removeHandler(handler)
        parse_log.setLevel(prev_level)
        parse_log.propagate = prev_propagate

    assert len(result.items) == 1, "item must persist under WARN"
    messages = [r.getMessage() for r in records]
    assert any("expected ≥7" in m for m in messages), (
        f"WARN must echo configured threshold (7), not a hardcoded value; got: {messages}"
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
