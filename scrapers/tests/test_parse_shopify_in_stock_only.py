"""scrapers/tests/test_parse_shopify_in_stock_only.py — CTK-088
parse_shopify._should_keep in_stock_only availability-gate tests.

Parse-only — no DB, no network. Validates the in_stock_only opt-in gate
added to _should_keep for vendors whose catalog is a permanent archive of
mostly sold-out items (POTO live-sale archive: ~5,466 published / ~164
buyable / 159 kept after filter). Per-variant `available` is the only stock
signal on the public Shopify feed (Shopify hides inventory_quantity).

Default-off discipline: in_stock_only defaults False, so the 9 pre-CTK-088
vendors are byte-identical (no availability gate). The no-regression path is
exercised here AND by the full per-vendor parse-test suite passing unchanged.

Runnable as:
  python -m scrapers.tests.test_parse_shopify_in_stock_only
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

from scrapers.common.parse_shopify import _should_keep


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "parse_shopify_in_stock_only" / "products.sample.json"

# POTO-shape config: in_stock_only gate, no category_filter (catalog coral-pure).
POTO_DENYLIST_FILTER = {"tag_denylist": ["macroalgae"]}  # only used by the AND-interaction test


def _load_fixture() -> list[dict]:
    with FIXTURE_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)["products"]


try:
    import pytest
    @pytest.fixture(scope="module")
    def products():
        return _load_fixture()
except ImportError:
    pass


def _by_title(products: list[dict], title: str) -> dict:
    for p in products:
        if p["title"] == title:
            return p
    raise KeyError(f"fixture missing product titled {title!r}")


# Test 1: in_stock_only=True keeps a buyable product (>=1 available variant)
def test_in_stock_only_keeps_buyable(products):
    """POTO Lightning Bug Torch — one available=true variant. in_stock_only
    gate passes; no category_filter → keep."""
    p = _by_title(products, "POTO Lightning Bug Torch — buyable")
    assert _should_keep(p, None, in_stock_only=True) is True


# Test 2: in_stock_only=True drops a sold-out product (no available variant)
def test_in_stock_only_drops_sold_out(products):
    """Vivids Badfish Acropora — single available=false variant. in_stock_only
    gate short-circuits → reject. This is the POTO archive case: ~5,307 of
    5,466 products are sold-out past-drop items that must never enter the diff."""
    p = _by_title(products, "Vivids Badfish Acropora — sold out")
    assert _should_keep(p, None, in_stock_only=True) is False


# Test 3: in_stock_only=True drops sold-out even with multiple variants
def test_in_stock_only_drops_sold_out_multi_variant(products):
    """Sold-out product with TWO available=false variants — any()-over-empty-
    truthy short-circuits to False → reject. Confirms the gate evaluates all
    variants, not just the first."""
    p = _by_title(products, "Sold-out product that would pass an allowlist")
    assert _should_keep(p, None, in_stock_only=True) is False


# Test 4: in_stock_only=False (DEFAULT) keeps both buyable AND sold-out
def test_in_stock_only_default_off_is_permissive(products):
    """No-regression core: default in_stock_only=False applies no availability
    gate — both buyable and sold-out products pass (fleet behavior). This is
    the byte-identical guarantee for the 9 pre-CTK-088 vendors."""
    buyable = _by_title(products, "POTO Lightning Bug Torch — buyable")
    sold_out = _by_title(products, "Vivids Badfish Acropora — sold out")
    # Default param (omitted)
    assert _should_keep(buyable, None) is True
    assert _should_keep(sold_out, None) is True
    # Explicit False
    assert _should_keep(buyable, None, in_stock_only=False) is True
    assert _should_keep(sold_out, None, in_stock_only=False) is True


# Test 5: in_stock_only AND-interacts with tag_denylist (both must pass)
def test_in_stock_only_and_tag_denylist_interaction(products):
    """A buyable product carrying a denylist tag: in_stock_only gate passes
    (buyable) but tag_denylist rejects (macroalgae). Confirms in_stock_only is
    AND-combined with category_filter axes, not a bypass. (POTO ships with NO
    category_filter — this test guards the interaction for any future POTO-
    shape vendor that wants both an availability gate AND a thin denylist.)"""
    p = _by_title(products, "Buyable product with denylist tag")
    # in_stock_only alone → keep
    assert _should_keep(p, None, in_stock_only=True) is True
    # in_stock_only + denylist → reject (denylist short-circuits after gate)
    assert _should_keep(p, POTO_DENYLIST_FILTER, in_stock_only=True) is False


# Test 6: in_stock_only=False + sold-out + would-pass-allowlist stays permissive
def test_default_off_does_not_gate_sold_out_with_category_filter(products):
    """With in_stock_only default-off, a sold-out product passes the category
    gate normally (no availability check). Proves the gate is purely additive
    — turning it off restores exact pre-CTK-088 evaluation for category_filter
    consumers."""
    p = _by_title(products, "Sold-out product that would pass an allowlist")
    cf = {"product_type_allowlist": ["live sale"]}
    assert _should_keep(p, cf) is True              # default off → kept despite sold-out
    assert _should_keep(p, cf, in_stock_only=True) is False  # gate on → dropped


# Test 7 (fold #7): discriminates any()-over-variants from a variants[0]-only bug
def test_keeps_when_first_variant_sold_out_second_buyable(products):
    """First variant available=false, SECOND available=true → KEPT under
    in_stock_only. The Test 3 both-false fixture can't catch a regression that
    only checks variants[0]; this one does — if the gate were
    `variants[0].available` instead of `any(v.available ...)`, this product
    would wrongly drop and the test fails."""
    p = _by_title(products, "First variant sold out, second buyable")
    assert _should_keep(p, None, in_stock_only=True) is True


# Test 8 (fold #9): empty + missing variants pin the `or []` guard (no crash)
def test_empty_and_missing_variants_drop_without_crash(products):
    """Empty variants list + missing variants key — under in_stock_only neither
    has a buyable variant → dropped, and the `or []` guard means no crash on
    the absent/empty collection. Default-off → permissive (no availability
    gate applied)."""
    empty = _by_title(products, "Empty variants list")
    missing = _by_title(products, "Missing variants key")
    assert _should_keep(empty, None, in_stock_only=True) is False
    assert _should_keep(missing, None, in_stock_only=True) is False
    assert _should_keep(empty, None) is True       # default off → permissive
    assert _should_keep(missing, None) is True


# Test 9 (fold #9): product_type None vs "" both match the '' allowlist entry
def test_product_type_none_and_empty_both_match_empty_allowlist(products):
    """product_type=None and product_type='' both normalize to '' via the
    `or ''` guard, so both match the '' allowlist entry — this is what lets
    POTO keep its buyable empty-product_type cross-vendor corals. Pins the
    normalization; a product_type genuinely outside the allowlist still drops."""
    cf = {"product_type_allowlist": ["live sale", ""]}
    null_pt = _by_title(products, "Null product_type buyable")
    empty_pt = _by_title(products, "Empty-string product_type buyable")
    assert _should_keep(null_pt, cf, in_stock_only=True) is True
    assert _should_keep(empty_pt, cf, in_stock_only=True) is True
    # A product_type NOT in the allowlist (and not '') still drops:
    other = {**null_pt, "product_type": "merch"}
    assert _should_keep(other, cf, in_stock_only=True) is False


# Test 10 (fold #8): the new-bucket WARN fires for an unknown buyable drop
def test_warn_fires_on_unknown_buyable_bucket_drop(caplog):
    """A BUYABLE item whose product_type is neither in the allowlist NOR the
    known-excluded set raises the new-bucket WARN — this is the post-ship watch
    signal the listings_seen canary can't provide (an additive bucket)."""
    import logging
    unknown = {
        "title": "Buyable item in an unknown bucket",
        "product_type": "mega sale",  # not in allowlist, not known-excluded
        "tags": [],
        "variants": [{"sku": "X", "available": True}],
    }
    cf = {"product_type_allowlist": ["live sale", "collection"]}
    with caplog.at_level(logging.WARNING, logger="scrapers.common.parse_shopify"):
        assert _should_keep(unknown, cf, in_stock_only=True) is False
    assert "possible new bucket" in caplog.text


# Test 11 (fold #8): gate order — availability FIRST, so a sold-out unknown bucket does NOT warn
def test_sold_out_unknown_bucket_does_not_warn(caplog):
    """Gate-order pin: a SOLD-OUT item in an unknown bucket must NOT WARN — the
    availability gate drops it BEFORE the allowlist-WARN branch. If the gates
    were reordered (allowlist before availability), this would emit a spurious
    new-bucket WARN for an item that's just sold out."""
    import logging
    sold_out_unknown = {
        "title": "Sold-out item in an unknown bucket",
        "product_type": "mega sale",
        "tags": [],
        "variants": [{"sku": "Y", "available": False}],
    }
    cf = {"product_type_allowlist": ["live sale"]}
    with caplog.at_level(logging.WARNING, logger="scrapers.common.parse_shopify"):
        assert _should_keep(sold_out_unknown, cf, in_stock_only=True) is False
    assert "possible new bucket" not in caplog.text


# Test 12 (fold #3): known-excluded buckets drop silently (WARN keeps its signal)
def test_known_excluded_bucket_does_not_warn(caplog):
    """A BUYABLE merch item dropped by the allowlist must NOT WARN — merch is a
    known-excluded bucket (expected drop), so it stays silent and the WARN keeps
    its new-bucket signal. Without this suppression the post-ship watch drowns in
    ~11 expected-drop WARNs per scrape."""
    import logging
    merch = {
        "title": "POTO Super Mario Hoodie",
        "product_type": "merch",
        "tags": [],
        "variants": [{"sku": "Z", "available": True}],
    }
    cf = {"product_type_allowlist": ["live sale", "collection"]}
    with caplog.at_level(logging.WARNING, logger="scrapers.common.parse_shopify"):
        assert _should_keep(merch, cf, in_stock_only=True) is False
    assert "possible new bucket" not in caplog.text


def main() -> int:
    products = _load_fixture()
    tests = [
        test_in_stock_only_keeps_buyable,
        test_in_stock_only_drops_sold_out,
        test_in_stock_only_drops_sold_out_multi_variant,
        test_in_stock_only_default_off_is_permissive,
        test_in_stock_only_and_tag_denylist_interaction,
        test_default_off_does_not_gate_sold_out_with_category_filter,
        test_keeps_when_first_variant_sold_out_second_buyable,
        test_empty_and_missing_variants_drop_without_crash,
        test_product_type_none_and_empty_both_match_empty_allowlist,
    ]
    failed = 0
    for t in tests:
        try:
            t(products)
            print(f"PASS  {t.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL  {t.__name__}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
