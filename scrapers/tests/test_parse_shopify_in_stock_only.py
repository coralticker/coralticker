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

from scrapers.common import parse_shopify
from scrapers.common.http import FetchResult
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


# Test 13 (CTK-094 Session 5 fold #6 — regression-pin for Session 3 → Session 4
# fold #1). Drives parse_shopify.fetch_and_parse end-to-end to pin the
# filtered_urls discrimination: only category-rejected URLs (vendor still
# buyable) enter the cohort absent-set; sold-out rejects are the cohort signal
# and must NOT enter filtered_urls. Session 3's fold #4 added URLs at the
# wrong scope, defeating CTK-094 on POTO; Session 4 restored the discrimination
# but landed no test. This test would have caught the Session 3 regression at
# landing time. Three assertions cover all three classes of _should_keep
# rejects under in_stock_only:true.
def test_filtered_urls_excludes_sold_out_includes_category_rejected():
    """CTK-094 Session 5 fold #6 — three assertions on parse_shopify.fetch_and_parse:
    (a) sold-out product (in_stock_only short-circuit at skipped_unavailable) →
        URL NOT in filtered_urls (cohort signal preserved).
    (b) buyable + category-rejected product (skipped_category) → URL IS in
        filtered_urls (cohort exclusion: vendor still buyable, no false-OOS).
    (c) sold-out + category-rejected product (skipped_unavailable wins per
        L165-168 discrimination order) → URL NOT in filtered_urls."""
    fixture = {
        "products": [
            # (a) Sold-out buyable category — cohort signal must persist.
            {
                "id": 1,
                "handle": "sold-out-coral",
                "title": "Sold-out coral that would pass category gate",
                "product_type": "live sale",
                "tags": [],
                "variants": [{"sku": "SO-1", "available": False}],
                "images": [],
            },
            # (b) Buyable but category-rejected — cohort exclusion via filtered_urls.
            {
                "id": 2,
                "handle": "buyable-merch",
                "title": "Buyable merch in disallowed bucket",
                "product_type": "merch",
                "tags": [],
                "variants": [{"sku": "M-1", "available": True}],
                "images": [],
            },
            # (c) Sold-out AND category-rejected — skipped_unavailable wins.
            {
                "id": 3,
                "handle": "sold-out-merch",
                "title": "Sold-out merch in disallowed bucket",
                "product_type": "merch",
                "tags": [],
                "variants": [{"sku": "SOM-1", "available": False}],
                "images": [],
            },
            # Anchor buyable + in-allowlist product to keep items non-empty.
            {
                "id": 4,
                "handle": "kept-coral",
                "title": "Buyable coral in allowlist bucket",
                "product_type": "live sale",
                "tags": [],
                "variants": [{"sku": "K-1", "available": True, "price": "100.00"}],
                "images": [],
            },
        ]
    }

    original_fetch = parse_shopify.http.fetch
    pages_served: dict[int, bool] = {1: False}

    def stub_fetch(url, request_delay_sec=2.0):
        if "page=1" in url and not pages_served[1]:
            pages_served[1] = True
            return FetchResult(
                body=json.dumps(fixture).encode("utf-8"),
                status_code=200,
                error_class=None,
                error_message=None,
            )
        # Subsequent pages → empty products array (natural terminator).
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
            "in_stock_only": True,
            "category_filter": {"product_type_allowlist": ["live sale"]},
            "image_strategy": "mirror",
        }
        result = parse_shopify.fetch_and_parse(config)
    finally:
        parse_shopify.http.fetch = original_fetch

    # Build expected URL shape (matches _normalize_product + parse_shopify.py:178).
    base = "https://example-vendor.com/products"
    sold_out_url = f"{base}/sold-out-coral"
    buyable_merch_url = f"{base}/buyable-merch"
    sold_out_merch_url = f"{base}/sold-out-merch"

    # (a) sold-out coral — NOT in filtered_urls (cohort signal preserved).
    assert sold_out_url not in result.filtered_urls, (
        f"sold-out coral URL must NOT enter filtered_urls (it IS the cohort "
        f"signal); got filtered_urls={result.filtered_urls}"
    )
    # (b) buyable + category-rejected — IS in filtered_urls (cohort exclusion).
    assert buyable_merch_url in result.filtered_urls, (
        f"buyable + category-rejected URL must enter filtered_urls (vendor "
        f"still buyable, prevents false cohort-OOS); got "
        f"filtered_urls={result.filtered_urls}"
    )
    # (c) sold-out + category-rejected — NOT in filtered_urls
    # (skipped_unavailable wins; sold-out is still the cohort signal).
    assert sold_out_merch_url not in result.filtered_urls, (
        f"sold-out + category-rejected URL must NOT enter filtered_urls "
        f"(skipped_unavailable wins per L165-168 discrimination order); got "
        f"filtered_urls={result.filtered_urls}"
    )
    # Sanity: the anchor buyable in-allowlist product DID make it into items.
    assert len(result.items) == 1, (
        f"expected 1 kept item (kept-coral); got {len(result.items)} "
        f"({[i.get('product_url') for i in result.items]})"
    )


# CTK-117 /code-review fold (Finding 1) — pytest-only caplog test. Pins that the
# call-site attribution counter uses the SAME normalized tag_denylist matching
# as the _should_keep gate. A Livestock product tagged `Reef-Safe` (hyphen
# variant) whose title ALSO hits title_denylist is dropped by the tag_denylist
# gate (normalized: `reef-safe` -> `reef safe`); the drop must attribute to
# category-filter, not title-denylist. Pre-fold the attribution branch matched
# exact-lowercase, so `reef-safe` missed the set and the title-hit elif fired —
# re-opening the CTK-096 F5 mis-attribution for label-shape variants. Not in the
# script-mode main() runner (caplog is pytest-only), consistent with the other
# caplog tests in this file.
def test_tag_denylist_variant_attributes_to_category_not_title():
    import logging

    fixture = {
        "products": [
            {
                "id": 1,
                "handle": "reef-safe-fish-late-fees",
                "title": "Some Reef Fish Late Fees Special",  # hits title_denylist 'Late Fees'
                "product_type": "Livestock",                  # in allowlist
                "tags": ["Reef-Safe"],                        # hyphen variant -> normalizes to 'reef safe'
                "variants": [{"sku": "RS-1", "available": True, "price": "10.00"}],
                "images": [],
            },
            {
                "id": 2,
                "handle": "kept-coral",
                "title": "Buyable coral in allowlist bucket",
                "product_type": "Livestock",
                "tags": [],
                "variants": [{"sku": "K-1", "available": True, "price": "100.00"}],
                "images": [],
            },
        ]
    }

    original_fetch = parse_shopify.http.fetch
    pages_served = {1: False}

    def stub_fetch(url, request_delay_sec=2.0):
        if "page=1" in url and not pages_served[1]:
            pages_served[1] = True
            return FetchResult(
                body=json.dumps(fixture).encode("utf-8"),
                status_code=200, error_class=None, error_message=None,
            )
        return FetchResult(
            body=json.dumps({"products": []}).encode("utf-8"),
            status_code=200, error_class=None, error_message=None,
        )

    parse_shopify.http.fetch = stub_fetch
    try:
        config = {
            "base_url": "https://example-vendor.com",
            "products_path": "/products.json",
            "page_size": 250,
            "max_pages": 3,
            "request_delay_sec": 0,
            "image_strategy": "mirror",
            "category_filter": {
                "product_type_allowlist": ["Livestock"],
                "tag_denylist": ["Reef Safe"],   # canonical entry; tag is 'Reef-Safe'
                "title_denylist": ["Late Fees"],
            },
        }
        import logging as _logging
        logger = _logging.getLogger("scrapers.common.parse_shopify")
        records: list[str] = []
        handler = _logging.Handler()
        handler.emit = lambda r: records.append(r.getMessage())  # type: ignore[assignment]
        prev_level = logger.level
        logger.setLevel(_logging.INFO)
        logger.addHandler(handler)
        try:
            parse_shopify.fetch_and_parse(config)
        finally:
            logger.removeHandler(handler)
            logger.setLevel(prev_level)
    finally:
        parse_shopify.http.fetch = original_fetch

    filter_line = next((m for m in records if m.startswith("filter:")), "")
    assert "category-filter 1" in filter_line, (
        f"hyphen-variant tag_denylist drop must attribute to category-filter; "
        f"got log line: {filter_line!r}"
    )
    assert "title-denylist 0" in filter_line, (
        f"hyphen-variant tag_denylist drop must NOT attribute to title-denylist "
        f"(CTK-096 F5 re-closure); got log line: {filter_line!r}"
    )


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
    # No-args tests driving fetch_and_parse end-to-end (CTK-094 fold #6 +
    # CTK-117 fold Finding 1 attribution).
    noargs = [
        test_filtered_urls_excludes_sold_out_includes_category_rejected,
        test_tag_denylist_variant_attributes_to_category_not_title,
    ]
    for t in noargs:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL  {t.__name__}")
            traceback.print_exc()
    total = len(tests) + len(noargs)
    print(f"\n{total - failed}/{total} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
