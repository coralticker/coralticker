"""scrapers/tests/test_parse_shopify_in_stock_only.py — CTK-088
parse_shopify._should_keep in_stock_only availability-gate tests.

Parse-only — no DB, no network. Validates the in_stock_only opt-in gate
added to _should_keep for vendors whose catalog is a permanent archive of
mostly sold-out items (POTO live-sale archive: ~3,500 published / ~21-41
buyable). Per-variant `available` is the only stock signal on the public
Shopify feed (Shopify hides inventory_quantity).

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
    gate short-circuits → reject. This is the POTO archive case: ~3,459 of
    3,500 products are sold-out past-drop items that must never enter the diff."""
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


def main() -> int:
    products = _load_fixture()
    tests = [
        test_in_stock_only_keeps_buyable,
        test_in_stock_only_drops_sold_out,
        test_in_stock_only_drops_sold_out_multi_variant,
        test_in_stock_only_default_off_is_permissive,
        test_in_stock_only_and_tag_denylist_interaction,
        test_default_off_does_not_gate_sold_out_with_category_filter,
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
