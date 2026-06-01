"""scrapers/tests/test_parse_bigcommerce_compare_at_price.py — CTK-100 Wave-2
BC Stencil compare_at_price capture tests (AquaSD).

Parse-only — no DB, no network. Five cases per directive + plan W2-§A:
  (a) present .price--non-sale with valid $100.00 markdown > current → captures
  (b) .price--non-sale missing → None
  (c) .price--non-sale populated but <= current_price → None (L2 stale)
  (d) auction-path row with markdown → None (L4 via current_price=None at call site)
  (e) billion-dollar typo '100000000.00' → None (F15 clamp)

Cases (a/b/c/e) unit-test `_extract_compare_at_price` directly — pure
helper-level logic, no benefit from routing through fetch_and_parse.
Case (d) end-to-end-tests through fetch_and_parse + _is_auction_category
so the L4 structural carve-out (auction null-out at parse_bigcommerce.py
sequences BEFORE the compare_at extraction at the next line) is
verified at the actual integration site.

Wave-2 audit (2026-06-01) found zero live marked-downs on AquaSD across
786 cards × 21 genus paths; populated text format `$XX.XX` per BC
Stencil convention is inferred (operator runbook trigger watches for
first non-NULL compare_at_price write on vendor_id=aquasd). Synthetic
HTML below uses the anticipated `$XX.XX` shape; if the live populated
format differs, this test module is the first line of regression
defense.

Runnable as:
  python -m scrapers.tests.test_parse_bigcommerce_compare_at_price
"""

from __future__ import annotations

import json
import sys
import traceback
from decimal import Decimal

from bs4 import BeautifulSoup

from scrapers.common import parse_bigcommerce
from scrapers.common.http import FetchResult
from scrapers.common.parse_bigcommerce import _extract_compare_at_price


def _card_with_non_sale(non_sale_text: str | None) -> BeautifulSoup:
    """Build a synthetic BC Stencil card with the minimum DOM the helper
    inspects — .price--non-sale optional. None = element absent; "" =
    empty-shell span (the dominant audit-time shape); "$XX.XX" =
    populated markdown."""
    if non_sale_text is None:
        # Element absent entirely
        html = '<li class="product"><article></article></li>'
    else:
        html = (
            '<li class="product"><article>'
            f'<span class="price price--non-sale">{non_sale_text}</span>'
            "</article></li>"
        )
    return BeautifulSoup(html, "html.parser").select_one("li.product")


# --- Cases a/b/c/e — unit tests on _extract_compare_at_price ---

def test_a_populated_non_sale_captures():
    """(a) Card with `.price--non-sale` populated as "$100.00" and
    current_price=Decimal("80.00") → captures Decimal("100.00"). Mirrors
    the W2-§A audit's anticipated populated shape (BC Stencil
    convention)."""
    card = _card_with_non_sale("$100.00")
    result = _extract_compare_at_price(card, Decimal("80.00"))
    assert result == Decimal("100.00"), f"expected Decimal('100.00'); got {result!r}"


def test_b_missing_non_sale_returns_none():
    """(b) Card without a `.price--non-sale` element at all → None.
    Synthetic mirror of the audit-time dominant case (zero live
    marked-downs)."""
    card = _card_with_non_sale(None)
    result = _extract_compare_at_price(card, Decimal("80.00"))
    assert result is None, f"expected None on missing selector; got {result!r}"


def test_b_empty_non_sale_returns_none():
    """(b-variant) Card WITH `.price--non-sale` element but empty text
    (the audit-time dominant case — empty-shell span). Returns None."""
    card = _card_with_non_sale("")
    result = _extract_compare_at_price(card, Decimal("80.00"))
    assert result is None, f"expected None on empty-shell span; got {result!r}"


def test_c_stale_non_sale_returns_none():
    """(c) `.price--non-sale` populated but <= current_price → None
    (L2 stale). Three sub-cases pin the boundary: less / equal /
    zero — same shape as the Shopify Wave-1 tests."""
    current_price = Decimal("80.00")
    # less than
    card = _card_with_non_sale("$60.00")
    assert _extract_compare_at_price(card, current_price) is None
    # equal
    card = _card_with_non_sale("$80.00")
    assert _extract_compare_at_price(card, current_price) is None
    # zero
    card = _card_with_non_sale("$0.00")
    assert _extract_compare_at_price(card, current_price) is None


def test_strip_handles_thousands_separator_and_whitespace():
    """Sanity pin on the strip-and-parse sequence — BC convention may
    locale-format larger values as `$1,234.56`. Strip leading `$` + `,`
    + surrounding whitespace before Decimal parse. Operator runbook
    note: if the populated text format diverges further (e.g., locale
    suffix), this test pins the current strip set so a regression
    fails LOUD instead of silently dropping markdown."""
    card = _card_with_non_sale("  $1,234.56  ")
    result = _extract_compare_at_price(card, Decimal("999.99"))
    assert result == Decimal("1234.56"), f"got {result!r}"


def test_current_price_none_returns_none():
    """L4 — current_price is None (auction null-out OR price-on-request)
    short-circuits at the top, regardless of source DOM."""
    card = _card_with_non_sale("$100.00")
    result = _extract_compare_at_price(card, current_price=None)
    assert result is None


def test_e_clamp_billion_dollar_typo_nulls():
    """(e) F15 — vendor typo (`$100000000.00` = 1e8) → None.
    numeric(10,2) max = 99999999.99 (10^8 - 0.01); the clamp predicate
    `value >= Decimal("100000000")` returns None to prevent
    NumericValueOutOfRange at UPSERT."""
    card = _card_with_non_sale("$100000000.00")
    result = _extract_compare_at_price(card, Decimal("80.00"))
    assert result is None, f"clamp should null at 1e8; got {result!r}"


def test_clamp_boundary_just_under_overflow_captures():
    """F15 boundary — `$99999999.99` (numeric(10,2) max) MUST capture,
    not null. Pins the boundary so the clamp predicate doesn't drift to
    `>` instead of `>=` and accidentally widen the silent-null window."""
    card = _card_with_non_sale("$99999999.99")
    result = _extract_compare_at_price(card, Decimal("80.00"))
    assert result == Decimal("99999999.99"), f"boundary value must capture; got {result!r}"


def test_non_finite_nan_does_not_crash():
    """F2 (Wave-1.5 carried) — text like '$NaN' parses as NaN Decimal;
    the is_finite() guard returns None silently. Also covers Infinity
    via the same predicate."""
    for bad_text in ("$NaN", "$Infinity", "$-Infinity"):
        card = _card_with_non_sale(bad_text)
        result = _extract_compare_at_price(card, Decimal("80.00"))
        assert result is None, f"text={bad_text!r} should null silently; got {result!r}"


# --- Case d — end-to-end through fetch_and_parse for L4 auction carve-out ---

def test_d_auction_path_nulls_compare_at_regardless():
    """(d) Auction-category-path row with synthetic compare_at-populated
    DOM → compare_at_price = None at items-dict output.
    parse_bigcommerce.py:367-368 nulls current_price for auction-path
    rows; _extract_compare_at_price (called immediately after) returns
    None via its current_price-None guard. Tests through fetch_and_parse
    end-to-end so the call-order at the integration site is the
    load-bearing assertion.

    Synthetic Stencil category HTML — one card with a populated
    .price--non-sale on a path that auction_detection.category_paths
    matches → null. A second card on a non-auction path captures
    normally — same matrix shape as the Shopify Wave-1 auction test."""

    # Build minimal Stencil category page HTML — one card per page.
    def category_html(path: str, card_price: str, non_sale_text: str | None) -> bytes:
        non_sale_span = (
            f'<span class="price price--non-sale">{non_sale_text}</span>'
            if non_sale_text is not None
            else ""
        )
        html = f"""
        <html><body>
          <ul class="productGrid">
            <li class="product">
              <article data-name="Test Coral on {path}" data-product-price="{card_price}" data-product-category="lps">
                <a class="card-figure__link" href="https://example-vendor.com{path}test-coral">link</a>
                <img class="card-image" src="https://example.com/img.jpg" />
                {non_sale_span}
                <span class="price price--withTax">${card_price}</span>
              </article>
            </li>
          </ul>
        </body></html>
        """
        return html.encode("utf-8")

    # Stub the fetcher to serve per-path bodies.
    served_pages: dict[tuple[str, int], bool] = {}
    fixtures = {
        "/auction/": ("100.00", "$200.00"),  # auction path; even with populated non-sale, expect null
        "/lps/": ("80.00", "$100.00"),       # non-auction path with markdown; expect capture
    }

    def stub_fetch(url, request_delay_sec=2.0):
        # Identify which path was requested + which page.
        for path in fixtures:
            if path in url:
                page = 1 if "?page=1" in url else 2
                key = (path, page)
                if served_pages.get(key):
                    # Already served — return empty terminator.
                    return FetchResult(body=b"<html><body></body></html>", status_code=404, error_class=None, error_message=None)
                served_pages[key] = True
                if page == 1:
                    card_price, non_sale = fixtures[path]
                    return FetchResult(
                        body=category_html(path, card_price, non_sale),
                        status_code=200,
                        error_class=None,
                        error_message=None,
                    )
                # page 2 — empty terminator (404 per BC convention)
                return FetchResult(body=b"", status_code=404, error_class=None, error_message=None)
        return FetchResult(body=b"", status_code=404, error_class=None, error_message=None)

    original_fetch = parse_bigcommerce.http.fetch
    parse_bigcommerce.http.fetch = stub_fetch
    try:
        config = {
            "base_url": "https://example-vendor.com",
            "category_paths": ["/auction/", "/lps/"],
            "pagination": "?page={n}",
            "max_pages": 2,
            "request_delay_sec": 0,
            "expected_min_per_category": 0,
            # Auction-detection by literal category path (BC convention)
            "auction_detection": {"category_paths": ["/auction/"]},
        }
        result = parse_bigcommerce.fetch_and_parse(config)
    finally:
        parse_bigcommerce.http.fetch = original_fetch

    by_path_token = {}
    for item in result.items:
        # Group by which fixture path the product_url hints at
        for path in fixtures:
            if path in item["product_url"]:
                by_path_token[path] = item
                break

    # Auction path: current_price=None AND compare_at_price=None (L4 structural)
    auction = by_path_token.get("/auction/")
    assert auction is not None, f"auction-path item missing; items={[i['product_url'] for i in result.items]}"
    assert auction["current_price"] is None, (
        f"auction-path row must have current_price=None (auction null-out at "
        f"parse_bigcommerce.py:367-368); got {auction['current_price']!r}"
    )
    assert auction["compare_at_price"] is None, (
        f"auction-path row must have compare_at_price=None (L4 structural via "
        f"_extract_compare_at_price's current_price-None guard); got "
        f"{auction['compare_at_price']!r}"
    )

    # Non-auction marked-down path: captures
    lps = by_path_token.get("/lps/")
    assert lps is not None, f"lps-path item missing; items={[i['product_url'] for i in result.items]}"
    assert lps["current_price"] == Decimal("80.00"), f"got {lps['current_price']!r}"
    assert lps["compare_at_price"] == Decimal("100.00"), (
        f"marked-down lps row must capture Decimal('100.00'); got "
        f"{lps['compare_at_price']!r}"
    )


def main() -> int:
    tests = [
        test_a_populated_non_sale_captures,
        test_b_missing_non_sale_returns_none,
        test_b_empty_non_sale_returns_none,
        test_c_stale_non_sale_returns_none,
        test_strip_handles_thousands_separator_and_whitespace,
        test_current_price_none_returns_none,
        test_e_clamp_billion_dollar_typo_nulls,
        test_clamp_boundary_just_under_overflow_captures,
        test_non_finite_nan_does_not_crash,
        test_d_auction_path_nulls_compare_at_regardless,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL  {t.__name__}")
            traceback.print_exc()
    total = len(tests)
    print(f"\n{total - failed}/{total} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
