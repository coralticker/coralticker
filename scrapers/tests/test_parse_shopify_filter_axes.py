"""scrapers/tests/test_parse_shopify_filter_axes.py — CTK-096 D-4 cross-fleet
integration test for the lowercase-runtime tag_denylist mitigation + all-
vendor-YAML load smoke test.

Parse-only — no DB, no network. The lowercase-runtime mitigation lives in
`parse_shopify._should_keep` and is the cross-fleet bug class — by
definition it can drift on any of 11 vendors, not just the three with
new `title_denylist` entries in CTK-096. CTK-094 Session 5 fold #6
introduced the same regression-pin shape (multi-vendor filter-axis
interaction); this file extends it for CTK-096 D-2.

Asserts:
  1. _load_yaml accepts every vendor YAML in scrapers/vendors/ — no parse
     errors, no missing-field crashes. Catches a YAML-side typo or
     accidental shape drift before it lands in the cron tick.
  2. tag_denylist membership is case-insensitive in BOTH directions —
     YAML mixed-case + API lowercase = drop; YAML lowercase + API
     mixed-case = drop. Pins CTK-096 D-2 against future tag-shape
     regressions on any of the 11 vendors.

Runnable as:
  python -m scrapers.tests.test_parse_shopify_filter_axes
"""

from __future__ import annotations

import sys
import traceback

from scrapers.common.parse_shopify import _should_keep
from scrapers.common.run import _load_yaml


VENDOR_SLUGS = [
    "aquasd", "battlecorals", "jf", "pacific_east", "poto", "reef_chasers",
    "tidal_gardens", "tsa", "unique_corals", "vivid_aquariums", "wwc",
]


def test_load_all_11_vendor_yamls():
    """All 11 vendor YAMLs parse cleanly via the canonical _load_yaml entrypoint
    used by run.py at scrape-start. A YAML-side typo (bad indent, missing
    colon) would surface here rather than in the cron logs. The slug field
    isn't asserted equal to the filename — CTK-093 surfaced an underscore-vs-
    hyphen mismatch that's now codified DB-side; the YAML invariant here is
    just `parses to a dict carrying a slug key`."""
    for slug in VENDOR_SLUGS:
        cfg = _load_yaml(slug)
        assert isinstance(cfg, dict), f"{slug}.yaml did not parse to a dict"
        assert "slug" in cfg, f"{slug}.yaml missing 'slug' field"


# --- Lowercase-runtime mitigation, both directions ---
#
# The mitigation site is at parse_shopify._should_keep:
#   if tag_denylist and any(
#       t.lower() in {e.lower() for e in tag_denylist} for t in tags
#   ): return False
#
# Pre-CTK-096 the predicate was `t in tag_denylist` — case-sensitive — so a
# vendor returning 'triton' while the YAML carried 'Triton' (or vice versa)
# would silently miss. The mitigation closes both directions.

# Use a minimal filter dict shape so we don't depend on a specific vendor's
# allowlist. Empty product_type_allowlist = permissive (no PT gate).
def _mk_filter(tag_denylist: list[str]) -> dict:
    return {"product_type_allowlist": [], "tag_denylist": tag_denylist}


def _p(tags: list[str], product_type: str = "") -> dict:
    """Synthetic product carrying the test's tag-shape. Title doesn't matter
    for tag_denylist; PT empty so it doesn't gate."""
    return {"title": "x", "product_type": product_type, "tags": tags}


def test_yaml_mixed_case_api_lowercase_drops():
    """YAML carries `Triton` capital — API returns `triton` lowercase
    (real-world CTK-095 Axis 2 shape: UC catalog rotated in Triton supplements
    tagged lowercase). Mitigation must catch."""
    flt = _mk_filter(["Triton"])
    p = _p(tags=["triton"])
    assert _should_keep(p, flt) is False


def test_yaml_lowercase_api_mixed_case_drops():
    """YAML carries `dalua` lowercase — API returns `Dalua` mixed-case
    (the inverse drift direction). Mitigation must catch."""
    flt = _mk_filter(["dalua"])
    p = _p(tags=["Dalua"])
    assert _should_keep(p, flt) is False


def test_yaml_and_api_both_mixed_case_drops_no_regression():
    """Pre-CTK-096 same-case match continues to drop. Confirms the mitigation
    didn't accidentally narrow the drop predicate."""
    flt = _mk_filter(["Dalua"])
    p = _p(tags=["Dalua"])
    assert _should_keep(p, flt) is False


def test_yaml_and_api_both_lowercase_drops_no_regression():
    """Same-case lowercase match continues to drop."""
    flt = _mk_filter(["triton"])
    p = _p(tags=["triton"])
    assert _should_keep(p, flt) is False


def test_no_overlap_keeps():
    """Tag set entirely disjoint from denylist: row stays kept regardless
    of case shape on either side."""
    flt = _mk_filter(["Dalua", "triton"])
    p = _p(tags=["acropora", "Coral"])
    assert _should_keep(p, flt) is True


def test_empty_denylist_permissive():
    """Empty tag_denylist = no gate (existing 8 vendors with empty denylist
    stay byte-identical to pre-CTK-096 behavior)."""
    flt = _mk_filter([])
    p = _p(tags=["anything", "AnythingElse"])
    assert _should_keep(p, flt) is True


# --- title_denylist permissive when unset (no-regression for 8 vendors) ---

def test_title_denylist_unset_preserves_pre_ctk096_behavior():
    """A vendor YAML without a title_denylist key behaves identically to the
    pre-CTK-096 shape — permissive when unset. Pins the 8 non-CTK-096 vendors
    (PE / WWC / TSA / Reef Chasers / Vivid / POTO / AquaSD / Tidal Gardens)
    stay byte-identical."""
    flt = {
        "product_type_allowlist": ["CORAL"],
        "tag_denylist": ["goods"],
        # No title_denylist key at all.
    }
    # A row that pre-CTK-096 would pass — passes post-CTK-096 too.
    p = _p(tags=["acro"], product_type="CORAL")
    assert _should_keep(p, flt) is True
    # A row pre-CTK-096 would drop via tag_denylist — still drops.
    p_drop = _p(tags=["goods"], product_type="CORAL")
    assert _should_keep(p_drop, flt) is False


def main() -> int:
    tests = [
        test_load_all_11_vendor_yamls,
        test_yaml_mixed_case_api_lowercase_drops,
        test_yaml_lowercase_api_mixed_case_drops,
        test_yaml_and_api_both_mixed_case_drops_no_regression,
        test_yaml_and_api_both_lowercase_drops_no_regression,
        test_no_overlap_keeps,
        test_empty_denylist_permissive,
        test_title_denylist_unset_preserves_pre_ctk096_behavior,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL  {t.__name__}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
