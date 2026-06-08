"""scrapers/tests/test_ctk117_fish_detector.py — CTK-117 Arm 1 unit coverage
for the fish-leak detector's boundary-anchored term matcher.

Pure string-transform tests — no DB, no network. Pins the load-bearing
regression anchor (the id=38474-class catch the ad-hoc D-5 query made) plus
the widened genus coverage and the boundary correctness that the production
normalize.py:40 alternation-boundary bug lacks.

Runnable as:
  python -m scrapers.tests.test_ctk117_fish_detector

Coverage:
  test_flags_clownfish_38474_class      regression anchor — id=38474 title flags
  test_flags_widened_genus_nouns        anthias/puffer/butterfly/foxface/basslet
  test_flags_existing_prod_terms        fish/wrasse/tang/goby/clownfish/blenny
  test_boundary_no_substring_falsefire  `tang` must NOT fire on "Tangerine"
  test_clean_coral_title_no_flag        a plain coral title returns []
  test_empty_and_none_safe              "" / None return []
"""

from __future__ import annotations

import sys

from scrapers.tools.ctk117_fish_leak_detector import detect_fish_terms


def test_flags_clownfish_38474_class():
    """Regression anchor — id=38474 "Clownfish & Anemone Aquarium Kit" is the
    live stuck-residual the CTK-104 D-5 raw_title backstop caught (now OOS, so
    pinned here as a durable string-level anchor rather than a live DB row).
    The detector MUST flag it on `clownfish`."""
    terms = detect_fish_terms("Clownfish & Anemone Aquarium Kit")
    assert "clownfish" in terms, (
        f"id=38474-class title must flag on 'clownfish'; got {terms}"
    )


def test_flags_widened_genus_nouns():
    """CTK-117 widening — the TSA genus noun-phrases that escaped category
    inference (the CTK-104 named leaks: Borbonius Anthias / Valentini Puffer /
    Yellow Longnose Butterfly / Magnificent Foxface / Harlequin Basslet)."""
    cases = {
        "Borbonius Anthias": "anthias",
        "Valentini Puffer": "puffer",
        "Yellow Longnose Butterfly": "butterfly",
        "Magnificent Foxface": "foxface",
        "Harlequin Basslet": "basslet",
    }
    for title, term in cases.items():
        terms = detect_fish_terms(title)
        assert term in terms, f"{title!r} must flag on {term!r}; got {terms}"


def test_flags_existing_prod_terms():
    """The existing production fish terms still flag — and middle-of-alternation
    terms (wrasse / tang / goby / clownfish) now carry boundaries that the
    buggy production pattern only gave to `fish`/`blenny`."""
    cases = {
        "Yellow Tang": "tang",
        "Melanurus Wrasse": "wrasse",
        "Yellow Watchman Goby": "goby",
        "Tailspot Blenny": "blenny",
        "WYSIWYG Fish Pack": "fish",
    }
    for title, term in cases.items():
        terms = detect_fish_terms(title)
        assert term in terms, f"{title!r} must flag on {term!r}; got {terms}"


def test_boundary_no_substring_falsefire():
    """Boundary correctness — the fix the probe carries over the production
    pattern. `tang` is a bare alternative in normalize.py:40 (substring-matches),
    so it would false-fire on "Tangerine"/"Tango"/"Tangelo" coral lineages. The
    grouped `\\b(?:...)\\b` detector must NOT flag these as fish. (The detector
    tunes aggressive on real whole-word collisions like "Butterfly Effect" — that
    is intended Section-2 noise — but a substring false-fire is a regression.)"""
    for title in ("Tangerine Dream Zoanthid", "Tango Mango Palythoa",
                  "Goby-Free Acropora Tangelo"):
        terms = detect_fish_terms(title)
        # "Goby-Free ..." legitimately contains the whole word "goby" — assert
        # only that the substring-class term `tang` never fires inside Tangerine/
        # Tango/Tangelo.
        assert "tang" not in terms, (
            f"{title!r} substring-fired `tang` (boundary regression); got {terms}"
        )


def test_clean_coral_title_no_flag():
    """A plain coral title with no fish noun returns []."""
    for title in ("WWC Bizarro Acropora", "Rainbow Bounce Mushroom",
                  "JF Jack-O-Lantern Leptoseris"):
        assert detect_fish_terms(title) == [], (
            f"clean coral title {title!r} should not flag; got {detect_fish_terms(title)}"
        )


def test_empty_and_none_safe():
    """Empty / None raw_title return [] without raising."""
    assert detect_fish_terms("") == []
    assert detect_fish_terms(None) == []  # type: ignore[arg-type]


TESTS = [
    test_flags_clownfish_38474_class,
    test_flags_widened_genus_nouns,
    test_flags_existing_prod_terms,
    test_boundary_no_substring_falsefire,
    test_clean_coral_title_no_flag,
    test_empty_and_none_safe,
]


def main() -> int:
    passed = 0
    failed = 0
    for fn in TESTS:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL  {fn.__name__}: {e}")
            failed += 1
        except Exception as e:  # noqa: BLE001
            print(f"  ERROR {fn.__name__}: {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed (total {len(TESTS)})")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
