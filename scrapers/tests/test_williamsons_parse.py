"""scrapers/tests/test_williamsons_parse.py — CTK-146 parse-layer tests for
Williamson's Reef's Shopify /products.json shape against locked fixture
scrapers/tests/fixtures/williamsons/products.sample.json.

Parse-only — no DB, no network. Validates parse_shopify._normalize_product
output shape + html_hash sentinel + the NON-STANDARD category_filter mechanism
that makes Williamson's different from every other fleet vendor.

WHY THIS TEST EXISTS (the regression it pins):
Williamson's product_type is NOT a genus taxonomy. The Session-1 walk
(2026-06-28, the full catalog locked as this fixture, 202 rows) found just TWO
product_type buckets: 'Coral' (184) and '' empty (18). The '' bucket is mostly
REAL CORAL (BC ''-as-coral-grab-bag shape, NOT Cornbred's drop-''): POTO Queen
Of Hearts $79 (zero tags), WWC Strip Tease, UC Dippin Dots, Aussie Scolymias.
So the mechanism is product_type_allowlist:[Coral, ""] (allowlist BOTH buckets)
+ a targeted denylist for the small enumerable non-coral that also lives in ''.

Two regressions a future "tidy" would silently cause, both caught here:
  - Dropping "" from the allowlist (cloning the Cornbred [Coral]-only shape)
    silently loses ~14 real coral in the '' bucket — test_empty_bucket_coral_survives.
  - Coarsening the "Mushroom Cage" title_denylist entry to "Mushroom" nukes
    every real mushroom coral — test_mushroom_cage_substring_granularity.

INV-05 is NOT triggered: the full-catalog walk found zero auction signal (no
wk_end_auction/auc/bid tags, no product_type:Auction). The single "$0 Auction
order" row is an off-platform-win checkout helper, dropped by title_denylist —
NOT an INV-05 auction. williamsons.yaml carries no auction_detection block;
test_yaml_mirror_parity pins that absence so a future block can't land unmirrored.

Mirror-parity (CTK-115 convention): test loads scrapers/vendors/williamsons.yaml
and asserts the in-test WILLIAMSONS_CATEGORY_FILTER equals the YAML block
byte-exact — a YAML allowlist/denylist amendment that isn't mirrored here fails
test_yaml_mirror_parity.

Runnable as:
  python -m scrapers.tests.test_williamsons_parse

Fixture regen path: re-fetch williamsonsreef.com/products.json?limit=250&page=1
and re-dump the full {"products": [...]} payload (the walk shape used at CTK-146
Session 1). NOTE: re-pinning will move the kept/dropped counts as the live
catalog drifts — update test_total_kept_is_197's expected counts to match the
new snapshot, and re-confirm the four survivor titles still exist.
"""

from __future__ import annotations

import hashlib
import json
import sys
import traceback
from pathlib import Path

import yaml

from scrapers.common.parse_shopify import (
    _normalize_product,
    _normalize_tag,
    _should_keep,
)


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "williamsons" / "products.sample.json"
YAML_PATH = Path(__file__).parent.parent / "vendors" / "williamsons.yaml"
BASE_URL = "https://williamsonsreef.com"
ORIGINATOR_PREFIX = None  # CTK-146 — null per seed-list absence (reseller, no Williamson's-attributed canonicals)
IMAGE_STRATEGY = "mirror"
AUCTION_DETECTION = None   # CTK-146 — INV-05 not triggered; no auction_detection block in the YAML

# Hand-mirror of scrapers/vendors/williamsons.yaml category_filter — kept
# byte-exact with the YAML; test_yaml_mirror_parity asserts the equality so a
# YAML amendment that isn't mirrored here fails loudly (CTK-115 drift class).
WILLIAMSONS_CATEGORY_FILTER = {
    "product_type_allowlist": ["Coral", ""],
    "tag_denylist": ["giftcard"],
    "title_denylist": [
        "Gift Card", "Versa Pump", "Auction order", "Mushroom Cage",
        "add to coral order", "Chaeto", "Cheato", "Macroalgae", "Macro Algae",
    ],
}

# Expected keep/drop counts on the LOCKED 2026-06-28 fixture (202 rows). These
# pin the snapshot, not live — re-pinning the fixture requires updating them.
EXPECTED_TOTAL = 202
EXPECTED_KEPT = 197
EXPECTED_DROPPED = 5

# The five enumerable non-coral rows that MUST drop (Session-1 walk, resolved
# row-by-row). Gift Card is caught by BOTH the giftcard tag and the "Gift Card"
# title; the other four by title_denylist.
NON_CORAL_TITLES = [
    "Williamson's Reef Gift Card",
    "Versa Pump 4 Pack with Base Station",
    "Auction order",
    "Mushroom Cage Black",
    "4 Micro Brittle Starfish add to coral order.",
]

# Real coral that lives in the '' empty product_type bucket (or is otherwise the
# regression target) — these MUST survive. POTO Queen Of Hearts is the headline:
# zero tags + empty product_type, so [Coral]-only OR a tag_allowlist would both
# silently drop it.
EMPTY_BUCKET_CORAL_TITLES = [
    "POTO Queen Of Hearts",          # PT='', zero tags — the killer case
    "WWC Strip Tease",               # PT='', SPS-tagged
    "UC Dippin Dots",                # PT='', SPS-tagged
    "Aussie Bleeding Apple Scolymia",  # PT='', LPS-tagged
]


def _tag_denylist_norm() -> set[str]:
    """Mirror the production hoist in fetch_and_parse: normalize the YAML
    tag_denylist into the set _should_keep consumes as its 4th positional arg.
    Without this the giftcard tag axis is silently bypassed (the real reason
    the gift card needs the title backstop too)."""
    return {_normalize_tag(e) for e in (WILLIAMSONS_CATEGORY_FILTER.get("tag_denylist") or [])}


def _keep(p: dict) -> bool:
    """_should_keep called exactly as production does — category_filter +
    in_stock_only=False (williamsons has no in_stock_only) + the normalized
    tag_denylist."""
    return _should_keep(p, WILLIAMSONS_CATEGORY_FILTER, False, _tag_denylist_norm())


def _normalize(p: dict) -> dict:
    return _normalize_product(p, BASE_URL, IMAGE_STRATEGY, ORIGINATOR_PREFIX, AUCTION_DETECTION)


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


# Test 1: html_hash sentinel — sorted-keys-of-first-product SHA256
def test_html_hash_first_product_keys(products):
    """Arch §2.6 Shopify variant: hash sorted key set of first product.
    Matches the 13-key Shopify-fleet anchor. Sentinel flips only when keys
    add/remove."""
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


# Test 2 (DIRECTIVE #1): total kept = 197 (202 - 5 enumerable non-coral)
def test_total_kept_is_197(products):
    """Full-catalog skip count on the locked 202-row fixture: 197 kept, 5
    dropped. This is the aggregate guard — any allowlist/denylist regression
    that leaks junk or drops coral moves these counts and fails here."""
    assert len(products) == EXPECTED_TOTAL, f"fixture drifted: expected {EXPECTED_TOTAL} rows, got {len(products)}"
    kept = sum(1 for p in products if _keep(p))
    dropped = len(products) - kept
    assert kept == EXPECTED_KEPT, f"expected {EXPECTED_KEPT} kept, got {kept}"
    assert dropped == EXPECTED_DROPPED, f"expected {EXPECTED_DROPPED} dropped, got {dropped}"


# Test 3 (DIRECTIVE #2): the five enumerable non-coral rows are dropped
def test_five_non_coral_rows_dropped(products):
    """Each of the five non-coral rows resolved row-by-row at the Session-1
    walk must drop: Gift Card (tag + title), Versa Pump (equipment), Auction
    order ($0 off-platform checkout helper), Mushroom Cage Black (acclimation
    cage), and the brittle-star CUC add-on."""
    for title in NON_CORAL_TITLES:
        p = _by_title(products, title)
        assert _keep(p) is False, f"non-coral row should have dropped: {title!r}"


# Test 4 (DIRECTIVE #3, THE REGRESSION): ''-grab-bag coral survives
def test_empty_bucket_coral_survives(products):
    """The '' empty product_type bucket is mostly REAL CORAL (BC grab-bag
    shape). These must survive. POTO Queen Of Hearts is the headline: empty
    product_type AND zero tags, so cloning the Cornbred [Coral]-only allowlist
    OR switching to a tag_allowlist would BOTH silently drop it. This is the
    exact regression the [Coral, ""] mechanism exists to prevent."""
    # Precondition that makes this test load-bearing: POTO Queen Of Hearts is
    # genuinely in the empty bucket with no tags — if the fixture drifted such
    # that it gained a tag or a 'Coral' product_type, the regression guard would
    # be co-incidentally satisfied and would stop testing the grab-bag path.
    poto = _by_title(products, "POTO Queen Of Hearts")
    assert poto.get("product_type") == "", "fixture drift: POTO Queen Of Hearts no longer empty-PT"
    assert not (poto.get("tags") or []), "fixture drift: POTO Queen Of Hearts gained tags"

    for title in EMPTY_BUCKET_CORAL_TITLES:
        p = _by_title(products, title)
        assert _keep(p) is True, f"'' -bucket coral should have survived: {title!r}"


# Test 5 (DIRECTIVE #4): Mushroom Cage denylist granularity
def test_mushroom_cage_substring_granularity(products):
    """The title_denylist entry is the specific "Mushroom Cage", NOT "Mushroom".
    Mushroom Cage Black (acclimation-cage equipment, Mushrooms-tagged) drops,
    while genuine Mushrooms-tagged mushroom CORALS survive. Coarsening the entry
    to "Mushroom" would nuke every real mushroom coral — this asserts the
    granularity holds."""
    cage = _by_title(products, "Mushroom Cage Black")
    assert "Mushrooms" in (cage.get("tags") or []), "fixture drift: Mushroom Cage lost its Mushrooms tag"
    assert _keep(cage) is False, "Mushroom Cage equipment should have dropped"

    # A real Mushrooms-tagged coral whose title does NOT contain 'Mushroom Cage'
    # must survive. Anchor a known one + assert the broader class survives too.
    real_mushroom = _by_title(products, "Ultra Rainbow Rhodactis Mushroom Colony")
    assert "Mushrooms" in (real_mushroom.get("tags") or [])
    assert _keep(real_mushroom) is True, "real mushroom coral should have survived the Mushroom Cage denylist"

    real_mushroom_corals = [
        p for p in products
        if "Mushrooms" in (p.get("tags") or []) and "Mushroom Cage" not in p["title"]
    ]
    assert real_mushroom_corals, "fixture drift: no real Mushrooms-tagged coral to guard granularity"
    for p in real_mushroom_corals:
        assert _keep(p) is True, f"real mushroom coral wrongly dropped: {p['title']!r}"


# Test 6: gift card drops via the tag axis specifically (not only the title)
def test_gift_card_dropped_by_tag_axis(products):
    """The real gift card carries BOTH a 'giftcard' tag and a 'Gift Card' title,
    so it drops via either axis. Isolate the TAG axis so a future title-only
    refactor can't silently disable the tag mechanism: a synthetic row with the
    giftcard tag in an allowlisted product_type and an innocuous title still
    drops via tag_denylist; the same row without the tag survives."""
    real = _by_title(products, "Williamson's Reef Gift Card")
    assert "giftcard" in (real.get("tags") or [])
    assert _keep(real) is False

    tdn = _tag_denylist_norm()
    tagged = {"title": "Innocuous Coral Name", "product_type": "Coral", "tags": ["giftcard"]}
    assert _should_keep(tagged, WILLIAMSONS_CATEGORY_FILTER, False, tdn) is False, (
        "giftcard tag_denylist axis not firing — the gift card would rely on the title backstop alone"
    )
    control = {"title": "Innocuous Coral Name", "product_type": "Coral", "tags": []}
    assert _should_keep(control, WILLIAMSONS_CATEGORY_FILTER, False, tdn) is True, (
        "FP control: an allowlisted-PT coral with no denied tag should survive"
    )


# Test 7: no auction null-out — INV-05 not triggered at the normalize layer
def test_normalize_no_auction_nulling(products):
    """williamsons.yaml carries no auction_detection (AUCTION_DETECTION=None),
    so coral normalizes with is_auction=False and keeps its real price — no
    collateral null-out. Pins the INV-05-not-triggered decision at the
    _normalize_product layer."""
    p = _by_title(products, "WWC Strip Tease")
    norm = _normalize(p)
    assert norm["is_auction"] is False
    assert norm["current_price"] is not None, "non-auction coral price must not be nulled"


# Test 8: _normalize_product output shape — coral product
def test_normalize_output_shape(products):
    """_normalize_product on a coral — validates output dict shape per arch §1.4
    vendor_listings columns + absolute product_url (CTK-033 D1)."""
    p = _by_title(products, "WWC Strip Tease")
    norm = _normalize(p)
    assert norm["raw_title"] == "WWC Strip Tease"
    assert norm["product_url"].startswith("https://williamsonsreef.com/products/")
    assert norm["currency"] == "USD"
    assert norm["vendor_image_url"] is not None
    assert "cdn.shopify.com" in norm["vendor_image_url"]


# Test 9 (MIRROR-PARITY, CTK-115): in-test filter == williamsons.yaml byte-exact
def test_yaml_mirror_parity():
    """CTK-115 mirror-parity: the in-test WILLIAMSONS_CATEGORY_FILTER must equal
    the scrapers/vendors/williamsons.yaml category_filter byte-exact, and the
    YAML must carry NO auction_detection block (INV-05 not triggered).

    The keys-exact assertion is load-bearing: this test (and _keep()) only model
    the three axes williamsons uses today (product_type_allowlist / tag_denylist
    / title_denylist) with in_stock_only=False. If a future maintainer adds a
    fourth axis (tag_allowlist / title_denylist_prefix / sku_denylist_suffix) or
    sets in_stock_only, the locked-fixture keep/drop counts would NOT reflect it
    and the suite would stay green against diverged production behavior. So we
    fail loudly the moment the YAML's filter-axis set — or the in_stock_only flag
    — drifts from what this test models, forcing the mirror to be extended.
    (CTK-115 drift class; the CTK-119 WWC chaeto-mirror lag was exactly this.
    Axis-coverage gap caught by CTK-146 /code-review 2026-06-28.)"""
    cfg = yaml.safe_load(YAML_PATH.read_text(encoding="utf-8"))
    yaml_filter = cfg["category_filter"]
    assert yaml_filter["product_type_allowlist"] == WILLIAMSONS_CATEGORY_FILTER["product_type_allowlist"], (
        "product_type_allowlist drift between williamsons.yaml and the test mirror"
    )
    assert yaml_filter.get("tag_denylist", []) == WILLIAMSONS_CATEGORY_FILTER["tag_denylist"], (
        "tag_denylist drift between williamsons.yaml and the test mirror"
    )
    assert yaml_filter.get("title_denylist", []) == WILLIAMSONS_CATEGORY_FILTER["title_denylist"], (
        "title_denylist drift between williamsons.yaml and the test mirror"
    )
    # Keys-exact: no unmodeled filter axis may appear. This test + _keep() model
    # exactly these three axes; any addition (tag_allowlist / title_denylist_prefix
    # / sku_denylist_suffix) must extend the mirror, not slip in silently.
    assert set(yaml_filter.keys()) == set(WILLIAMSONS_CATEGORY_FILTER.keys()), (
        f"williamsons.yaml category_filter grew/changed an axis the test mirror "
        f"doesn't model: YAML={sorted(yaml_filter.keys())} vs "
        f"mirror={sorted(WILLIAMSONS_CATEGORY_FILTER.keys())} — extend WILLIAMSONS_CATEGORY_FILTER + _keep()"
    )
    # in_stock_only is the other behavior-shifting knob _keep() hardcodes to
    # False; assert the YAML hasn't set it (which would change the keep-set).
    assert "in_stock_only" not in cfg, (
        "williamsons.yaml set in_stock_only — _keep() hardcodes False and the "
        "locked counts would no longer reflect production; thread it through the test"
    )
    assert cfg.get("auction_detection") is None, (
        "williamsons.yaml grew an auction_detection block — INV-05 disposition changed; "
        "re-confirm the walk + update this test mirror"
    )


def main() -> int:
    products = _load_fixture()
    no_param = {test_yaml_mirror_parity}
    tests = [
        test_html_hash_first_product_keys,
        test_total_kept_is_197,
        test_five_non_coral_rows_dropped,
        test_empty_bucket_coral_survives,
        test_mushroom_cage_substring_granularity,
        test_gift_card_dropped_by_tag_axis,
        test_normalize_no_auction_nulling,
        test_normalize_output_shape,
        test_yaml_mirror_parity,
    ]
    failed = 0
    for t in tests:
        try:
            t() if t in no_param else t(products)
            print(f"PASS  {t.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL  {t.__name__}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
