"""scrapers/tests/test_ctk160_auction_keep_override.py — CTK-160 Option B
auction-keep override.

Parse-only — no DB; the integration test monkeypatches http.fetch (no network).
Pins the writer-side fix for the deceptive-buy-price defect: an _is_auction
product whose product_type misses the coral allowlist (the real WWC shape,
product_type='WWC Auction') is KEPT and price-nulled instead of stranded.

Root cause it guards (diagnosed live 2026-06-15): the 4 WWC auction rows were
rejected at intake by product_type_allowlist (`_should_keep=False`), so they
never reached _normalize_product (CTK-041 null-out never ran) OR diff.classify,
and cohort-OOS skips filtered URLs — freezing them in_stock at a stale buy-price.
The override bypasses the coral-gate (allowlist) for auctions but keeps the
junk-gate (denylists) + availability gate.

Reuses the real _is_auction / _should_keep / _normalize_product / fetch_and_parse
predicates (no fork).

Runnable as:
  python -m scrapers.tests.test_ctk160_auction_keep_override
"""

from __future__ import annotations

import json
import sys
import traceback
from decimal import Decimal

from scrapers.common import parse_shopify
from scrapers.common.http import FetchResult
from scrapers.common.parse_shopify import (
    _build_auction_keep_filter,
    _normalize_product,
    _should_keep,
    _should_keep_with_auction_override,
    fetch_and_parse,
)

BASE = "https://example-reef.com"

# Minimal WWC-shaped config: a coral allowlist (the coral-gate), denylists (the
# junk-gate), and auction_detection. 'WWC Auction' is deliberately NOT in the
# allowlist — the real live shape that strands auctions.
CATEGORY_FILTER = {
    "product_type_allowlist": ["Frag", "WYSIWYG Frag"],
    "tag_denylist": ["Dry Goods"],
    "title_denylist": ["Chaeto"],
    "title_denylist_prefix": ["WS - "],
}
AUCTION_DETECTION = {"tags": ["Auction", "active_bidding", "on_auction"], "slug_suffix": "-auc"}
AKF = _build_auction_keep_filter(CATEGORY_FILTER)


def _p(title="Rainbow Acro", product_type="Frag", tags=None, handle="rainbow-acro",
       available=True, price="100.00") -> dict:
    return {
        "title": title,
        "product_type": product_type,
        "tags": tags or [],
        "handle": handle,
        "variants": [{"available": available, "price": price}],
        "images": [],
    }


# (a) the primary new guard — auction with a non-allowlisted product_type is KEPT
def test_override_keeps_auction_non_allowlisted_pt():
    p = _p(product_type="WWC Auction", tags=["Auction"])
    # Normal gate rejects (PT not in the coral allowlist) — the strand cause.
    assert _should_keep(p, CATEGORY_FILTER) is False
    # Override keeps it (auction bypasses the coral-gate).
    assert _should_keep_with_auction_override(p, CATEGORY_FILTER, AUCTION_DETECTION, AKF) is True


# (a, price half) the kept auction is price-nulled in _normalize_product
def test_override_kept_auction_price_nulled():
    p = _p(product_type="WWC Auction", tags=["Auction"], price="599.00")
    out = _normalize_product(p, BASE, "mirror", "wwc", AUCTION_DETECTION)
    assert out["current_price"] is None, f"auction price not nulled: {out['current_price']!r}"


# (b) junk-gate intact — an auction caught by a denylist is DROPPED
def test_override_drops_denylisted_auction_by_tag():
    p = _p(product_type="WWC Auction", tags=["Auction", "Dry Goods"])
    assert _should_keep_with_auction_override(p, CATEGORY_FILTER, AUCTION_DETECTION, AKF) is False


def test_override_drops_denylisted_auction_by_title():
    p = _p(title="Chaeto Auction Lot", product_type="WWC Auction", tags=["Auction"])
    assert _should_keep_with_auction_override(p, CATEGORY_FILTER, AUCTION_DETECTION, AKF) is False


# (c) no allowlist regression — a non-auction non-allowlisted product still DROPS
def test_override_drops_non_auction_non_allowlisted():
    p = _p(product_type="Fish", tags=["Fish"])
    assert _should_keep_with_auction_override(p, CATEGORY_FILTER, AUCTION_DETECTION, AKF) is False


# no-op when unconfigured — without auction_detection the override never fires
def test_override_noop_when_auction_detection_unconfigured():
    p = _p(product_type="WWC Auction", tags=["Auction"])
    assert _should_keep_with_auction_override(p, CATEGORY_FILTER, None, None) is False


# the override keeps the availability gate (a sold-out auction under in_stock_only drops)
def test_override_keeps_availability_gate():
    p = _p(product_type="WWC Auction", tags=["Auction"], available=False)
    assert _should_keep_with_auction_override(
        p, CATEGORY_FILTER, AUCTION_DETECTION, AKF, in_stock_only=True
    ) is False


# a non-allowlisted product that is NOT an auction is unaffected even when the
# override is active for the vendor (proves the auction predicate is the gate)
def test_override_only_applies_to_auctions():
    non_auction = _p(product_type="WWC Auction", tags=["LPS"])  # 'WWC Auction' PT but no auction tag
    assert parse_shopify._is_auction(non_auction, AUCTION_DETECTION) is False
    assert _should_keep_with_auction_override(non_auction, CATEGORY_FILTER, AUCTION_DETECTION, AKF) is False


# (d) integration — kept auction reaches items + is nulled + is NOT in
# filtered_urls (the cohort-absent-set reach that gives it a real OOS lifecycle)
def test_fetch_and_parse_auction_kept_nulled_and_not_filtered():
    products = [
        _p(title="Fire Nova Acan", product_type="WWC Auction", tags=["Auction"],
           handle="fire-nova-auc", price="599.00"),
        _p(title="Normal Coral", product_type="Frag", tags=[], handle="normal-coral", price="50.00"),
        _p(title="Yellow Tang", product_type="Fish", tags=["Fish"], handle="yellow-tang"),
    ]
    bodies = [
        json.dumps({"products": products}).encode("utf-8"),
        json.dumps({"products": []}).encode("utf-8"),
    ]
    calls = {"n": 0}

    def fake_fetch(url, request_delay_sec=0.0):
        i = min(calls["n"], len(bodies) - 1)
        calls["n"] += 1
        return FetchResult(bodies[i], 200, None, None)

    orig = parse_shopify.http.fetch
    parse_shopify.http.fetch = fake_fetch
    try:
        cfg = {
            "base_url": BASE,
            "products_path": "/products.json",
            "image_strategy": "mirror",
            "originator_prefix": "wwc",
            "category_filter": CATEGORY_FILTER,
            "auction_detection": AUCTION_DETECTION,
        }
        res = fetch_and_parse(cfg)
    finally:
        parse_shopify.http.fetch = orig

    by_url = {it["product_url"]: it for it in res.items}
    auc_url = f"{BASE}/products/fire-nova-auc"
    coral_url = f"{BASE}/products/normal-coral"
    fish_url = f"{BASE}/products/yellow-tang"

    # auction kept, price nulled, NOT filtered (reaches the cohort absent-set)
    assert auc_url in by_url, "auction not kept by fetch_and_parse"
    assert by_url[auc_url]["current_price"] is None, "kept auction price not nulled"
    assert auc_url not in res.filtered_urls, "auction in filtered_urls — would skip cohort-OOS (the freeze)"
    # normal coral kept with its real price (no collateral)
    assert coral_url in by_url and by_url[coral_url]["current_price"] == Decimal("50.00")
    # non-auction non-allowlisted still filtered (no allowlist regression)
    assert fish_url not in by_url and fish_url in res.filtered_urls


def main() -> int:
    tests = [
        test_override_keeps_auction_non_allowlisted_pt,
        test_override_kept_auction_price_nulled,
        test_override_drops_denylisted_auction_by_tag,
        test_override_drops_denylisted_auction_by_title,
        test_override_drops_non_auction_non_allowlisted,
        test_override_noop_when_auction_detection_unconfigured,
        test_override_keeps_availability_gate,
        test_override_only_applies_to_auctions,
        test_fetch_and_parse_auction_kept_nulled_and_not_filtered,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  [PASS] {t.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  [FAIL] {t.__name__}: {e}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
