"""scrapers/tests/test_tsa_parse.py — CTK-026 parse-layer tests for TSA's
Shopify /products.json shape against locked fixture
scrapers/tests/fixtures/tsa/products.sample.json.

Parse-only — no DB, no network. Validates parse_shopify._normalize_product
output shape + html_hash sentinel computation across seven curated TSA
products covering: TSA-prefix coral OOS, TSA-prefix coral in-stock, no-
prefix coral OOS (matcher §3.4 stage 3 case), no-prefix coral in-stock,
fish (non-coral category-inference path), multi-variant merch (variant-
list logic), no-SKU edge case (sku=None).

Runnable as:
  python -m scrapers.tests.test_tsa_parse

Fixture regen path documented in scrapers/vendors/tsa.py docstring (CTK-024/
025/026 convention).

Coverage:
  test_html_hash_first_product_keys                      arch §2.6 sentinel
  test_tsa_prefix_coral_normalize_preserves_prefix       decision #18
  test_no_prefix_coral_normalize_no_synthesis            stage 3 input shape
  test_oos_product_in_stock_false                        variants.available
  test_in_stock_product_in_stock_true                    variants.available
  test_multi_variant_merch_in_stock_any                  any-available logic
  test_no_sku_product_sku_none                           sku selection edge
  test_product_url_absolute                              CTK-033 D1 anchor
  test_vendor_image_url_first_image                      images[0].src
  test_currency_usd_default                              Q1-3 lock
  test_lineage_flag_vendor_named_on_caps_prefix          infer_lineage_flag
  test_category_inference                                arch §1.4 enum
"""

from __future__ import annotations

import hashlib
import json
import sys
import traceback
from pathlib import Path

from scrapers.common.parse_shopify import _normalize_product, _should_keep


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "tsa" / "products.sample.json"
BASE_URL = "https://topshelfaquatics.com"
ORIGINATOR_PREFIX = "tsa"  # matches scrapers/vendors/tsa.yaml D3-equivalent lock
IMAGE_STRATEGY = "mirror"

# Mirrors scrapers/vendors/tsa.yaml category_filter block (CTK-037 2026-05-10;
# Session 4.6 added Coral-POS; Session 5 added empty-string for ~62-row
# real-coral recovery in the empty-product_type bucket — Q-8 path (a)).
# Livestock product_type covers both coral + fish; tag-denylist rejects fish
# tags within Livestock. Anemone tag NOT in denylist per D1 lean (a) seed-list
# coverage. Equipment (Aquarium Supplies / Oversized / Drop shipped) denied
# by allowlist default.
TSA_CATEGORY_FILTER = {
    "product_type_allowlist": ["", "Coral-POS", "Livestock"],
    # Mirrors the production scrapers/vendors/tsa.yaml 29-entry tag_denylist:
    # 6 reef-safety tag family (CTK-104 D-1 structural fish gate) + 3 equipment
    # tags (CTK-104 D-2 jellyfish-aquarium plug for the blank-PT allowlist
    # entry) + 12 per-genus fish (D-1A belt-and-suspenders) + 8 invert / bio-
    # media (CTK-041 + CTK-095 + Biomedia per CTK-107 D-2-tris; the Biomedia
    # entry was missing from this mirror until the CTK-112 review-fold).
    # Sorted alphabetically to match YAML.
    "tag_denylist": [
        "Algae Eater", "All-in-One Aquariums", "Angelfish", "Aquariums",
        "Beginner Fish", "Biomedia", "Clam", "Clownfish", "EXPERT ONLY",
        "Filefish", "Goby", "Hawkfish", "Invert", "Jellyfish Art",
        "Live Rock", "Macroalgae", "Mangrove", "Nano Fish", "Non Reef Safe",
        "Not Reef Safe", "Predator", "Reef Safe", "Reef Safe Caution",
        "Refugiums", "Tang", "Tilefish", "Wrasse", "Wrasses", "WYSIWYG Fish",
    ],
    # Mirrors scrapers/vendors/tsa.yaml title_denylist. The prior mirror omitted
    # this axis entirely (stale vs. CTK-107's title-axis additions); brought to
    # full parity here so the CTK-112 "Late Fees" reject + false-kill guard tests
    # exercise the same predicate the production YAML carries. Entries: CTK-107
    # placeholder + chaeto/macroalgae belt-and-suspenders, CTK-112 store-credit SKU.
    "title_denylist": [
        "Test Livestock", "Chaeto", "Cheato", "Macroalgae", "Macro Algae",
        "Late Fees",
    ],
}


def _load_fixture() -> list[dict]:
    with FIXTURE_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)["products"]


# CTK-039 pytest fixture wrapper — exposes the script-mode `_load_fixture()`
# return value as a pytest fixture so collected `def test_X(products)` test
# functions resolve cleanly under `pytest scrapers/tests/`. Script-mode
# invocation (`python -m scrapers.tests.test_tsa_parse`) continues to work
# via main()'s direct `_load_fixture()` call; the pytest decorator is
# metadata-only in that path.
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


def _normalize(p: dict) -> dict:
    return _normalize_product(p, BASE_URL, IMAGE_STRATEGY, ORIGINATOR_PREFIX)


# ─── Test 1: html_hash sentinel — sorted-keys-of-first-product SHA256 ─────────
def test_html_hash_first_product_keys(products):
    """Arch §2.6 Shopify variant: hash sorted key set of first product object.
    F5 fold (sort-before-hash) in parse_shopify.py:82 — Shopify can change JSON
    key emission order across versions without a real schema change; sorting
    collapses ordering noise. The hash flips ONLY when keys are added/removed.
    """
    first = products[0]
    keys = sorted(first.keys())
    expected = hashlib.sha256(",".join(keys).encode("utf-8")).hexdigest()
    # Empirical anchor: 13 keys per smoke 2026-05-07. PE+WWC also have 13 keys.
    assert len(keys) == 13, (
        f"expected 13 keys on first product (matches PE+WWC empirical anchor), "
        f"got {len(keys)}: {keys}"
    )
    expected_keys = [
        "body_html", "created_at", "handle", "id", "images", "options",
        "product_type", "published_at", "tags", "title", "updated_at",
        "variants", "vendor",
    ]
    assert keys == expected_keys, (
        f"first-product key set drift — expected {expected_keys}, got {keys}. "
        f"If a key was added/removed, the html_hash sentinel will flip and "
        f"scraper_runs.error_class='html_schema_change' will fire next scrape."
    )
    assert len(expected) == 64, f"SHA256 hex digest is 64 chars; got {len(expected)}"


# ─── Test 2: TSA-prefix coral — normalize PRESERVES prefix per decision #18 ───
def test_tsa_prefix_coral_normalize_preserves_prefix(products):
    """Per decision #18 (§3.2 cascade fix): vendor prefix is preserved in
    normalized_title. The matcher §3.4 stage 3 prepends originator_prefix at
    match-time for no-prefix titles; it does NOT strip an existing prefix from
    prefix-bearing titles. originator_prefix YAML config does not affect
    normalize_title output (decision #23 + decision #18 interaction).
    """
    p = _by_title(products, "TSA Deep Soul Favia Coral")
    out = _normalize(p)
    assert out["raw_title"] == "TSA Deep Soul Favia Coral"
    assert out["normalized_title"] == "tsa deep soul favia coral", (
        f"prefix should be preserved (lowercase only); got {out['normalized_title']!r}"
    )


# ─── Test 3: no-prefix coral — normalize_title is bare (matcher §3.4 stage 3) ─
def test_no_prefix_coral_normalize_no_synthesis(products):
    """Per matcher §3.4 stage 3: no-prefix titles are normalized to bare
    ("beast boy favia coral"). Stage 3 SYNTHESIZES "tsa beast boy favia coral"
    against canonical-prefix patterns at match-time; that synthesis lives in
    matcher.py, not parse_shopify. This test pins the parse-layer contract.
    """
    p = _by_title(products, "Beast Boy Favia Coral")
    out = _normalize(p)
    assert out["normalized_title"] == "beast boy favia coral", (
        f"no-prefix title should normalize bare; got {out['normalized_title']!r}"
    )


# ─── Test 4: OOS product — variants.available all false → in_stock=False ──────
def test_oos_product_in_stock_false(products):
    """Arch §2.1 stage 4 in_stock semantics: any(v.get('available')) across
    variants. Between-drop window TSA corals are typically OOS — fixture
    captures this realistic state. price_history diff logic depends on
    in_stock toggling correctly so price-changed-while-OOS doesn't trip a
    stock-changed event."""
    p = _by_title(products, "TSA Deep Soul Favia Coral")
    out = _normalize(p)
    assert out["in_stock"] is False, f"expected in_stock=False, got {out['in_stock']!r}"


# ─── Test 5: in-stock product → in_stock=True ─────────────────────────────────
def test_in_stock_product_in_stock_true(products):
    p = _by_title(products, "Krak God Zoanthids Coral")
    out = _normalize(p)
    assert out["in_stock"] is True, f"expected in_stock=True, got {out['in_stock']!r}"


# ─── Test 6: multi-variant merch — any-available decides in_stock ─────────────
def test_multi_variant_merch_in_stock_any(products):
    """T-shirt with 6 size variants. in_stock=True if ANY variant available;
    in_stock=False only if ALL variants are unavailable. Phase 1 stock-flip
    de-duplication depends on this any-semantics — a single-size restock
    on a multi-variant product flips in_stock True without false-positive
    'all sizes restocked'."""
    p = _by_title(products, "TSA Coral Pattern Outline UV Reactive T-Shirt")
    variants = p.get("variants") or []
    assert len(variants) > 1, f"fixture multi-variant pick should have >1 variants; got {len(variants)}"
    out = _normalize(p)
    expected = any(v.get("available") for v in variants)
    assert out["in_stock"] is expected, (
        f"in_stock={out['in_stock']!r} doesn't match any(available)={expected!r}"
    )


# ─── Test 7: no-SKU product → vendor_sku=None ─────────────────────────────────
def test_no_sku_product_sku_none(products):
    """Hydros Duet variant emits sku=None (or empty). parse_shopify picks the
    first non-empty SKU across variants; if none, returns None. NOT NULL on
    vendor_listings.vendor_sku is not enforced (per arch §1.4 + CTK-024 0002
    drop-vendor-sku-unique migration), so None lands cleanly."""
    p = _by_title(products, "Hydros Duet Dosing Pump & Aquarium Controller - Hydros")
    out = _normalize(p)
    assert out["vendor_sku"] is None, (
        f"expected vendor_sku=None for no-SKU product; got {out['vendor_sku']!r}"
    )


# ─── Test 8: product_url is absolute (CTK-033 D1 anchor) ──────────────────────
def test_product_url_absolute(products):
    """Per CTK-033 D1 + arch §2.1 stage 4 normalize lock: product_url is
    ABSOLUTE (base_url joined to /products/<handle>). The diff.classify()
    lookup against existing_by_url depends on this — relative URLs would
    miss the dict and force-classify every existing listing as 'new' on the
    next-day scrape (price_history explosion + redundant re-mirroring)."""
    for p in products:
        out = _normalize(p)
        assert out["product_url"].startswith(BASE_URL + "/products/"), (
            f"product_url not absolute for {p['title']!r}: {out['product_url']!r}"
        )
        assert out["product_url"].endswith(p["handle"]), (
            f"product_url missing handle suffix for {p['title']!r}: {out['product_url']!r}"
        )


# ─── Test 9: vendor_image_url is images[0].src (raw, pre-mirror) ──────────────
def test_vendor_image_url_first_image(products):
    """Phase B mirror queue pulls vendor_image_url and writes image_url after
    R2 storage. Parse layer just hands over the raw vendor URL untouched."""
    p = _by_title(products, "TSA Deep Soul Favia Coral")
    out = _normalize(p)
    expected_src = p["images"][0]["src"]
    assert out["vendor_image_url"] == expected_src, (
        f"vendor_image_url should be images[0].src; expected {expected_src!r}, "
        f"got {out['vendor_image_url']!r}"
    )


# ─── Test 10: currency = USD per Q1-3 lock ────────────────────────────────────
def test_currency_usd_default(products):
    """Phase 1 vendors all USD per Q1-3 (arch §1.4 / decision register). Parse
    layer hardcodes USD; currency-aware logic re-opens at Phase 2 if any vendor
    ships non-USD."""
    for p in products:
        out = _normalize(p)
        assert out["currency"] == "USD", (
            f"currency drift on {p['title']!r}: expected 'USD', got {out['currency']!r}"
        )


# ─── Test 11: lineage_flag — vendor-named on ALL-CAPS prefix ──────────────────
def test_lineage_flag_vendor_named_on_caps_prefix(products):
    """infer_lineage_flag fires 'vendor-named' on 2-4 char ALL-CAPS prefix
    followed by title-case (matches "TSA Deep Soul..." pattern). 'unknown'
    otherwise. Cheap heuristic; matcher §3 does real lineage work."""
    tsa_prefix = _by_title(products, "TSA Deep Soul Favia Coral")
    no_prefix = _by_title(products, "Beast Boy Favia Coral")
    fish = _by_title(products, "Powder Blue Tang")

    assert _normalize(tsa_prefix)["lineage_flag"] == "vendor-named", (
        "TSA-prefix coral should flip lineage_flag to vendor-named"
    )
    assert _normalize(no_prefix)["lineage_flag"] == "unknown", (
        "no-prefix coral should be lineage_flag=unknown (matcher §3 does real work)"
    )
    assert _normalize(fish)["lineage_flag"] == "unknown", (
        "fish (non-coral) should be lineage_flag=unknown"
    )


# ─── Test 12: category inference per arch §1.4 enum ───────────────────────────
def test_category_inference(products):
    """infer_category matches against product_type + tags + title. Arch §1.4
    enum: ('sps','lps','softie','zoa','mushroom','anemone','clam','chalice',
    'fish','invert','equipment','other'). First-hit wins; more specific
    before generic. Favia/Acan → lps; Zoanthids → zoa; Tang → fish."""
    favia = _by_title(products, "TSA Deep Soul Favia Coral")
    zoa = _by_title(products, "Krak God Zoanthids Coral")
    tang = _by_title(products, "Powder Blue Tang")

    assert _normalize(favia)["category"] == "lps", (
        f"Favia should match lps; got {_normalize(favia)['category']!r}"
    )
    assert _normalize(zoa)["category"] == "zoa", (
        f"Zoanthids should match zoa; got {_normalize(zoa)['category']!r}"
    )
    assert _normalize(tang)["category"] == "fish", (
        f"Tang should match fish; got {_normalize(tang)['category']!r}"
    )


# ─── Test 13 (CTK-037): filter keeps TSA-prefix coral (Livestock product_type) ─
def test_filter_keeps_tsa_livestock_coral(products):
    """TSA Livestock allowlist + no fish-tag denylist hit = KEEP. Anchor case
    for the 96% of Livestock that's coral."""
    p = _by_title(products, "TSA Deep Soul Favia Coral")
    assert _should_keep(p, TSA_CATEGORY_FILTER) is True


# ─── Test 14 (CTK-037): filter rejects Aquarium Supplies (equipment) ─────────
def test_filter_rejects_tsa_aquarium_supplies_equipment(products):
    """Equipment lives outside Livestock allowlist — rejected without
    consulting tag_denylist. Hydros Duet is the empirical anchor case."""
    p = _by_title(products, "Hydros Duet Dosing Pump & Aquarium Controller - Hydros")
    assert _should_keep(p, TSA_CATEGORY_FILTER) is False


# ─── Test 15 (CTK-037): filter rejects merch (T-shirt, Aquarium Supplies) ────
def test_filter_rejects_tsa_merch_apparel(products):
    """T-shirt product_type='Aquarium Supplies' — TSA's apparel + equipment
    share this product_type, both denied by allowlist."""
    p = _by_title(products, "TSA Coral Pattern Outline UV Reactive T-Shirt")
    assert _should_keep(p, TSA_CATEGORY_FILTER) is False


# ─── Test 16 (CTK-037): tag-denylist rejects fish within Livestock ────────────
def test_filter_tsa_tag_denylist_rejects_tang(products):
    """Powder Blue Tang is product_type='Livestock' (passes allowlist) but
    carries tags ['Reef Safe', 'Tang', 'WYSIWYG Fish']. Tang + WYSIWYG Fish
    both match tag_denylist — rejected. Load-bearing test for Q-B lock
    (allowlist primary + tag-denylist secondary)."""
    p = _by_title(products, "Powder Blue Tang")
    assert _should_keep(p, TSA_CATEGORY_FILTER) is False
    assert "Tang" in p["tags"]


# ─── Test 17 (CTK-037): permissive default when no category_filter block ──────
def test_filter_tsa_permissive_when_no_block(products):
    """Phase 2 vendor onboarding inheritance — None or {} = no gate. Every
    fixture product passes (including the fish + equipment that the real TSA
    filter rejects)."""
    for p in products:
        assert _should_keep(p, None) is True
        assert _should_keep(p, {}) is True


# ─── Test 18 (CTK-037 / CTK-041 Session 2): skip-count across TSA fixture ─────
def test_filter_tsa_skip_count_matches(products):
    """TSA fixture composition: 4 Livestock coral (Deep Soul Favia, Berry Bash
    Echinata, Beast Boy Favia, Krak God Zoanthids) + 1 Livestock fish (Powder
    Blue Tang — tag-denylist hit per CTK-037) + 2 Aquarium Supplies (T-shirt +
    Hydros Duet — allowlist miss) + 3 Livestock non-coral (CTK-041 Session 2
    additions — Skunk Cleaner Shrimp / Chaeto Macroalgae / Mexican Turbo
    Snail; tag-denylist hits on Invert / Macroalgae / Algae Eater).
    Expected: 4 kept, 6 skipped."""
    kept = sum(1 for p in products if _should_keep(p, TSA_CATEGORY_FILTER))
    skipped = sum(1 for p in products if not _should_keep(p, TSA_CATEGORY_FILTER))
    assert kept == 4, f"expected 4 kept, got {kept}"
    assert skipped == 6, f"expected 6 skipped, got {skipped}"


# ─── CTK-041 Session 2: tag_denylist rejects Livestock + Invert tag ──────────
def test_filter_rejects_livestock_invert(products):
    """CTK-041 Session 2 — Invert umbrella tag catches Shrimp/Crab/Urchin/
    Starfish/Snail/Lobster co-carry per live audit. Skunk Cleaner Shrimp is
    product_type='Livestock' (passes allowlist) + tags include Invert + Shrimp
    — Invert match short-circuits reject."""
    p = _by_title(products, "Skunk Cleaner Shrimp")
    assert _should_keep(p, TSA_CATEGORY_FILTER) is False
    assert "Invert" in p["tags"]


# ─── CTK-041 Session 2: tag_denylist rejects Livestock + Macroalgae tag ──────
def test_filter_rejects_livestock_macroalgae(products):
    """CTK-041 Session 2 — Macroalgae is bio-media algae; refugium-shape
    content surfaced inside Livestock allowlist per Jon-eyeball /vendor/tsa
    2026-05-19. Chaeto Macroalgae is product_type='Livestock' + tags
    [Macroalgae, Refugiums]."""
    p = _by_title(products, "Chaeto Macroalgae")
    assert _should_keep(p, TSA_CATEGORY_FILTER) is False


# ─── CTK-112 review-fold: tag-axis isolation for bio-media tags ───────────────
def test_filter_rejects_biomedia_tags_on_tag_axis_alone(products):
    """CTK-112 review-fold finding #2 — the 'Chaeto Macroalgae' fixture above is
    double-covered post-CTK-112: its TITLE also matches the mirror's
    title_denylist ('Chaeto'/'Macroalgae'), so test_filter_rejects_livestock_
    macroalgae would keep passing even if the Macroalgae/Refugiums tag entries
    were deleted — the title axis masks a tag-axis regression. Pin the tag axis
    in isolation: synthetic products whose titles carry NO denylist substring
    must reject on the bio-media tag alone (one product per tag, mirroring the
    reef-safety family test shape). Biomedia included per review-fold finding #1
    (entry was absent from this mirror until the fold; previously untested)."""
    title_denylist_lc = [e.lower() for e in TSA_CATEGORY_FILTER["title_denylist"]]
    for bio_tag in ("Macroalgae", "Refugiums", "Biomedia"):
        # Title deliberately excludes the tag name — "Macroalgae" in the title
        # would re-trigger the title axis and defeat the isolation.
        product = {
            "title": "Fictitious Green Bundle",
            "product_type": "Livestock",
            "tags": [bio_tag],
            "variants": [{"available": True}],
        }
        assert not any(e in product["title"].lower() for e in title_denylist_lc), (
            "self-check: synthetic title must carry no title_denylist substring, "
            "or this test stops isolating the tag axis"
        )
        assert _should_keep(product, TSA_CATEGORY_FILTER) is False, (
            f"bio-media tag {bio_tag!r} should reject on the tag axis alone "
            f"(clean title); product passed"
        )


# ─── CTK-041 Session 2: tag_denylist rejects Livestock + Algae Eater tag ─────
def test_filter_rejects_livestock_algae_eater(products):
    """CTK-041 Session 2 — Algae Eater catches algae-utility inverts (snails
    + crabs sold for algae control). Mexican Turbo Snail is
    product_type='Livestock' + tags [Algae Eater, Invert, Snail] — multi-tag
    intersection short-circuits on first match."""
    p = _by_title(products, "Mexican Turbo Snail")
    assert _should_keep(p, TSA_CATEGORY_FILTER) is False


# ─── CTK-104 D-1 happy-path: reef-safety tag rejects even on Livestock allowlist ─
def test_filter_rejects_reef_safety_tag_family(products):
    """CTK-104 D-1 (2026-06-01) — reef-safety rating tag family
    (Reef Safe / Reef Safe Caution / Non Reef Safe / Not Reef Safe / EXPERT ONLY
    / Predator) is the primary structural fish gate. TSA tags every fish with
    one of these; corals carry none (live full-catalog scan 2026-06-01: 83
    in-stock reef-safety-tagged rows, 0 coral, 0 anemone). The denylist gate
    must fire on the reef-safety tag ALONE — even when no per-genus fish tag
    co-carries — so the structural family catches future fish leaks without
    waiting on per-genus enumeration. Synthetic fixtures pin each tag of the
    family individually so a YAML drop of any one entry breaks this test."""
    for rs_tag in ("Reef Safe", "Reef Safe Caution", "Non Reef Safe",
                   "Not Reef Safe", "EXPERT ONLY", "Predator"):
        product = {
            "title": f"Fictitious Test Fish ({rs_tag})",
            "product_type": "Livestock",
            "tags": [rs_tag],
            "variants": [{"available": True}],
        }
        assert _should_keep(product, TSA_CATEGORY_FILTER) is False, (
            f"reef-safety tag {rs_tag!r} should reject on its own; product passed"
        )


# ─── CTK-104 D-1 false-kill guard: coral with no reef-safety tag still passes ─
def test_filter_keeps_coral_without_reef_safety_tag(products):
    """CTK-104 D-1 false-kill guard — the reef-safety discriminator must not
    false-fire on corals. All four real-shape coral fixtures (TSA Deep Soul
    Favia / TSA Berry Bash Echinata / Beast Boy Favia / Krak God Zoanthids)
    carry no reef-safety tag in the live catalog and must pass the filter post-
    CTK-104. Pin behavior across the full coral fixture surface — drop of a
    coral row would surface as a fixture maintenance failure, not as a silent
    discriminator regression."""
    coral_titles = [
        "TSA Deep Soul Favia Coral",
        "TSA Berry Bash Echinata Coral",
        "Beast Boy Favia Coral",
        "Krak God Zoanthids Coral",
    ]
    reef_safety_set = {"Reef Safe", "Reef Safe Caution", "Non Reef Safe",
                       "Not Reef Safe", "EXPERT ONLY", "Predator"}
    for title in coral_titles:
        p = _by_title(products, title)
        tags = set(p.get("tags") or [])
        assert not (tags & reef_safety_set), (
            f"coral fixture {title!r} carries reef-safety tag {tags & reef_safety_set!r}; "
            f"fixture drift — false-kill-guard test no longer pinning the intended invariant"
        )
        assert _should_keep(p, TSA_CATEGORY_FILTER) is True, (
            f"coral {title!r} rejected by post-CTK-104 filter (false-kill); "
            f"tags={p.get('tags')}"
        )


# ─── CTK-104 D-2: equipment tag rejects jellyfish-aquarium leak under blank-PT ─
def test_filter_rejects_equipment_tag_under_blank_pt(products):
    """CTK-104 D-2 (2026-06-01) — the blank-product_type allowlist entry was
    retained at CTK-037 for ~62-row real-coral recovery (Q-8 path (a)) but
    leaks Kreisel / Jelly Cylinder jellyfish aquariums (3 in stock 2026-06-01:
    `product_type=''`, tags=['Aquariums', 'All-in-One Aquariums', 'Jellyfish
    Art']). Three equipment tags added to tag_denylist to plug the leak.
    Synthetic fixture pins each equipment tag individually."""
    for eq_tag in ("Aquariums", "All-in-One Aquariums", "Jellyfish Art"):
        product = {
            "title": f"Fictitious Test Equipment ({eq_tag})",
            "product_type": "",  # the load-bearing leak surface
            "tags": [eq_tag],
            "variants": [{"available": True}],
        }
        assert _should_keep(product, TSA_CATEGORY_FILTER) is False, (
            f"equipment tag {eq_tag!r} should reject under blank-PT; product passed"
        )


# ─── CTK-112: title_denylist rejects the "Late Fees" store-credit/penalty SKU ──
def test_filter_rejects_late_fees_store_credit_sku(products):
    """CTK-112 (2026-06-03) — "Late Fees" ($361) is a store-credit / penalty SKU,
    not livestock. It leaked to /new because product_type='' is allowlisted (for
    blank-PT coral recovery, CTK-037 Q-8 path (a)) and tags=[] blinds the
    tag_denylist — only the title axis catches it. Pin the structural shape that
    made it leak (blank PT + empty tags) so the reject is attributed to the
    title_denylist axis, not an incidental tag/PT block."""
    product = {
        "title": "Late Fees",
        "product_type": "",   # blank-PT allowlist entry — the leak surface
        "tags": [],           # empty tags — tag_denylist is blind here
        "variants": [{"available": True}],
    }
    assert _should_keep(product, TSA_CATEGORY_FILTER) is False, (
        "'Late Fees' should reject via title_denylist under blank-PT + empty-tags; "
        "product passed the filter"
    )


# ─── CTK-112 false-kill guard: coral with a "fee" substring still passes ───────
def test_filter_keeps_coral_with_fee_substring(products):
    """CTK-112 false-kill guard — the "Late Fees" entry is a COMPOUND phrase, not
    a bare "fee"/"fees", precisely so it can't substring-fire on coral lineages
    that carry "fee" inside a word (Toffee / Coffee zoanthid morphs are real reef
    names). Live /products.json pull 2026-06-03 (4,220 products) confirmed "late
    fees" substring-matches exactly 1 row (the SKU itself), 0 coral. This synthetic
    coral — "Toffee Nuclear Zoanthid", blank-PT to share Late Fees' leak surface —
    must survive the filter; a regression to a bare "fee"/"fees" entry breaks it.

    Two synthetics, one per regression shape (CTK-112 review-fold finding #3 —
    "toffee" contains "fee" but not "fees", so a Toffee-only guard passed
    vacuously against a bare-"fees" regression while claiming to cover it):
    "Toffee ..." catches bare-"fee"; "Coffees ..." catches bare-"fees"."""
    for title in ("Toffee Nuclear Zoanthid Coral", "Coffees & Cream Zoa Coral"):
        coral = {
            "title": title,
            "product_type": "",   # same blank-PT path Late Fees travels
            "tags": [],
            "variants": [{"available": True}],
        }
        assert _should_keep(coral, TSA_CATEGORY_FILTER) is True, (
            f"coral {title!r} false-killed by title_denylist — the 'Late Fees' "
            f"entry must stay compound, never bare 'fee'/'fees'"
        )


# ─── Test 19 (CTK-037 Session 5.5): predicate normalization keeps None/absent ─
def test_filter_normalizes_none_product_type_to_empty_string(products):
    """CTK-037 Session 5.5 — None or key-absent product_type normalizes to "" so
    TSA empty-string allowlist entry matches both Shopify shape variants. Prevents
    silent recall regression if Shopify shifts empty-bucket representation."""
    product_none = {"product_type": None, "title": "Some coral", "tags": []}
    product_missing = {"title": "Some coral", "tags": []}  # key absent
    cf = TSA_CATEGORY_FILTER  # has "" in allowlist post-Session-5
    assert _should_keep(product_none, cf) is True
    assert _should_keep(product_missing, cf) is True


# ─── Test 20 (CTK-037 Session 5.5): normalization is symmetric (rejects too) ──
def test_filter_rejects_none_product_type_when_empty_not_in_allowlist(products):
    """CTK-037 Session 5.5 — normalization is symmetric; None still rejects when
    "" is not in the allowlist (e.g., PE / WWC / JF YAMLs)."""
    product = {"product_type": None, "title": "Some coral", "tags": []}
    cf = {"product_type_allowlist": ["Livestock"], "tag_denylist": []}
    assert _should_keep(product, cf) is False


def main() -> int:
    products = _load_fixture()
    print(f"loaded fixture: {len(products)} products from {FIXTURE_PATH}")

    tests = [
        test_html_hash_first_product_keys,
        test_tsa_prefix_coral_normalize_preserves_prefix,
        test_no_prefix_coral_normalize_no_synthesis,
        test_oos_product_in_stock_false,
        test_in_stock_product_in_stock_true,
        test_multi_variant_merch_in_stock_any,
        test_no_sku_product_sku_none,
        test_product_url_absolute,
        test_vendor_image_url_first_image,
        test_currency_usd_default,
        test_lineage_flag_vendor_named_on_caps_prefix,
        test_category_inference,
        test_filter_keeps_tsa_livestock_coral,
        test_filter_rejects_tsa_aquarium_supplies_equipment,
        test_filter_rejects_tsa_merch_apparel,
        test_filter_tsa_tag_denylist_rejects_tang,
        test_filter_tsa_permissive_when_no_block,
        test_filter_tsa_skip_count_matches,
        test_filter_rejects_livestock_invert,
        test_filter_rejects_livestock_macroalgae,
        test_filter_rejects_biomedia_tags_on_tag_axis_alone,
        test_filter_rejects_livestock_algae_eater,
        test_filter_rejects_reef_safety_tag_family,
        test_filter_keeps_coral_without_reef_safety_tag,
        test_filter_rejects_equipment_tag_under_blank_pt,
        test_filter_rejects_late_fees_store_credit_sku,
        test_filter_keeps_coral_with_fee_substring,
        test_filter_normalizes_none_product_type_to_empty_string,
        test_filter_rejects_none_product_type_when_empty_not_in_allowlist,
    ]

    failures: list[tuple[str, str]] = []
    for fn in tests:
        name = fn.__name__
        try:
            fn(products)
            print(f"  [PASS] {name}")
        except AssertionError as e:
            print(f"  [FAIL] {name}: {e}")
            failures.append((name, str(e)))
        except Exception as e:  # noqa: BLE001
            print(f"  [ERROR] {name}: {type(e).__name__}: {e}")
            traceback.print_exc()
            failures.append((name, f"{type(e).__name__}: {e}"))

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
