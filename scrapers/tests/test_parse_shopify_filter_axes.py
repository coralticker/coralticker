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
  1. tag_denylist membership is case-insensitive in BOTH directions —
     YAML mixed-case + API lowercase = drop; YAML lowercase + API
     mixed-case = drop. Pins CTK-096 D-2 against future tag-shape
     regressions on any of the 11 vendors.
  2. title_denylist_prefix (CTK-119) is ANCHORED + case-insensitive +
     permissive-when-unset — pins the anchor semantics (word-final "ws"
     collision class survives) and the 10 non-WWC vendors byte-identical.

The all-vendor-YAML load smoke test that used to live here (CTK-096 D-4
assert 1, slug-list enumeration) moved to test_run_load_yaml.py's
test_all_live_vendor_yamls_load_clean (CTK-102 /code-review F7) — the glob
sweep there is the canonical fleet-enumeration pin and absorbed the
slug-key assertion.

Runnable as:
  python -m scrapers.tests.test_parse_shopify_filter_axes
"""

from __future__ import annotations

import sys
import traceback

from scrapers.common.parse_shopify import _should_keep


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

# --- tag_allowlist D-2 symmetric extension (close-fold F2 2026-05-31) ---
#
# Mirrors the tag_denylist mitigation. RC's load-bearing `tag_allowlist:
# ['Coral']` is the sole coral signal for ~143 corals; an API drift to
# lowercase 'coral' would empty the catalog without this symmetric mitigation.

def _mk_allowlist_filter(tag_allowlist: list[str]) -> dict:
    """Like _mk_filter but exercises tag_allowlist instead of tag_denylist.
    Empty product_type_allowlist = permissive (no PT gate)."""
    return {"product_type_allowlist": [], "tag_allowlist": tag_allowlist}


def test_tag_allowlist_yaml_mixed_case_api_lowercase_keeps():
    """YAML carries `Coral` capital — API returns `coral` lowercase (the RC
    load-bearing drift case). Symmetric mitigation must keep (allowlist hit)."""
    flt = _mk_allowlist_filter(["Coral"])
    p = _p(tags=["coral"])
    assert _should_keep(p, flt) is True


def test_tag_allowlist_yaml_lowercase_api_mixed_case_keeps():
    """YAML carries `coral` lowercase — API returns `Coral` mixed-case (inverse
    drift). Symmetric mitigation must keep."""
    flt = _mk_allowlist_filter(["coral"])
    p = _p(tags=["Coral"])
    assert _should_keep(p, flt) is True


def test_tag_allowlist_yaml_and_api_both_mixed_case_keeps_no_regression():
    """Same-case match continues to keep — pre-fold behavior preserved."""
    flt = _mk_allowlist_filter(["Coral"])
    p = _p(tags=["Coral"])
    assert _should_keep(p, flt) is True


def test_tag_allowlist_yaml_and_api_both_lowercase_keeps_no_regression():
    """Same-case lowercase match continues to keep."""
    flt = _mk_allowlist_filter(["coral"])
    p = _p(tags=["coral"])
    assert _should_keep(p, flt) is True


def test_tag_allowlist_no_overlap_drops():
    """Tag set entirely disjoint from allowlist: row drops regardless of case
    shape on either side. Pins the gate fires when it should."""
    flt = _mk_allowlist_filter(["Coral"])
    p = _p(tags=["Fish", "Tang"])
    assert _should_keep(p, flt) is False


def test_tag_allowlist_empty_permissive():
    """Empty tag_allowlist = no gate (existing 8 vendors with empty allowlist
    stay byte-identical to pre-fold behavior)."""
    flt = _mk_allowlist_filter([])
    p = _p(tags=["anything", "AnythingElse"])
    assert _should_keep(p, flt) is True


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


# --- title_denylist_prefix (CTK-119) — anchored axis, fleet semantics ---
#
# Anchored variant of title_denylist: case-insensitive startswith, lowercase-
# runtime both sides per the CTK-096 convention. Shipped for WWC's `WS - `
# wholesale/live-sale channel prefix; permissive when unset so the 10 other
# vendors stay byte-identical.

def _mk_prefix_filter(title_denylist_prefix: list[str]) -> dict:
    """Like _mk_filter but exercises title_denylist_prefix. Empty
    product_type_allowlist = permissive (no PT gate)."""
    return {"product_type_allowlist": [], "title_denylist_prefix": title_denylist_prefix}


def _p_titled(title: str) -> dict:
    """Synthetic product where the TITLE is the test surface (inverse of _p,
    where tags are)."""
    return {"title": title, "product_type": "", "tags": []}


def test_title_denylist_prefix_unset_preserves_behavior():
    """A filter without the title_denylist_prefix key is permissive — even for
    a title-initial 'WS - ' row. Pins the 10 non-WWC vendors byte-identical
    post-CTK-119 (the sharpest possible pin: the exact pattern that WOULD
    drop on WWC passes when the axis is unset)."""
    flt = {"product_type_allowlist": [], "tag_denylist": ["goods"]}
    p = _p_titled("WS - would drop on WWC, passes here")
    assert _should_keep(p, flt) is True


def test_title_denylist_prefix_empty_permissive():
    """Empty list = no gate, same shape as the other axes' empty semantics."""
    flt = _mk_prefix_filter([])
    p = _p_titled("WS - anything")
    assert _should_keep(p, flt) is True


def test_title_denylist_prefix_drops_title_initial():
    """Title-initial match drops."""
    flt = _mk_prefix_filter(["WS - "])
    assert _should_keep(_p_titled("WS - Acro Pack"), flt) is False


def test_title_denylist_prefix_case_insensitive_both_directions():
    """YAML mixed-case + API lowercase = drop, and the inverse — same
    lowercase-runtime contract as tag_denylist (CTK-096 D-2)."""
    assert _should_keep(_p_titled("ws - lowercase api"), _mk_prefix_filter(["WS - "])) is False
    assert _should_keep(_p_titled("WS - Mixed Case Api"), _mk_prefix_filter(["ws - "])) is False


def test_title_denylist_prefix_anchored_not_substring():
    """The load-bearing semantic pin (CTK-119 review-fold #1): the axis is
    ANCHORED. Word-final "ws" before " - " ('Rainbows - ...', 'Jaws - ...')
    and mid-title occurrences survive. A regression that reimplements the
    axis as substring matching breaks this test."""
    flt = _mk_prefix_filter(["WS - "])
    for title in ("Rainbows - WYSIWYG Frag", "Jaws - 2 inch", "Mid Title WS - embedded"):
        assert _should_keep(_p_titled(title), flt) is True, (
            f"{title!r} dropped — prefix axis lost its anchor"
        )


# --- sku_denylist_suffix (CTK-181) — variant-SKU anchored-suffix axis ---
#
# The only structural discriminator for cross-vendor TEST-DATA rows that carry
# REAL coral titles (TSA '…-twcheap', famous names at $1–$15 → title/tag/PT
# axes all blind). Case-SENSITIVE endswith, checked across ALL variants (not
# just the first SKU _normalize_product picks). Permissive when unset so every
# vendor without the axis stays byte-identical.

def _mk_sku_filter(sku_denylist_suffix: list[str]) -> dict:
    """Like _mk_filter but exercises sku_denylist_suffix. Empty
    product_type_allowlist = permissive (no PT gate)."""
    return {"product_type_allowlist": [], "sku_denylist_suffix": sku_denylist_suffix}


def _p_skus(skus: list, title: str = "Rainbow Acan") -> dict:
    """Synthetic product whose VARIANTS carry the test SKUs. Real coral title +
    empty PT/tags so ONLY the SKU axis can gate it — mirrors the twcheap reality
    (title/tag/PT all blind on a famous-name $15 test row)."""
    return {
        "title": title,
        "product_type": "",
        "tags": [],
        "variants": [{"sku": s} for s in skus],
    }


def test_sku_denylist_suffix_unset_preserves_behavior():
    """No sku_denylist_suffix key = permissive — the sharpest pin: a '-twcheap'
    SKU row that WOULD drop on TSA passes when the axis is unset. Pins every
    vendor without the axis byte-identical."""
    flt = {"product_type_allowlist": [], "tag_denylist": ["goods"]}
    assert _should_keep(_p_skus(["AWXKrissKrossChalice-twcheap"]), flt) is True


def test_sku_denylist_suffix_empty_permissive():
    """Empty list = no gate, same shape as the other axes' empty semantics."""
    assert _should_keep(_p_skus(["x-twcheap"]), _mk_sku_filter([])) is True


def test_sku_denylist_suffix_drops_on_suffix_match():
    """Title-blind drop: real coral title, the only signal is the SKU suffix.
    The core behavior — deletes the gate and this fails."""
    flt = _mk_sku_filter(["-twcheap"])
    assert _should_keep(_p_skus(["AWXKrissKrossChalice-twcheap"]), flt) is False


def test_sku_denylist_suffix_checks_all_variants_not_just_first():
    """LOAD-BEARING (fails if the gate checked only the first SKU the way
    _normalize_product does): the suffix on a NON-first variant still drops.
    A twcheap row can carry the marker on any variant, not just variant[0]."""
    flt = _mk_sku_filter(["-twcheap"])
    assert _should_keep(_p_skus(["CLEAN-001", None, "AWX-twcheap"]), flt) is False


def test_sku_denylist_suffix_anchored_endswith_not_substring():
    """Anchored: a SKU that merely CONTAINS '-twcheap' mid-string survives —
    only a true suffix drops. A substring reimplementation breaks this."""
    flt = _mk_sku_filter(["-twcheap"])
    assert _should_keep(_p_skus(["x-twcheap-real-frag"]), flt) is True


def test_sku_denylist_suffix_case_sensitive():
    """SKUs are identifiers, matched as EMITTED — uppercase '-TWCHEAP' does NOT
    match the lowercase entry (unlike the lowercase-runtime title/tag axes).
    Pins the deliberate case-sensitivity decision; flip the gate to .lower()
    and this fails."""
    flt = _mk_sku_filter(["-twcheap"])
    assert _should_keep(_p_skus(["ACRO-TWCHEAP"]), flt) is True


def test_sku_denylist_suffix_real_coral_sku_survives():
    """FP guard: a real coral SKU not ending in the suffix is kept."""
    flt = _mk_sku_filter(["-twcheap"])
    assert _should_keep(_p_skus(["WWC-DRAGON-SOUL-7234"]), flt) is True


def test_sku_denylist_suffix_none_and_missing_sku_safe():
    """None / missing / empty variants don't crash the gate and don't false-drop
    — the `(v.get('sku') or '')` guard + `(variants or [])` guard hold."""
    flt = _mk_sku_filter(["-twcheap"])
    assert _should_keep(_p_skus([None, None]), flt) is True
    assert _should_keep({"title": "x", "product_type": "", "tags": [], "variants": []}, flt) is True
    assert _should_keep({"title": "x", "product_type": "", "tags": []}, flt) is True  # no variants key


def test_sku_denylist_suffix_multi_suffix_tuple():
    """Multiple suffixes: any match drops (str.endswith takes the tuple); a SKU
    matching none survives."""
    flt = _mk_sku_filter(["-twcheap", "-testsku"])
    assert _should_keep(_p_skus(["x-testsku"]), flt) is False
    assert _should_keep(_p_skus(["x-clean"]), flt) is True


def main() -> int:
    tests = [
        test_yaml_mixed_case_api_lowercase_drops,
        test_yaml_lowercase_api_mixed_case_drops,
        test_yaml_and_api_both_mixed_case_drops_no_regression,
        test_yaml_and_api_both_lowercase_drops_no_regression,
        test_no_overlap_keeps,
        test_empty_denylist_permissive,
        test_tag_allowlist_yaml_mixed_case_api_lowercase_keeps,
        test_tag_allowlist_yaml_lowercase_api_mixed_case_keeps,
        test_tag_allowlist_yaml_and_api_both_mixed_case_keeps_no_regression,
        test_tag_allowlist_yaml_and_api_both_lowercase_keeps_no_regression,
        test_tag_allowlist_no_overlap_drops,
        test_tag_allowlist_empty_permissive,
        test_title_denylist_unset_preserves_pre_ctk096_behavior,
        test_title_denylist_prefix_unset_preserves_behavior,
        test_title_denylist_prefix_empty_permissive,
        test_title_denylist_prefix_drops_title_initial,
        test_title_denylist_prefix_case_insensitive_both_directions,
        test_title_denylist_prefix_anchored_not_substring,
        test_sku_denylist_suffix_unset_preserves_behavior,
        test_sku_denylist_suffix_empty_permissive,
        test_sku_denylist_suffix_drops_on_suffix_match,
        test_sku_denylist_suffix_checks_all_variants_not_just_first,
        test_sku_denylist_suffix_anchored_endswith_not_substring,
        test_sku_denylist_suffix_case_sensitive,
        test_sku_denylist_suffix_real_coral_sku_survives,
        test_sku_denylist_suffix_none_and_missing_sku_safe,
        test_sku_denylist_suffix_multi_suffix_tuple,
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
