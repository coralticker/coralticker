"""scrapers/tests/test_parse_shopify_compare_at_price.py — CTK-100 Wave-1
compare_at_price capture tests for Shopify (9-of-11 vendors).

Parse-only — no DB, no network. Four cases per plan §2.1 final paragraph:
  (1) variant with valid compare_at_price > price                → captures
  (2) variant with compare_at_price <= price                     → nulls (L2 stale)
  (3) variant with no compare_at_price field                     → nulls
  (4) auction listing (auction_detection tag match)              → nulls regardless
      of compare_at presence (L4 structural via current_price=None)

Cases 1-3 unit-test `normalize.coerce_compare_at_price` directly — the L2
cleanup and missing-field discrimination live entirely in the helper, no
benefit from routing through fetch_and_parse. Case 4 end-to-end-tests
through fetch_and_parse + _is_auction so the L4 structural carve-out
(auction null-out at parse_shopify.py:437-439 sequences BEFORE the
coerce_compare_at_price call at the next line) is verified at the
actual integration site, not at the helper alone.

Runnable as:
  python -m scrapers.tests.test_parse_shopify_compare_at_price
"""

from __future__ import annotations

import json
import sys
import traceback
from decimal import Decimal

from scrapers.common import normalize, parse_shopify
from scrapers.common.http import FetchResult


# --- Cases 1-3: unit tests on normalize.coerce_compare_at_price ---

def test_valid_compare_at_captures():
    """Case 1: variant with valid compare_at_price > current_price captures.
    The 'happy path' — vendor marked an item from $100 down to $80 and the
    compare_at_price field carries the original $100 reference."""
    variants = [{"sku": "X", "available": True, "price": "80.00", "compare_at_price": "100.00"}]
    current_price = Decimal("80.00")
    result = normalize.coerce_compare_at_price(variants, current_price)
    assert result == Decimal("100.00"), f"expected Decimal('100.00'); got {result!r}"


def test_stale_compare_at_nulls():
    """Case 2: variant with compare_at_price <= current_price nulls per L2.
    Vendors leave stale compare-at values populated after a sale ends
    (Shopify's compare_at_price field doesn't auto-clear). The parse-side
    null-out keeps invalid rows out of the DB entirely — no render guard,
    no read-side branching needed.

    Three sub-cases pin the boundary:
      (a) strictly less than current — typical stale-clear-incomplete shape
      (b) equal to current — zero-percent-off no-op (vendor set both equal)
      (c) zero (compare_at_price='0.00' is a Shopify default for un-set)
    """
    current_price = Decimal("80.00")
    # (a) strictly less
    less = [{"price": "80.00", "compare_at_price": "60.00"}]
    assert normalize.coerce_compare_at_price(less, current_price) is None
    # (b) equal
    equal = [{"price": "80.00", "compare_at_price": "80.00"}]
    assert normalize.coerce_compare_at_price(equal, current_price) is None
    # (c) zero (treated as missing via the (None, "", "0.00") guard)
    zero = [{"price": "80.00", "compare_at_price": "0.00"}]
    assert normalize.coerce_compare_at_price(zero, current_price) is None


def test_no_compare_at_field_nulls():
    """Case 3: variant with no compare_at_price field nulls.
    Most non-sale Shopify items don't carry the field at all (or carry it
    as None). Helper returns None without raising.

    Sub-cases: field absent, field=None, field="" (Shopify sometimes
    emits the field as an empty string instead of omitting it)."""
    current_price = Decimal("80.00")
    # Field absent entirely
    absent = [{"price": "80.00"}]
    assert normalize.coerce_compare_at_price(absent, current_price) is None
    # Field present as None
    null = [{"price": "80.00", "compare_at_price": None}]
    assert normalize.coerce_compare_at_price(null, current_price) is None
    # Field present as empty string
    empty = [{"price": "80.00", "compare_at_price": ""}]
    assert normalize.coerce_compare_at_price(empty, current_price) is None


# --- Case 4: end-to-end through fetch_and_parse for L4 auction carve-out ---

def test_auction_listing_nulls_compare_at_regardless():
    """Case 4: auction listing (auction_detection tag match) nulls
    compare_at_price regardless of source DOM. L4 structural — auction
    detection nulls current_price at parse_shopify.py:437-439; the
    coerce_compare_at_price call sequenced immediately after returns None
    via its `current_price is None` guard. Tests through fetch_and_parse
    end-to-end so the integration site (sequence: coerce_price →
    auction-null-out → coerce_compare_at_price) is verified.

    Fixture carries three products to cover the cross-case matrix:
      (A) auction with synthetic compare_at_price → compare_at_price = None
          AND current_price = None (auction null-out)
      (B) non-auction with valid compare_at > price → compare_at_price captured
      (C) non-auction without compare_at → compare_at_price = None
    """
    fixture = {
        "products": [
            # (A) Auction row: tag triggers auction_detection, vendor populated
            # compare_at_price too (synthetic — real auctions wouldn't, but
            # this is the L4 structural pin: even if they DID, compare_at
            # MUST null because current_price nulled).
            {
                "id": 101,
                "handle": "auction-with-compare-at",
                "title": "Auction Coral — bid trajectory",
                "product_type": "live sale",
                "tags": ["auction"],
                "variants": [{"sku": "AUC-1", "available": True, "price": "150.00", "compare_at_price": "300.00"}],
                "images": [],
            },
            # (B) Non-auction marked-down row: standard markdown capture.
            {
                "id": 102,
                "handle": "marked-down-coral",
                "title": "TSA Candy Crush Scolymia",
                "product_type": "live sale",
                "tags": ["lps"],
                "variants": [{"sku": "TSA-CC-1", "available": True, "price": "849.99", "compare_at_price": "934.99"}],
                "images": [],
            },
            # (C) Non-auction full-price row: compare_at absent.
            {
                "id": 103,
                "handle": "full-price-coral",
                "title": "Battlecorals Ferrari Acan",
                "product_type": "live sale",
                "tags": ["lps"],
                "variants": [{"sku": "BC-F-1", "available": True, "price": "200.00"}],
                "images": [],
            },
        ]
    }

    original_fetch = parse_shopify.http.fetch
    served = {1: False}

    def stub_fetch(url, request_delay_sec=2.0):
        if "page=1" in url and not served[1]:
            served[1] = True
            return FetchResult(
                body=json.dumps(fixture).encode("utf-8"),
                status_code=200,
                error_class=None,
                error_message=None,
            )
        return FetchResult(
            body=json.dumps({"products": []}).encode("utf-8"),
            status_code=200,
            error_class=None,
            error_message=None,
        )

    parse_shopify.http.fetch = stub_fetch
    try:
        config = {
            "base_url": "https://example-vendor.com",
            "products_path": "/products.json",
            "page_size": 250,
            "max_pages": 3,
            "request_delay_sec": 0,
            # CTK-041 auction detection: tag-set match nulls current_price.
            "auction_detection": {"tags": ["auction"]},
            "image_strategy": "mirror",
        }
        result = parse_shopify.fetch_and_parse(config)
    finally:
        parse_shopify.http.fetch = original_fetch

    by_handle = {
        item["product_url"].rsplit("/", 1)[-1]: item
        for item in result.items
    }

    # (A) Auction row: current_price=None (auction null-out) AND
    # compare_at_price=None (L4 structural via the helper's None-guard).
    auction = by_handle["auction-with-compare-at"]
    assert auction["current_price"] is None, (
        f"auction row must have current_price=None per CTK-041 null-out; "
        f"got {auction['current_price']!r}"
    )
    assert auction["compare_at_price"] is None, (
        f"auction row must have compare_at_price=None per L4 structural "
        f"(current_price-None guard); got {auction['compare_at_price']!r}. "
        f"This pin guards against a regression that calls "
        f"coerce_compare_at_price BEFORE the auction null-out."
    )

    # (B) Marked-down row: captures the markdown.
    marked = by_handle["marked-down-coral"]
    assert marked["current_price"] == Decimal("849.99"), (
        f"got current_price={marked['current_price']!r}"
    )
    assert marked["compare_at_price"] == Decimal("934.99"), (
        f"marked-down row must capture compare_at_price=Decimal('934.99'); "
        f"got {marked['compare_at_price']!r}"
    )

    # (C) Full-price row: compare_at absent in source → None at output.
    full = by_handle["full-price-coral"]
    assert full["current_price"] == Decimal("200.00")
    assert full["compare_at_price"] is None, (
        f"full-price row (no compare_at_price field) must null; "
        f"got {full['compare_at_price']!r}"
    )


# --- F1 pair-discipline pins (Wave-1.5 /code-review fold 2026-06-01) ---

def test_heterogeneous_variants_pair_compare_at_with_chosen_variant():
    """F1 phantom-markdown regression pin. Pre-fix the helper walked all
    variants looking for any non-empty compare_at, which paired
    variant[1]'s compare_at with variant[0]'s price on multi-variant
    frags. Post-fix the helper consults ONLY the variant coerce_price
    chose (variant[0] here, since variant[0]'s price is non-empty and
    parseable). variant[0] has no compare_at → None."""
    variants = [
        {"sku": "A", "available": True, "price": "80.00"},
        {"sku": "B", "available": True, "price": "50.00", "compare_at_price": "100.00"},
    ]
    # current_price comes from coerce_price(variants) which picks variant[0]'s '80.00'.
    current_price = Decimal("80.00")
    result = normalize.coerce_compare_at_price(variants, current_price)
    assert result is None, (
        f"heterogeneous-variant must NOT pull variant[1]'s compare_at when "
        f"variant[0] is the chosen-price variant; got {result!r} (pre-fix "
        f"shape would return Decimal('100.00') — phantom markdown)"
    )


def test_stale_then_valid_variants_stop_at_chosen():
    """F1 walk-discipline pin. variant[0] has a stale compare_at
    ($60 <= $80); variant[1] has a valid compare_at ($100 > $80). The
    chosen variant under coerce_price is variant[0] (first non-empty
    price), so the helper consults variant[0]'s compare_at — L2 stale —
    nulls. variant[1] is never read. Pre-fix the helper also returned
    None here, but via L2-early-return-after-skipping-empty (different
    mechanism); post-fix the mechanism is pair-discipline. Behavior
    parity, different reason — this pin guards against a future
    refactor that "fixes" L2 by walking forward to later variants."""
    variants = [
        {"sku": "A", "available": True, "price": "80.00", "compare_at_price": "60.00"},
        {"sku": "B", "available": True, "price": "80.00", "compare_at_price": "100.00"},
    ]
    current_price = Decimal("80.00")
    result = normalize.coerce_compare_at_price(variants, current_price)
    assert result is None, (
        f"stale-then-valid must null at variant[0]'s L2-stale compare_at; "
        f"got {result!r}. variant[1]'s valid compare_at is structurally "
        f"unreachable post-F1 (pair-discipline) and that's the invariant."
    )


def test_nan_compare_at_does_not_crash():
    """F2 NaN-guard pin. Decimal accepts 'NaN' as a literal, but
    NaN-comparison (NaN > Decimal('80.00')) raises InvalidOperation
    outside the parse try/except — pre-fix this would take out the
    whole scrape on any vendor row carrying compare_at_price='NaN'.
    Post-fix the is_finite() guard returns None silently. Also covers
    Infinity / -Infinity / sNaN by the same predicate."""
    for bad_value in ("NaN", "Infinity", "-Infinity", "sNaN"):
        variants = [{"sku": "X", "available": True, "price": "80.00", "compare_at_price": bad_value}]
        current_price = Decimal("80.00")
        # Must not raise.
        result = normalize.coerce_compare_at_price(variants, current_price)
        assert result is None, (
            f"compare_at_price={bad_value!r} must null silently; got {result!r}"
        )


# --- F15 clamp pins (Wave-2 fold 2026-06-01) ---

def test_clamp_billion_dollar_typo_nulls():
    """F15 — vendor typo (compare_at_price='100000000.00' = 1e8) → None.
    Without the clamp, the typo parses as a finite Decimal, passes L2
    (> current_price), and writes to numeric(10,2) which raises
    NumericValueOutOfRange mid-batch — taking out the whole scrape.
    Clamp predicate `value >= Decimal("100000000")` returns None
    silently. Same shape mirrored at parse_bigcommerce + tidal_gardens
    helpers."""
    variants = [{"sku": "X", "available": True, "price": "80.00", "compare_at_price": "100000000.00"}]
    result = normalize.coerce_compare_at_price(variants, Decimal("80.00"))
    assert result is None, f"clamp should null at 1e8; got {result!r}"
    # And the worst-case typo — what a real billion-dollar misclick looks like
    variants = [{"sku": "X", "available": True, "price": "80.00", "compare_at_price": "99999999999.99"}]
    result = normalize.coerce_compare_at_price(variants, Decimal("80.00"))
    assert result is None, f"clamp should null at ~1e11; got {result!r}"


def test_clamp_boundary_just_under_overflow_captures():
    """F15 boundary — '99999999.99' (numeric(10,2) max) MUST capture,
    not null. Pins the boundary so the clamp predicate doesn't drift to
    `>` instead of `>=` and accidentally widen the silent-null window."""
    variants = [{"sku": "X", "available": True, "price": "80.00", "compare_at_price": "99999999.99"}]
    result = normalize.coerce_compare_at_price(variants, Decimal("80.00"))
    assert result == Decimal("99999999.99"), f"boundary value must capture; got {result!r}"


# --- Bonus: ensure current_price=None alone (price-on-request) nulls compare_at ---

def test_current_price_none_nulls_compare_at():
    """Defensive pin: when current_price is None at the call site (price-
    on-request: JF event drops, TSA cut-to-order), compare_at_price MUST
    null too. The helper's `current_price is None` guard at the top
    enforces this; this test pins the contract so a future refactor that
    reorders the guard doesn't silently capture a compare_at on a row
    whose current_price is null (which would render as "was $X, now —"
    on the listing card — incoherent shape)."""
    variants = [{"price": "0.00", "compare_at_price": "100.00"}]
    result = normalize.coerce_compare_at_price(variants, current_price=None)
    assert result is None


def main() -> int:
    tests = [
        test_valid_compare_at_captures,
        test_stale_compare_at_nulls,
        test_no_compare_at_field_nulls,
        test_auction_listing_nulls_compare_at_regardless,
        test_heterogeneous_variants_pair_compare_at_with_chosen_variant,
        test_stale_then_valid_variants_stop_at_chosen,
        test_nan_compare_at_does_not_crash,
        test_clamp_billion_dollar_typo_nulls,
        test_clamp_boundary_just_under_overflow_captures,
        test_current_price_none_nulls_compare_at,
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
