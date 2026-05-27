"""scrapers/tests/test_parse_shopify_tag_allowlist.py — CTK-086 Session 2 Q-4
parse_shopify._should_keep tag_allowlist extension tests.

Parse-only — no DB, no network. Validates the new tag_allowlist axis added
to category_filter for vendors whose taxonomy lives in tags rather than
product_type (Reef Chasers shape — product_type='' universal, every coral
row tagged 'Coral'). Symmetric with product_type_allowlist; AND-semantics
when both axes are configured.

Runnable as:
  python -m scrapers.tests.test_parse_shopify_tag_allowlist
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

from scrapers.common.parse_shopify import _should_keep


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "parse_shopify_tag_allowlist" / "products.sample.json"

# Reef Chasers-shape filter: tag_allowlist primary (taxonomy in tags, not
# product_type) + tag_denylist secondary belt-and-suspenders. Mirrors the
# YAML shape locked at CTK-086 plan §Decisions Q-2 (Session 3 ships RC).
RC_SHAPE_FILTER = {
    "tag_allowlist": ["Coral"],
    "tag_denylist": ["Fish", "Tang", "shipping"],
}


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


# Test 1: tag_allowlist hit — tag intersection non-empty = keep
def test_tag_allowlist_keeps_when_tag_intersects(products):
    """Synthetic Coral Frag has 'Coral' in tags; RC_SHAPE_FILTER tag_allowlist
    is ['Coral']. Intersection non-empty → keep. Validates the Q-4 primary
    semantic from CTK-086 plan §Decisions Q-4."""
    p = _by_title(products, "Synthetic Coral Frag — tag_allowlist hit")
    assert _should_keep(p, RC_SHAPE_FILTER) is True


# Test 2: tag_allowlist miss — no tag intersection = reject
def test_tag_allowlist_rejects_when_no_tag_intersects(products):
    """Synthetic Fish has tags ['Fish', 'Tang']; RC_SHAPE_FILTER tag_allowlist
    is ['Coral']. Intersection empty → short-circuit reject (Q-4 mirror of
    product_type_allowlist miss behavior)."""
    p = _by_title(products, "Synthetic Fish — tag_allowlist miss")
    assert _should_keep(p, RC_SHAPE_FILTER) is False


# Coverage extension: tag_denylist short-circuits after tag_allowlist hit
def test_tag_allowlist_hit_still_rejected_by_tag_denylist(products):
    """Synthetic Coral with denylist tag has tags ['Coral', 'shipping']. The
    'Coral' tag passes tag_allowlist; the 'shipping' tag fails tag_denylist.
    Confirms tag_denylist short-circuit fires AFTER tag_allowlist hit (AND-
    semantics across all three axes per the docstring contract)."""
    p = _by_title(products, "Synthetic Coral with denylist tag — denylist short-circuit")
    assert _should_keep(p, RC_SHAPE_FILTER) is False


# Coverage extension: tag_allowlist permissive when unset (single-axis configs preserved)
def test_tag_allowlist_unset_preserves_pre_q4_behavior(products):
    """category_filter without a tag_allowlist key behaves identically to the
    pre-Q-4 shape for product_type_allowlist + tag_denylist consumers
    (PE/WWC/TSA/JF/BC/UC). Permissive when unset is the no-regression
    contract."""
    legacy_filter = {
        "product_type_allowlist": [""],  # Reef Chasers' product_type='' would still pass under empty-PT allowlist (BC/UC shape)
        "tag_denylist": ["Fish", "Tang"],
    }
    p = _by_title(products, "Synthetic Coral Frag — tag_allowlist hit")
    # Pre-Q-4 path: product_type='' is in allowlist [''] → pass; no Fish/Tang tags → pass.
    assert _should_keep(p, legacy_filter) is True


def main() -> int:
    products = _load_fixture()
    tests = [
        test_tag_allowlist_keeps_when_tag_intersects,
        test_tag_allowlist_rejects_when_no_tag_intersects,
        test_tag_allowlist_hit_still_rejected_by_tag_denylist,
        test_tag_allowlist_unset_preserves_pre_q4_behavior,
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
