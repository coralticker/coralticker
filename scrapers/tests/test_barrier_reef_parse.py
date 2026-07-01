"""scrapers/tests/test_barrier_reef_parse.py — CTK-151 parse-layer tests for Barrier
Reef Aquariums' Shopify /products.json shape against locked fixture
scrapers/tests/fixtures/barrier_reef/products.sample.json (2026-07-01 full-catalog
walk, 1,722 rows across 7 pages — NOT a page-1 sample, per CTK-142 lesson +
feedback_absence_diag_full_catalog_sweep).

CTK-208: driven by the shared scrapers/tests/vendor_parse_harness.py — a
VendorParseConfig + the fixture + the Barrier-Reef-specific regressions below.

Parse-only — no DB, no network. Validates the tag_allowlist category_filter that
makes Barrier Reef the FLEET'S FIRST CORAL-MINORITY tag_allowlist store.

WHY THIS TEST EXISTS (the regressions it pins):
Barrier Reef is a full reef LFS where corals are the MINORITY of a 1,722-row
catalog (fish / inverts / equipment / apparel / swag dominate). product_type is
blank on 1,561/1,722, so neither a product_type_allowlist (Biota) nor a
no-allowlist title_denylist (Cherry/Coral Stop) fits — the posture flips to a
tag_allowlist on the 10 coral category tags the catalog already carries. See
barrier_reef.yaml's SHAPE / failure-asymmetry block.

The load-bearing regression (the reason the allowlist is correct here, INVERTING
the Cherry/Coral Stop no-allowlist logic): a no-allowlist posture would render the
vendor page as majority fish-and-pumps. test_fish_and_equipment_excluded pins that
fish/equipment drop; test_coral_tags_kept pins that coral survives.

Other regressions pinned:
  - The 5 vendor-coral-tagged inverts (clams/anemones) ride along on 'Coral WYSIWYG'
    and classify NON-NULL (clam/anemone), NOT the INV-07-hidden 'invert', and NOT
    NULL — test_coral_tagged_inverts_classify_non_null. A NULL there would leak them
    into coral counts (INV-07 is a denylist, keeps NULLs).
  - '$10 Value' budget-frag corals with no other coral tag survive —
    test_ten_dollar_value_corals_kept.
  - Fish 'SW Fish WYSIWYG' must NOT leak via the 'Coral WYSIWYG' allowlist entry
    (exact tag match, not substring) — test_fish_wysiwyg_not_leaked.
  - The accepted single miss (Space Invader Chalice, zero tags) is DOCUMENTED as a
    drop, not silently lost — test_accepted_single_miss_documented.

INV-05 is NOT triggered: the full-catalog walk found zero auction signal (2 substring
false positives — a 'Fauchea' macroalgae + an 'RB' additive — documented in the YAML).
barrier_reef.yaml carries no auction_detection block; yaml_mirror_parity pins that.

Mirror-parity (CTK-115): the harness yaml_mirror_parity loads barrier_reef.yaml and
asserts CONFIG.category_filter == the YAML block byte-exact, the axis-set is exactly
{tag_allowlist}, and product_type_allowlist / title_denylist / tag_denylist are ABSENT
(the coral-minority tag_allowlist posture via CONFIG.expected_absent_axes) — any of
them landing later fails loudly.

Runnable as:
  python -m scrapers.tests.test_barrier_reef_parse

Fixture regen path: re-fetch barrierreefaquariums.com/products.json?limit=250 across
pages (Session-1 walk shape: 1,722 rows / 7 pages) and re-dump {"products": [...]}.
NOTE: re-pinning moves the kept count + the drift-watch counts as the live catalog
drifts — update EXPECTED_TOTAL/EXPECTED_KEPT + the anchor sets to match the snapshot,
and re-audit the tag census for any NEW coral tag (the allowlist's invisible-coral-out
cost; feedback_rotating_bucket_allowlist).
"""

from __future__ import annotations

import collections
import sys
from pathlib import Path

from scrapers.common.normalize import infer_category
from scrapers.tests.vendor_parse_harness import (
    VendorParseConfig,
    by_title as _by_title,
    check_html_hash_first_product_keys,
    check_yaml_mirror_parity,
    make_keep,
    make_normalize,
    run_main,
)


# Hand-mirror of scrapers/vendors/barrier_reef.yaml category_filter — kept byte-exact
# with the YAML; yaml_mirror_parity asserts the equality so a YAML amendment that
# isn't mirrored here fails loudly (CTK-115 drift class). The 10 coral category tags;
# NO product_type_allowlist / title_denylist / tag_denylist (coral-minority posture).
BARRIER_REEF_CATEGORY_FILTER = {
    "tag_allowlist": [
        "Coral WYSIWYG", "LPS", "SPS", "Zoa", "Soft Coral", "Mushroom",
        "Torch", "ORA Hard", "ORA Soft", "$10 Value",
    ],
}

CONFIG = VendorParseConfig(
    fixture_path=Path(__file__).parent / "fixtures" / "barrier_reef" / "products.sample.json",
    yaml_path=Path(__file__).parent.parent / "vendors" / "barrier_reef.yaml",
    base_url="https://barrierreefaquariums.com",
    image_strategy="mirror",
    originator_prefix=None,   # CTK-151 — null (no Barrier-Reef-attributed seed-list canonicals)
    auction_detection=None,   # CTK-151 — INV-05 not triggered; no auction_detection block
    category_filter=BARRIER_REEF_CATEGORY_FILTER,
    in_stock_only=False,
    expected_first_product_keys=[
        "body_html", "created_at", "handle", "id", "images", "options",
        "product_type", "published_at", "tags", "title", "updated_at",
        "variants", "vendor",
    ],
    html_hash_sentinel="c94c512f27be051326728462bfaf34b4b4cb3f2595a3eafbe44ba45a672aad70",
    expected_filter_keys=frozenset({"tag_allowlist"}),
    expected_absent_axes=frozenset({"product_type_allowlist", "title_denylist", "tag_denylist"}),
    expect_in_stock_only_absent=True,
    expect_auction_detection_none=True,
)

_keep = make_keep(CONFIG)
_normalize = make_normalize(CONFIG)


# Expected keep count on the LOCKED 2026-07-01 fixture (1,722 rows). The tag_allowlist
# keeps exactly the coral-tagged set; the rest of the full-LFS catalog drops by
# omission. Any allowlist regression (a coral tag dropped, or a non-coral tag added)
# moves this count.
EXPECTED_TOTAL = 1722
EXPECTED_KEPT = 779

# The 5 clams/anemones the vendor tagged 'Coral WYSIWYG' — they ride along and MUST
# classify NON-NULL (clam/anemone), never NULL (which would leak them into coral
# counts, INV-07 being a keeps-NULL denylist) and never the INV-07-hidden 'invert'.
CORAL_TAGGED_INVERTS = {
    "WYSIWYG - ORA Gold Maxima Clam": "clam",
    "WYSIWYG - ORA Blue Maxima Clam": "clam",
    "WYSIWYG - Ultra Rock Flower Anemone": "anemone",
    "WYSIWYG - Holy Grail Bubble Tip Anemone": "anemone",
    "WYSIWYG - Nexus Burst BTA 1/2 Split Coloration": "anemone",
}

# The accepted single invisible-coral-out miss — a real coral with ZERO tags. Logged
# so it is a KNOWN drop (re-walk recovery target), not silently lost.
ACCEPTED_SINGLE_MISS = "Space Invader Chalice"

# Coverage-floor: over the KEPT set, NULL-category ratio must stay under threshold.
COVERAGE_NULL_THRESHOLD_PCT = 10.0


try:
    import pytest

    @pytest.fixture(scope="module")
    def products():
        from scrapers.tests.vendor_parse_harness import load_fixture
        return load_fixture(CONFIG)
except ImportError:
    pass


# Test 1 (COMMON, harness): html_hash sentinel — sorted-keys-of-first-product SHA256
def test_html_hash_first_product_keys(products):
    check_html_hash_first_product_keys(products, CONFIG)


# Test 2: total kept = 779 (the coral-tagged set; the full-LFS non-coral catalog drops)
def test_total_kept_is_779(products):
    """Full-catalog keep count on the locked 1,722-row fixture: 779 kept. The
    tag_allowlist admits only coral-tagged rows; fish/equipment/apparel/swag drop by
    omission. A drop in this count means a coral tag was removed from the allowlist;
    a rise means a non-coral tag was added."""
    assert len(products) == EXPECTED_TOTAL, (
        f"fixture drifted: expected {EXPECTED_TOTAL} rows, got {len(products)}"
    )
    kept = sum(1 for p in products if _keep(p))
    assert kept == EXPECTED_KEPT, f"expected {EXPECTED_KEPT} kept, got {kept}"


# Test 3 (THE LOAD-BEARING REGRESSION): fish + equipment are excluded
def test_fish_and_equipment_excluded(products):
    """The coral-minority posture's load-bearing guard, INVERTING Cherry/Coral Stop's
    no-allowlist logic: a no-allowlist store would render /vendor as majority
    fish-and-pumps. The tag_allowlist drops them. Pin that real fish + equipment rows
    from the catalog do NOT survive, and that synthetic fish/equipment rows drop."""
    # Real catalog fish (tagged as fish, not coral) drop.
    for title in ["Scopas Tang", "Rainfordi Goby", "Captive Bred Tomato Clownfish"]:
        assert _keep(_by_title(products, title)) is False, f"fish leaked: {title!r}"
    # Real catalog equipment drops.
    for title in ["IceCap 2K Gyre Flow | Pump Only", "IceCap High Output UV Sterilizer"]:
        assert _keep(_by_title(products, title)) is False, f"equipment leaked: {title!r}"
    # Synthetic isolation: a coral-word-in-title fish/equipment row still drops (no coral tag).
    assert _keep({"title": "Yellow Tang", "product_type": "", "tags": ["Tang"]}) is False
    assert _keep({"title": "Coral Feeder Pump", "product_type": "", "tags": ["AI Pumps"]}) is False


# Test 4: coral-tagged rows are kept
def test_coral_tags_kept(products):
    """Each of the 10 allowlist tags keeps its rows. Synthetic one-tag rows isolate the
    axis — a coral carrying ONLY that tag survives (case-insensitive membership, so
    lowercase 'sps' matches 'SPS')."""
    for tag in ["Coral WYSIWYG", "LPS", "SPS", "Zoa", "Soft Coral", "Mushroom",
                "Torch", "ORA Hard", "ORA Soft", "$10 Value"]:
        assert _keep({"title": f"Test {tag} Coral", "product_type": "", "tags": [tag]}) is True, (
            f"allowlist tag failed to keep: {tag!r}"
        )
    # Case-insensitive: lowercase 'sps' (the real "Rainbow Montipora" row) survives.
    assert _keep({"title": "Rainbow Montipora", "product_type": "", "tags": ["sps"]}) is True


# Test 5: '$10 Value' budget corals with no other coral tag survive
def test_ten_dollar_value_corals_kept(products):
    """The '$10 Value' entry is a PRICE tag, added to the allowlist to rescue 11 budget
    corals it uniquely tags (Monti Digitata, Xenia, Paly, Anacropora, Stylocoeniella...).
    Pin that a real $10-Value-only coral survives and that all such rows are kept — a
    drop means the entry was removed (11 corals lost, invisible-coral-out)."""
    p = _by_title(products, "Orange Monti Digitata | Value Sized")
    assert _keep(p) is True, "a '$10 Value'-only coral was dropped (allowlist entry removed?)"
    # The real guard: this row's SOLE tag is '$10 Value', so keeping it proves the
    # entry rescues an otherwise-untagged coral (drop the entry -> this fails). A
    # whole-'$10 Value'-set all(_keep) assertion would be tautological — rows are
    # selected by carrying the tag, which is itself an allowlist entry, so _keep is a
    # guaranteed superset and can't fail independently (CTK-151 /code-review fold).
    assert set(p["tags"]) == {"$10 Value"}, "fixture drift: expected '$10 Value' as the sole tag"


# Test 6: the 5 vendor-coral-tagged inverts classify NON-NULL (clam/anemone), not NULL
def test_coral_tagged_inverts_classify_non_null(products):
    """CTK-151 Q2 first-ship spot-check. The 5 clams/anemones the vendor tagged
    'Coral WYSIWYG' ride along (kept) and MUST classify NON-NULL — clam/anemone via
    normalize._CATEGORY_PATTERNS — NOT NULL. A NULL classification leaks them into
    coral counts (INV-07 excludes explicit 'invert'/'equipment' but KEEPS NULLs).
    Pins the corals-only ruling's data integrity: they are carried, not hidden, and
    they resolve to a real category."""
    for title, expected_cat in CORAL_TAGGED_INVERTS.items():
        p = _by_title(products, title)
        assert _keep(p) is True, f"coral-tagged invert wrongly dropped: {title!r}"
        cat = infer_category(p)
        assert cat is not None, (
            f"coral-tagged invert classified NULL (leaks into coral counts): {title!r}"
        )
        assert cat == expected_cat, (
            f"coral-tagged invert mis-classified: {title!r} -> {cat!r}, expected {expected_cat!r}"
        )


# Test 7: fish 'SW Fish WYSIWYG' does NOT leak via the 'Coral WYSIWYG' entry
def test_fish_wysiwyg_not_leaked(products):
    """The allowlist entry is 'Coral WYSIWYG'; fish carry 'SW Fish WYSIWYG'. Tag
    membership is exact (case-insensitive equality, NOT substring), so 'sw fish wysiwyg'
    != 'coral wysiwyg' and fish WYSIWYG rows drop. Pin a real fish WYSIWYG row drops +
    the synthetic isolation (were membership substring, this would leak)."""
    fish_wysiwyg = [p for p in products if "sw fish wysiwyg" in {t.lower() for t in p.get("tags", [])}]
    assert fish_wysiwyg, "fixture drift: expected 'SW Fish WYSIWYG' fish rows"
    assert all(not _keep(p) for p in fish_wysiwyg), "a 'SW Fish WYSIWYG' fish leaked in"
    assert _keep({"title": "WYSIWYG - Purple Tang", "product_type": "", "tags": ["SW Fish WYSIWYG"]}) is False


# Test 8: the accepted single miss is documented as a drop (not silently lost)
def test_accepted_single_miss_documented(products):
    """The one accepted invisible-coral-out miss: 'Space Invader Chalice' carries ZERO
    tags, so the tag_allowlist drops it. This test DOCUMENTS the drop (the '' empty-tag
    bucket was rejected — it would drag in 5 non-corals to rescue this 1 coral). If the
    fixture no longer has this row, or it gains a coral tag, update the note — the miss
    is logged for drift-watch re-walk recovery, not hidden."""
    p = _by_title(products, ACCEPTED_SINGLE_MISS)
    assert p["tags"] == [], "fixture drift: the accepted-miss row is no longer zero-tag"
    assert _keep(p) is False, "the accepted-miss row is now kept — re-audit the note"


# Test 9: no auction null-out — INV-05 not triggered at the normalize layer
def test_normalize_no_auction_nulling(products):
    """barrier_reef.yaml carries no auction_detection (AUCTION_DETECTION=None), so coral
    normalizes with is_auction=False and keeps its real price. Pins INV-05-not-triggered
    at the _normalize_product layer (the walk found zero auction signal — 2 substring
    false positives only)."""
    p = next(p for p in products if _keep(p) and any(v.get("price") for v in p.get("variants", [])))
    norm = _normalize(p)
    assert norm["is_auction"] is False
    assert norm["current_price"] is not None, "non-auction coral price must not be nulled"


# Test 10: _normalize_product output shape — coral product
def test_normalize_output_shape(products):
    """_normalize_product on a kept coral — validates output dict shape per arch §1.4
    vendor_listings columns + absolute product_url (CTK-033 D1)."""
    p = _by_title(products, "Orange Monti Digitata | Value Sized")
    norm = _normalize(p)
    assert norm["raw_title"] == "Orange Monti Digitata | Value Sized"
    assert norm["product_url"].startswith("https://barrierreefaquariums.com/products/")
    assert norm["currency"] == "USD"


# Test 11: coverage floor — NULL-category ratio over the KEPT set under threshold
def test_category_coverage_floor(products):
    """CTK-151 coverage gate: over the KEPT set (production parser output), the
    NULL-category ratio must stay <= 10%. If it regresses, the missing genera/common-
    names must be added to normalize._CATEGORY_PATTERNS (fleet-general) BEFORE ship.
    Prints the NULL titles so a regression names the missing terms."""
    kept = [p for p in products if _keep(p)]
    null_titles = [p.get("title") for p in kept if infer_category(p) is None]
    ratio = len(null_titles) / len(kept) * 100
    assert ratio <= COVERAGE_NULL_THRESHOLD_PCT, (
        f"category coverage regressed: {ratio:.2f}% NULL > {COVERAGE_NULL_THRESHOLD_PCT}% "
        f"(NULL titles: {collections.Counter(null_titles)})"
    )


# Test 12 (COMMON, harness, MIRROR-PARITY CTK-115): CONFIG == barrier_reef.yaml
def test_yaml_mirror_parity():
    check_yaml_mirror_parity(CONFIG)


def main() -> int:
    return run_main(
        CONFIG,
        tests=[
            test_html_hash_first_product_keys,
            test_total_kept_is_779,
            test_fish_and_equipment_excluded,
            test_coral_tags_kept,
            test_ten_dollar_value_corals_kept,
            test_coral_tagged_inverts_classify_non_null,
            test_fish_wysiwyg_not_leaked,
            test_accepted_single_miss_documented,
            test_normalize_no_auction_nulling,
            test_normalize_output_shape,
            test_category_coverage_floor,
            test_yaml_mirror_parity,
        ],
        no_param={test_yaml_mirror_parity},
    )


if __name__ == "__main__":
    sys.exit(main())
