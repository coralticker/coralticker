"""scrapers/tests/test_reefregeneration_parse.py — CTK-148 parse-layer tests for
Reef Regeneration's Shopify /products.json shape against locked fixture
scrapers/tests/fixtures/reefregeneration/products.sample.json.

Parse-only — no DB, no network. Validates parse_shopify._normalize_product output
shape + html_hash sentinel + the NO-ALLOWLIST category_filter that makes Reef
Regeneration the ONE Shopify-fleet vendor without a product_type_allowlist.

WHY THIS TEST EXISTS (the regression it pins):
RR's product_type IS a genuine coral-genus taxonomy — the Session-1 walk
(2026-06-28, the full catalog locked as this fixture, 111 rows) found 18
product_type buckets, EVERY one coral-native (Mushroom 19, Acan 17, Zoa 15, Acro
13, Goni 10, Chalice 10, Monti 6, Torch 4, Euphyllia 4, Softies 3, Favia 2,
Blasto 2, + six single-count exotic genera: platygyra, LPS, Plate, bower,
Scolymia, Stylocoeniella). ZERO non-coral, zero equipment, zero gift cards, zero
'' bucket, zero tags on any row.

So the decision (CTK-148 #1, Jon-approved 2026-06-28) is NO product_type_allowlist
at all: RR mints a new product_type per genus (6 single-count exotics in 111
rows), and any allowlist would silently drop the NEXT genus bucket (the
allowlist-miss WARN is in_stock_only-gated, which RR doesn't set). The only gate
is a chaeto/macroalgae title_denylist forward-bind.

Two regressions a future "tidy" would silently cause, both caught here:
  - Adding a product_type_allowlist (cloning the rest of the fleet) silently
    drops any future coral genus the allowlist doesn't enumerate —
    test_no_allowlist_new_genus_survives pins that a never-before-seen genus
    survives, and test_all_exotic_buckets_survive pins today's 6 single-count
    exotics survive.
  - Coarsening / dropping the chaeto/macroalgae forward-bind (RR's ONLY junk
    gate) — test_chaeto_macroalgae_forward_bind pins it fires on synthetic
    macroalgae while leaving all 111 real coral rows kept.

INV-05 is NOT triggered: the full-catalog walk found zero auction signal (no
wk_end_auction/auc/bid tags, no product_type:Auction, no 'auction' anywhere; RR
carries no tags at all). reefregeneration.yaml carries no auction_detection
block; test_yaml_mirror_parity pins that absence so a future block can't land
unmirrored.

Mirror-parity (CTK-115 convention): test loads scrapers/vendors/
reefregeneration.yaml and asserts the in-test RR_CATEGORY_FILTER equals the YAML
block byte-exact, AND that the YAML carries NO product_type_allowlist (the
load-bearing absence) — a YAML allowlist that lands later fails
test_yaml_mirror_parity loudly.

Runnable as:
  python -m scrapers.tests.test_reefregeneration_parse

Fixture regen path: re-fetch reefregeneration.com/products.json?limit=250&page=1
and re-dump the full {"products": [...]} payload (the walk shape used at CTK-148
Session 1). NOTE: re-pinning will move the kept count + the bucket inventory as
the live catalog drifts — update test_total_kept_is_111's expected count, the
EXOTIC_BUCKET_SURVIVORS titles, and the coverage-floor NULL row to match the new
snapshot.
"""

from __future__ import annotations

import hashlib
import json
import sys
import traceback
from pathlib import Path

import yaml

from scrapers.common.normalize import infer_category
from scrapers.common.parse_shopify import (
    _normalize_product,
    _normalize_tag,
    _should_keep,
)


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "reefregeneration" / "products.sample.json"
YAML_PATH = Path(__file__).parent.parent / "vendors" / "reefregeneration.yaml"
BASE_URL = "https://reefregeneration.com"
ORIGINATOR_PREFIX = None  # CTK-148 — null (no RRG-attributed seed-list canonicals; flagged for seed-list review)
IMAGE_STRATEGY = "mirror"
AUCTION_DETECTION = None   # CTK-148 — INV-05 not triggered; no auction_detection block in the YAML

# Hand-mirror of scrapers/vendors/reefregeneration.yaml category_filter — kept
# byte-exact with the YAML; test_yaml_mirror_parity asserts the equality so a
# YAML amendment that isn't mirrored here fails loudly (CTK-115 drift class).
# NOTE the deliberate ABSENCE of product_type_allowlist — RR is the one
# Shopify-fleet vendor without one (CTK-148 #1).
RR_CATEGORY_FILTER = {
    "title_denylist": ["Chaeto", "Cheato", "Macroalgae", "Macro Algae", "Macro-Algae"],
}

# Expected keep/drop counts on the LOCKED 2026-06-28 fixture (111 rows). The
# chaeto/macroalgae forward-bind fires on ZERO real rows (RR stocks no macroalgae
# today), so the entire catalog is kept. These pin the snapshot, not live.
EXPECTED_TOTAL = 111
EXPECTED_KEPT = 111
EXPECTED_DROPPED = 0

# Coverage-floor decision (CTK-148): infer_category leaves exactly ONE row NULL
# on the locked fixture — the genus-less "bower" trade name. 1/111 = 0.9%, under
# the 10% pre-flight threshold, so _CATEGORY_PATTERNS is NOT edited for it
# (Williamson's one-off precedent). This pins that decision.
COVERAGE_NULL_THRESHOLD_PCT = 10.0
EXPECTED_NULL_TITLE = "RRG Paint Splatter Master Bower"

# The six single-count exotic-genus buckets (Session-1 walk). These are exactly
# what a naive product_type_allowlist would most likely miss -> they MUST survive
# under the no-allowlist decision. Each title is the lone member of its bucket.
EXOTIC_BUCKET_SURVIVORS = [
    "TG Platycakes Platygyra",                 # product_type 'platygyra'
    "Aquacultured Master Scolymia with Teal",  # product_type 'Scolymia'
    "Looney Tunes Stylocoeniella",             # product_type 'Stylocoeniella'
    "RRG Paint Splatter Master Bower",         # product_type 'bower' (also the NULL-category row)
    "RRG Scorched Earth Plate",                # product_type 'Plate'
    "Blue Candy Cane",                         # product_type 'LPS'
]


def _tag_denylist_norm() -> set[str]:
    """Mirror the production hoist in fetch_and_parse: normalize the YAML
    tag_denylist into the set _should_keep consumes as its 4th positional arg.
    RR carries no tag_denylist, so this is the empty set — the giftcard/tag axis
    is structurally inert here (RR has no tags). Kept for production-call parity."""
    return {_normalize_tag(e) for e in (RR_CATEGORY_FILTER.get("tag_denylist") or [])}


def _keep(p: dict) -> bool:
    """_should_keep called exactly as production does — category_filter +
    in_stock_only=False (RR has no in_stock_only) + the normalized tag_denylist."""
    return _should_keep(p, RR_CATEGORY_FILTER, False, _tag_denylist_norm())


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
    """Arch §2.6 Shopify variant: hash sorted key set of first product. Matches
    the 13-key Shopify-fleet anchor. Sentinel flips only when keys add/remove."""
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


# Test 2: total kept = 111, dropped = 0 (no allowlist + forward-bind no-op)
def test_total_kept_is_111(products):
    """Full-catalog keep count on the locked 111-row fixture: ALL 111 kept, 0
    dropped. With no product_type_allowlist and a chaeto/macroalgae forward-bind
    that matches zero real rows, the whole coral catalog survives. Any allowlist
    regression that drops coral, or a denylist that false-fires on a coral title,
    moves these counts and fails here."""
    assert len(products) == EXPECTED_TOTAL, f"fixture drifted: expected {EXPECTED_TOTAL} rows, got {len(products)}"
    kept = sum(1 for p in products if _keep(p))
    dropped = len(products) - kept
    assert kept == EXPECTED_KEPT, f"expected {EXPECTED_KEPT} kept, got {kept}"
    assert dropped == EXPECTED_DROPPED, f"expected {EXPECTED_DROPPED} dropped, got {dropped}"


# Test 3 (THE REGRESSION, part A): a never-before-seen genus survives
def test_no_allowlist_new_genus_survives(products):
    """The load-bearing no-allowlist decision: RR mints a new product_type per
    coral genus, so a future bucket the catalog hasn't shown yet MUST survive. A
    synthetic product with a brand-new product_type ('Anemone') and no denied
    title is kept — this is exactly what a product_type_allowlist would silently
    drop. If this test starts failing, someone added an allowlist; that is the
    CTK-148 #1 regression."""
    novel = {
        "title": "Rainbow Bubble Tip Anemone",
        "product_type": "Anemone",   # never appears in the locked fixture's 18 buckets
        "tags": [],
    }
    assert _keep(novel) is True, (
        "a never-before-seen coral genus was dropped — a product_type_allowlist "
        "must have been added; that silently drops future RR coral (CTK-148 #1)"
    )


# Test 4 (THE REGRESSION, part B): today's six single-count exotic buckets survive
def test_all_exotic_buckets_survive(products):
    """The six single-count exotic-genus buckets (platygyra, Scolymia,
    Stylocoeniella, bower, Plate, LPS) are exactly the rows a naive allowlist
    would most likely miss. Under the no-allowlist decision they MUST survive.
    Also asserts EVERY product_type bucket in the fixture is non-empty of
    survivors (no bucket is wholly dropped)."""
    for title in EXOTIC_BUCKET_SURVIVORS:
        p = _by_title(products, title)
        assert _keep(p) is True, f"exotic-bucket coral should have survived: {title!r}"

    # Stronger guard: every distinct product_type bucket keeps at least one row.
    buckets = {(p.get("product_type") or "") for p in products}
    for b in buckets:
        survivors = [p for p in products if (p.get("product_type") or "") == b and _keep(p)]
        assert survivors, f"product_type bucket {b!r} was wholly dropped — allowlist regression?"


# Test 5: chaeto/macroalgae forward-bind fires on synthetic, no-op on real catalog
def test_chaeto_macroalgae_forward_bind(products):
    """RR's ONLY junk gate is the chaeto/macroalgae title_denylist forward-bind.
    On the locked catalog it matches ZERO rows (RR stocks no macroalgae) —
    pure forward-bind. Pin that it WOULD fire on synthetic macroalgae rows (so a
    future leak is actually caught) while a control coral survives, and confirm
    no real row is collaterally dropped by it."""
    # Each denylist variant fires against a synthetic title containing it.
    for junk_title in [
        "Premium Chaetomorpha Algae Ball",   # 'Chaeto' substring
        "Cheato Macro Refugium Starter",     # 'Cheato' misspelling
        "Mixed Macroalgae Pack",             # 'Macroalgae'
        "Refugium Macro Algae Bundle",       # 'Macro Algae'
        "Display Macro-Algae Cluster",       # 'Macro-Algae' hyphen variant
    ]:
        junk = {"title": junk_title, "product_type": "Softies", "tags": []}
        assert _keep(junk) is False, f"macroalgae forward-bind failed to drop: {junk_title!r}"

    # A control coral with an innocuous title survives the denylist.
    control = {"title": "RRG Sub Zero Rhodactis", "product_type": "Mushroom", "tags": []}
    assert _keep(control) is True, "FP control: a coral with no denied substring must survive"

    # The forward-bind is a no-op on the real 111-row catalog (no false-fires).
    dropped_by_denylist = [
        p for p in products
        if not _keep(p)
    ]
    assert dropped_by_denylist == [], (
        f"chaeto/macroalgae forward-bind false-fired on real coral: "
        f"{[p['title'] for p in dropped_by_denylist]}"
    )


# Test 6: no auction null-out — INV-05 not triggered at the normalize layer
def test_normalize_no_auction_nulling(products):
    """reefregeneration.yaml carries no auction_detection (AUCTION_DETECTION=None),
    so coral normalizes with is_auction=False and keeps its real price — no
    collateral null-out. Pins the INV-05-not-triggered decision at the
    _normalize_product layer."""
    p = _by_title(products, "WWC Hollywood Nights Goni")
    norm = _normalize(p)
    assert norm["is_auction"] is False
    assert norm["current_price"] is not None, "non-auction coral price must not be nulled"


# Test 7: _normalize_product output shape — coral product
def test_normalize_output_shape(products):
    """_normalize_product on a coral — validates output dict shape per arch §1.4
    vendor_listings columns + absolute product_url (CTK-033 D1)."""
    p = _by_title(products, "WWC Hollywood Nights Goni")
    norm = _normalize(p)
    assert norm["raw_title"] == "WWC Hollywood Nights Goni"
    assert norm["product_url"].startswith("https://reefregeneration.com/products/")
    assert norm["currency"] == "USD"
    assert norm["vendor_image_url"] is not None
    assert "cdn.shopify.com" in norm["vendor_image_url"]


# Test 8: coverage floor — NULL-category ratio under threshold, the one NULL is bower
def test_category_coverage_floor(products):
    """CTK-148 coverage decision: infer_category leaves exactly ONE row NULL on
    the locked fixture (the genus-less 'bower' trade name), 0.9% < 10% threshold,
    so _CATEGORY_PATTERNS is NOT edited for it. This pins the decision: if a
    future _CATEGORY_PATTERNS change pushes RR's NULL ratio over threshold, this
    fails and forces a conscious re-look. Also asserts the lone NULL is the
    expected bower row (a different NULL row appearing is a coverage regression)."""
    null_titles = [p.get("title") for p in products if infer_category(p) is None]
    ratio = len(null_titles) / len(products) * 100
    assert ratio <= COVERAGE_NULL_THRESHOLD_PCT, (
        f"category coverage regressed: {ratio:.1f}% NULL > {COVERAGE_NULL_THRESHOLD_PCT}% "
        f"(NULL rows: {null_titles})"
    )
    assert null_titles == [EXPECTED_NULL_TITLE], (
        f"NULL-category set drifted — expected only {EXPECTED_NULL_TITLE!r}, got {null_titles}"
    )


# Test 9 (MIRROR-PARITY, CTK-115): in-test filter == reefregeneration.yaml byte-exact
def test_yaml_mirror_parity():
    """CTK-115 mirror-parity: the in-test RR_CATEGORY_FILTER must equal the
    scrapers/vendors/reefregeneration.yaml category_filter byte-exact, the YAML
    must carry NO product_type_allowlist (the load-bearing CTK-148 #1 absence),
    NO auction_detection block (INV-05 not triggered), and NO in_stock_only.

    The keys-exact assertion is load-bearing: this test (and _keep()) model only
    the single axis RR uses today (title_denylist) with in_stock_only=False. If a
    future maintainer adds product_type_allowlist (the exact regression this
    ticket exists to prevent) or any other axis, the locked-fixture keep count
    would NOT reflect it and the suite would stay green against diverged
    production behavior. So we fail loudly the moment the YAML's filter-axis set —
    or the in_stock_only flag — drifts from what this test models."""
    cfg = yaml.safe_load(YAML_PATH.read_text(encoding="utf-8"))
    yaml_filter = cfg["category_filter"]
    assert yaml_filter.get("title_denylist", []) == RR_CATEGORY_FILTER["title_denylist"], (
        "title_denylist drift between reefregeneration.yaml and the test mirror"
    )
    # The load-bearing absence: NO product_type_allowlist (CTK-148 #1).
    assert "product_type_allowlist" not in yaml_filter, (
        "reefregeneration.yaml grew a product_type_allowlist — that is the CTK-148 #1 "
        "regression (silent drop of future coral genera). Re-walk + re-decide before adding."
    )
    # Keys-exact: no unmodeled filter axis may appear.
    assert set(yaml_filter.keys()) == set(RR_CATEGORY_FILTER.keys()), (
        f"reefregeneration.yaml category_filter grew/changed an axis the test mirror "
        f"doesn't model: YAML={sorted(yaml_filter.keys())} vs "
        f"mirror={sorted(RR_CATEGORY_FILTER.keys())} — extend RR_CATEGORY_FILTER + _keep()"
    )
    assert "in_stock_only" not in cfg, (
        "reefregeneration.yaml set in_stock_only — _keep() hardcodes False and the "
        "locked count would no longer reflect production; thread it through the test"
    )
    assert cfg.get("auction_detection") is None, (
        "reefregeneration.yaml grew an auction_detection block — INV-05 disposition changed; "
        "re-confirm the walk + update this test mirror"
    )


def main() -> int:
    products = _load_fixture()
    no_param = {test_yaml_mirror_parity}
    tests = [
        test_html_hash_first_product_keys,
        test_total_kept_is_111,
        test_no_allowlist_new_genus_survives,
        test_all_exotic_buckets_survive,
        test_chaeto_macroalgae_forward_bind,
        test_normalize_no_auction_nulling,
        test_normalize_output_shape,
        test_category_coverage_floor,
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
