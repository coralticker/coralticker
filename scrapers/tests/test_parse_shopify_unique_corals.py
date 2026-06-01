"""scrapers/tests/test_parse_shopify_unique_corals.py — CTK-096 title_denylist
axis, Unique Corals coverage.

Parse-only — no DB, no network. Pins drop-vs-keep behavior per UC YAML
title_denylist entry against synthetic products matching the 2026-05-31
empirical leak surface (equipment-brand class: DaStaCo / SeeClear /
MagSleeve / ARID / Panta Rhei / Illumagic / Dalua) + FP-discipline
controls on the trailing-space `ARID ` substring (catches the brand but
not hypothetical `MARID`/`PARIDA` neighbors).

UC has tag_denylist overlap with title_denylist (Dalua / illumagic /
Panta Rhei) — by design per CTK-096 D-3 belt-and-suspenders against
tag-shape drift. The PT='Drygoods' rows in UC's catalog are caught by
allowlist exclusion regardless; title_denylist closes the residual
PT='' + new-brand-tag class (DaStaCo Replacement Bottom Sensor on
2026-05-31 walk).

Runnable as:
  python -m scrapers.tests.test_parse_shopify_unique_corals
"""

from __future__ import annotations

import sys
import traceback

from scrapers.common.parse_shopify import _should_keep


# UC YAML shape at CTK-096 ship: PT allowlist permissive on empty bucket +
# CORAL + Coral. tag_denylist 11 entries. title_denylist 7 walk-grounded
# entries per CTK-096 D-1 / D-3.
UC_FILTER = {
    "product_type_allowlist": ["", "CORAL", "Coral"],
    "tag_denylist": [
        "Dalua", "goods", "illumagic", "maintenance", "openbox", "Other DG",
        "Panta Rhei", "PNS", "shipping", "triton", "used",
    ],
    "title_denylist": [
        "ARID ",
        "Dalua",
        "DaStaCo",
        "Illumagic",
        "MagSleeve",
        "Panta Rhei",
        "SeeClear",
    ],
}


def _p(title: str, product_type: str = "", tags=None) -> dict:
    return {"title": title, "product_type": product_type, "tags": tags or []}


# --- Drop: per-entry empirical class pin ---

def test_uc_drops_dastaco_pt_empty():
    """The single empirical 2026-05-31 leak: DaStaCo Replacement Bottom Sensor
    with PT='' + tags=['DaStaCo']. 'DaStaCo' NOT in tag_denylist → pre-CTK-096
    this passed every axis. title_denylist catches via the brand substring."""
    p = _p("DaStaCo Replacement Bottom Sensor",
           product_type="", tags=["DaStaCo"])
    assert _should_keep(p, UC_FILTER) is False


def test_uc_drops_dastaco_pt_drygoods_redundant():
    """6 DaStaCo sibling rows with PT='Drygoods' are caught by allowlist
    exclusion today; title_denylist provides redundant defense if PT shape
    drifts. Synthetic test: with PT='' (the drift case), title catches."""
    for title in [
        "DaStaCo INTEGRA Controller",
        "DaStaCo CO2 Regulator",
        "Peristaltic Tubing for DaStaCo2 Calcium Reactor",
    ]:
        assert _should_keep(_p(title, product_type=""), UC_FILTER) is False, title


def test_uc_drops_seeclear_magsleeve():
    """SeeClear / MagSleeve class. Real walk-rows carry tags=['goods', ...]
    so `goods` tag_denylist catches today; title_denylist redundant. Test
    with PT='' + empty tags (the drift case) to pin title-only catch."""
    for title in [
        "SeeClear Outside Algae Magnet Sleeve MagSleeve (XXL)",
        "See Clear Inside Algae Magnet Sleeve MagSleeve (XL)",
    ]:
        assert _should_keep(_p(title, product_type="", tags=[]), UC_FILTER) is False, title


def test_uc_drops_arid_brand():
    """ARID equipment brand. Trailing-space `ARID ` substring catches the
    brand name even when surrounded by other text."""
    for title in [
        "ARID C36 Quick Disconnect Set",
        "ARID N24 Light Sleeve Assembly",
        "Power Cord Replacement - ARID Reactors",
    ]:
        assert _should_keep(_p(title, product_type="", tags=[]), UC_FILTER) is False, title


def test_uc_drops_panta_rhei_illumagic_dalua():
    """Equipment brands also already caught by tag_denylist on most rows;
    title_denylist redundant defense against tag-shape drift."""
    for title in [
        "Panta Rhei ECM 42 Pro Power Supply",
        "Illumagic Light Shade (For x4)",
        "Dalua Great White DC Plus Protein Skimmer GW-22 up to 580 gallons",
    ]:
        assert _should_keep(_p(title, product_type="", tags=[]), UC_FILTER) is False, title


# --- Keep: FP-discipline controls + baseline coral ---

def test_uc_keeps_arida_suffix_fp_control():
    """Trailing-space `ARID ` substring discipline pins SUFFIX collisions only.
    A hypothetical coral titled `Aridana Cyclamen` (substring `arid` followed
    by `a`, not space) must NOT false-fire — trailing-space protection works
    for suffix-extension words (PARIDA / Aridana / Aridoxa-class — all carry
    `arid` then a non-space char).

    Asymmetry observation (CTK-096 close-fold F14 + sweep S1 correction
    2026-06-01): trailing-space does NOT protect against PREFIX collisions —
    `Marid Smith` lowercase contains `arid ` as substring (position 1, with
    the original space after `marid` matching the entry's trailing space). Also
    does NOT protect END-of-string occurrences — `arid ` requires a trailing
    char to match, so a title like `Replacement Cord ARID` (vendor title-trim)
    would slip through. UC catalog 2026-05-31 walk-confirm contains no `marid `
    / `narid `-class coral titles AND no end-of-string ARID titles, so both
    asymmetries are theoretical FP/FN risk only; documented for future
    tag-shape drift watch."""
    p = _p("Aridana Cyclamen Echinata", product_type="CORAL", tags=[])
    assert _should_keep(p, UC_FILTER) is True


def test_uc_keeps_regular_coral():
    """Sanity: a normal UC coral row stays kept."""
    p = _p("UC Strawberry Shortcake OG", product_type="CORAL", tags=[])
    assert _should_keep(p, UC_FILTER) is True


def test_uc_keeps_empty_pt_real_coral():
    """Empty-PT bucket still passes when title is clean — UC signature
    WYSIWYG frags + cross-vendor TSA/WWC pieces stay in the catalog."""
    p = _p("TSA Twisted Sister", product_type="", tags=[])
    assert _should_keep(p, UC_FILTER) is True


def main() -> int:
    tests = [
        test_uc_drops_dastaco_pt_empty,
        test_uc_drops_dastaco_pt_drygoods_redundant,
        test_uc_drops_seeclear_magsleeve,
        test_uc_drops_arid_brand,
        test_uc_drops_panta_rhei_illumagic_dalua,
        test_uc_keeps_arida_suffix_fp_control,
        test_uc_keeps_regular_coral,
        test_uc_keeps_empty_pt_real_coral,
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
