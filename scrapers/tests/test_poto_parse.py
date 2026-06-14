"""scrapers/tests/test_poto_parse.py — CTK-088 parse-layer tests for POTO's
Shopify /products.json shape against locked fixture
scrapers/tests/fixtures/poto/products.sample.json.

Parse-only — no DB, no network. POTO is the FIRST consumer of the CTK-088
in_stock_only framework gate. Its catalog is a permanent live-sale archive
(~5,466 products / ~164 buyable), so in_stock_only is the load-bearing
filter, paired with a product_type_allowlist that drops buyable merch/
gift-card the plan pre-flight missed.

Covers ~4 representative fixtures per fixture discipline (NOT one-per-bucket):
  - POTO Solar Pop — buyable 'collection' coral: in_stock_only keep +
    product_type_allowlist keep
  - CC Banana Hammock Colony — sold-out 'live sale' coral: in_stock_only
    drop (the 5,300-row archive case — never enters the diff)
  - ReefnBid UV Ink T-Shirt — buyable 'merch': in_stock_only keep BUT
    product_type_allowlist drop (the image-bearing non-coral leak the
    ratified filter exists to catch)
  - Atomic Broccoli Macroalgae — buyable, product_type 'live sale', empty
    tags: the ACCEPTED leak (coral PT + no distinguishing tag → neither
    allowlist nor denylist excludes it; Battlecorals 1-anemone precedent)

The POTO filter combines in_stock_only=True + the ratified
product_type_allowlist (CTK-088 /lead-backend 2026-05-28). Both axes are
AND-combined in _should_keep.

Runnable as:
  python -m scrapers.tests.test_poto_parse
"""

from __future__ import annotations

import hashlib
import json
import sys
import traceback
from pathlib import Path

from scrapers.common.parse_shopify import _normalize_product, _should_keep


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "poto" / "products.sample.json"
BASE_URL = "https://piecesoftheocean.com"
ORIGINATOR_PREFIX = None  # CTK-088 — null per seed-list absence (no POTO-attributed canonicals)
IMAGE_STRATEGY = "mirror"

# Mirrors scrapers/vendors/poto.yaml: in_stock_only gate + product_type_allowlist
# (ratified /lead-backend 2026-05-28). '' kept by necessity (buyable empty-PT
# cross-vendor corals); merch/Gift Card excluded by omission.
POTO_CATEGORY_FILTER = {
    "product_type_allowlist": [
        "live sale", "lightning sale", "collection", "poto-gems", "wysiwyg", "",
    ],
    # CTK-155 (2026-06-14): mirror of the YAML title_denylist_prefix. (The
    # production title_denylist substring block — Chaeto/Macroalgae — predates
    # this mirror and is intentionally not reproduced here; see the /lead-backend
    # flag re: the pre-existing POTO mirror gap.)
    "title_denylist_prefix": ["Title"],
}
POTO_IN_STOCK_ONLY = True


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


def _keep(p: dict) -> bool:
    return _should_keep(p, POTO_CATEGORY_FILTER, in_stock_only=POTO_IN_STOCK_ONLY)


def _normalize(p: dict) -> dict:
    return _normalize_product(p, BASE_URL, IMAGE_STRATEGY, ORIGINATOR_PREFIX)


def _p(title: str, product_type: str = "", available: bool = True) -> dict:
    """CTK-155 synthetic product — buyable single variant so the in_stock_only
    gate passes and the title axis is isolated as the cut."""
    return {"title": title, "product_type": product_type, "tags": [],
            "variants": [{"available": available}]}


# Test 1: html_hash sentinel — sorted-keys-of-first-product SHA256
def test_html_hash_first_product_keys(products):
    """Arch §2.6 Shopify variant: hash sorted key set of first product.
    Matches the fleet 13-key anchor."""
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


# Test 2: buyable coral kept (in_stock_only pass + allowlist pass)
def test_keeps_buyable_collection_coral(products):
    """POTO Solar Pop — buyable 'collection' POTO signature piece. Passes the
    in_stock_only gate (buyable) AND the product_type_allowlist ('collection')
    → keep."""
    p = _by_title(products, "POTO Solar Pop")
    assert any(v.get("available") for v in p["variants"]), "fixture invariant: buyable"
    assert p["product_type"] == "collection"
    assert _keep(p) is True


# Test 3: sold-out coral dropped by in_stock_only (the archive case)
def test_drops_sold_out_coral_via_in_stock_only(products):
    """CC Banana Hammock Colony — sold-out 'live sale' coral. product_type is
    in the allowlist, but in_stock_only short-circuits (no buyable variant) →
    drop. This is the ~5,300-row archive case: sold-out drops never enter the
    diff, so vendor_listings holds only the live buyable count."""
    p = _by_title(products, "CC Banana Hammock Colony")
    assert not any(v.get("available") for v in p["variants"]), "fixture invariant: sold out"
    assert p["product_type"] == "live sale"  # would pass allowlist if buyable
    assert _keep(p) is False
    # Prove it's in_stock_only doing the work, not the allowlist:
    assert _should_keep(p, POTO_CATEGORY_FILTER, in_stock_only=False) is True


# Test 4: buyable merch dropped by product_type_allowlist (the ratified-filter case)
def test_drops_buyable_merch_via_allowlist(products):
    """ReefnBid UV Ink T-Shirt — BUYABLE 'merch'. Passes in_stock_only
    (buyable) but product_type 'merch' is not in the allowlist → drop. This
    is the image-bearing non-coral leak the ratified product_type_allowlist
    exists to catch (the plan pre-flight's 'no allowlist' premise missed it)."""
    p = _by_title(products, "ReefnBid UV Ink Illustrative Logo T-Shirt")
    assert any(v.get("available") for v in p["variants"]), "fixture invariant: buyable"
    assert p["product_type"] == "merch"
    assert _keep(p) is False
    # Prove it's the allowlist doing the work, not in_stock_only:
    assert _should_keep(p, None, in_stock_only=True) is True


# Test 5: macroalgae is the ACCEPTED leak (coral PT + no tag → not excludable)
def test_macroalgae_accepted_leak(products):
    """Atomic Broccoli Macroalgae — buyable, product_type 'live sale' (a coral
    bucket), empty tags. Neither the allowlist (PT is allowed) nor a
    tag_denylist (no tags) can exclude it, so it leaks. Accepted per the
    Battlecorals 1-anemone-leak precedent (macroalgae is reef-livestock-
    adjacent; 1 item; frontend has_image is the only downstream gate). This
    test PINS the known leak — if a future filter change starts dropping it,
    that's a deliberate decision, not an accident."""
    p = _by_title(products, "Atomic Broccoli Macroalgae")
    assert any(v.get("available") for v in p["variants"]), "fixture invariant: buyable"
    assert p["product_type"] == "live sale"
    assert p.get("tags") in ([], None), "fixture invariant: empty tags (untaggable)"
    assert _keep(p) is True  # accepted leak — documents current behavior


# Test 6: in_stock_only + allowlist skip-count across fixture
def test_skip_count_matches(products):
    """Fixture composition under the POTO filter: 1 kept (POTO Solar Pop) +
    1 macroalgae-leak kept = 2 kept; 1 sold-out coral + 1 buyable merch = 2
    dropped."""
    kept = sum(1 for p in products if _keep(p))
    dropped = sum(1 for p in products if not _keep(p))
    assert kept == 2, f"expected 2 kept (Solar Pop + macroalgae leak), got {kept}"
    assert dropped == 2, f"expected 2 dropped (sold-out + merch), got {dropped}"


# Test 7: _normalize_product output shape on a buyable coral
def test_normalize_buyable_coral(products):
    """_normalize_product on POTO Solar Pop — validates the output dict shape
    per arch §1.4. in_stock derives from variant availability."""
    p = _by_title(products, "POTO Solar Pop")
    norm = _normalize(p)
    assert norm["raw_title"] == "POTO Solar Pop"
    assert norm["product_url"].startswith("https://piecesoftheocean.com/products/")
    assert norm["in_stock"] is True
    assert norm["currency"] == "USD"
    assert norm["vendor_image_url"] is not None


# Test 8 (CTK-155): "Title" placeholder dropped by the anchored prefix
def test_drops_title_placeholder_via_prefix(products=None):
    """CTK-155 (2026-06-14) — POTO vendor placeholder row "Title" (id 72999,
    PT='' the allowlisted empty bucket) leaked to /new. title_denylist_prefix
    "Title" drops it. Synthetic is buyable + PT='' so in_stock_only and the
    allowlist both PASS — only the prefix rejects."""
    p = _p("Title")
    assert _keep(p) is False
    # Prove the prefix is the cut: without it (allowlist only) the row is kept.
    assert _should_keep(
        p, {"product_type_allowlist": POTO_CATEGORY_FILTER["product_type_allowlist"]},
        in_stock_only=POTO_IN_STOCK_ONLY,
    ) is True


# Test 9 (CTK-155): FP-guard — anchored prefix spares a "title" substring coral
def test_title_prefix_fp_guard_substring_coral_kept(products=None):
    """CTK-155 FP-guard — the entry is an ANCHORED prefix, not a substring
    (the reason Jon chose prefix). A coral whose name merely CONTAINS "title"
    mid-string must stay kept: "...subtitle..." does not START with "title".
    Pins that the entry cannot over-reach into real coral names."""
    p = _p("Reef Subtitle Acropora")  # contains "title" at an offset, not the start
    assert "title" in p["title"].lower()
    assert _keep(p) is True


def main() -> int:
    products = _load_fixture()
    tests = [
        test_html_hash_first_product_keys,
        test_keeps_buyable_collection_coral,
        test_drops_sold_out_coral_via_in_stock_only,
        test_drops_buyable_merch_via_allowlist,
        test_macroalgae_accepted_leak,
        test_skip_count_matches,
        test_normalize_buyable_coral,
        test_drops_title_placeholder_via_prefix,
        test_title_prefix_fp_guard_substring_coral_kept,
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
