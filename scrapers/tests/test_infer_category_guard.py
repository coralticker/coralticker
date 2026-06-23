"""scrapers/tests/test_infer_category_guard.py — CTK-189 reverse-precision
guard on normalize.infer_category.

Pure unit — no DB, no network, no fixtures. Calls infer_category directly with
synthetic product dicts so the guard is exercised in isolation across vendors.

The guard reroutes a coral-tagged NON-coral to 'equipment' when the winning
category pattern is a coral category AND the TITLE carries a non-coral marker
(pellet / sticker / kit / probe / clipper / cartridge / earrings / "coral
food"). The reroute is what the CTK-186 step-2 feed exclusion (category IS
DISTINCT FROM 'equipment') consumes to drop the row from /new + /search +
/vendor.

Exercise-the-guarantee (feedback_review_results_test_exercises_guarantee): the
reroute tests below FAIL if the guard code is deleted — without it,
"Marine Anemone Pellets" infers 'anemone', not 'equipment'. The FP tests pin
that the guard does NOT over-reach onto real corals.
"""

from __future__ import annotations

from scrapers.common.normalize import infer_category


def _p(title: str, product_type: str = "", tags=None) -> dict:
    """Minimal product dict in the shape infer_category reads."""
    return {"title": title, "product_type": product_type, "tags": tags or []}


# ─── Reroute: each marker flips a coral-tagged non-coral to 'equipment' ───────
# These are the load-bearing tests — each fails if the guard is removed.

def test_pellet_reroutes_anemone_food_to_equipment():
    # "Marine Anemone Pellets" hits \banemone\b (coral) but is invert/fish food.
    assert infer_category(_p("Marine Anemone Pellets - 4mm - Vitalis")) == "equipment"


def test_pellet_reroutes_lps_benepellet_to_equipment():
    assert infer_category(_p("Benepets LPS Benepellet Small 1.7mm - 1.3oz")) == "equipment"


def test_clipper_reroutes_sps_tool_to_equipment():
    assert infer_category(_p("Rio Precision SPS Coral Clipper")) == "equipment"


def test_earrings_reroutes_zoa_merch_to_equipment():
    assert infer_category(_p("Recycled Roots Zoa Earrings")) == "equipment"


def test_sticker_reroutes_favites_merch_to_equipment():
    # "Bejeweled Favites Sticker" hits \bfavites\b (lps) — the part-(a) leak 17140.
    assert infer_category(_p("WWC Bejeweled Favites Sticker")) == "equipment"


def test_probe_kit_reroutes_sps_paren_to_equipment():
    # "Salinity Probe Stability Kit (SPS)" hits \bsps\b — the part-(a) leak 39192.
    assert infer_category(_p("Salinity Probe Stability Kit (SPS) - VCA")) == "equipment"


def test_coral_food_phrase_reroutes_lps_to_equipment():
    # The part-(a) leak 38866 — double-hits 'pellet' AND 'coral food'.
    assert infer_category(_p("Ultra LPS Grow & Color Medium Pellet Coral Food - Fauna Marin")) == "equipment"


def test_cartridge_reroutes_coral_word_to_equipment():
    assert infer_category(_p("LPS Reactor Media Cartridge")) == "equipment"


# ─── FP guard: real corals are NOT rerouted ──────────────────────────────────

def test_clean_coral_no_marker_untouched():
    # No marker → guard does not fire; normal inference stands.
    assert infer_category(_p("WWC Pikachu Acropora", product_type="Acropora")) == "sps"
    assert infer_category(_p("JF Bowerbanki", tags=["lps"])) == "lps"


def test_bare_food_does_not_flip_real_coral():
    # Bare 'food' was DROPPED from the marker set precisely because Battle
    # Corals' whimsical names false-matched it. These stay coral.
    assert infer_category(_p("Fairy Food", product_type="Acropora sp.")) == "sps"
    assert infer_category(
        _p('"looks like the cool bruise I got When I cat bit my hand trying to steal my food"',
           product_type="Acropora")
    ) == "sps"


def test_marker_in_tags_only_does_not_flip():
    # Guard is TITLE-scoped — a marker in tags (not title) must not reroute a
    # real coral. "kit" in tags, clean coral title → stays coral.
    assert infer_category(_p("WWC Holy Grail Torch", tags=["kit", "lps"])) == "lps"


def test_marker_on_noncoral_match_is_noop():
    # A genuine equipment item with a marker is already 'equipment' via its own
    # pattern — guard path isn't taken, result is unchanged.
    assert infer_category(_p("Return Pump Cartridge")) == "equipment"
    # A non-coral with a marker but no coral word → no coral pattern wins, guard
    # does not fire; falls through to None (not forced to equipment).
    assert infer_category(_p("Vendor Logo Sticker")) is None


def test_substring_marker_does_not_false_fire():
    # Word-boundary discipline: 'kits' matches (plural) but a coral name that
    # merely CONTAINS the letters must not. No standalone marker word here.
    assert infer_category(_p("Skittles Acropora", product_type="Acropora")) == "sps"
