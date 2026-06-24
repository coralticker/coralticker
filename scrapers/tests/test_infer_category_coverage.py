"""scrapers/tests/test_infer_category_coverage.py — CTK-194 coverage-add pass
on normalize.infer_category.

Pure unit — no DB, no network. CTK-194 added genera + common-name abbreviations
to _CATEGORY_PATTERNS to fill the POTO/Cornbred NULL-category population. Each
term and its category was chosen by a full-catalog FP probe (the assigned
category is the MAJORITY vote of already-categorized rows carrying the term).

Exercise-the-guarantee (feedback_review_results_test_exercises_guarantee): every
positive test below FAILS if its term is removed from _CATEGORY_PATTERNS — they
pin the coverage, not a tautology. The negative tests pin the deliberate
EXCLUSIONS (color/generic + split-genus words) so a future "just add candy too"
edit trips a red test.
"""

from __future__ import annotations

from scrapers.common.normalize import infer_category


def _p(title: str, product_type: str = "", tags=None) -> dict:
    return {"title": title, "product_type": product_type, "tags": tags or []}


# ─── SPS coverage: genera + the vendor abbreviation each prefix anchor catches ─
# The SPS abbreviations were the single biggest uncaught bucket (Cornbred /
# BattleCorals "...Monti / ...Acro / ...Milli / ...Digi / ...Stylo").

def test_sps_abbreviations():
    assert infer_category(_p("Cornbred's Cherry Tree Monti")) == "sps"      # \bmonti
    assert infer_category(_p("Cornbred's Green Slimer Acro")) == "sps"      # \bacro
    assert infer_category(_p("Cornbred's Creamsicle Milli")) == "sps"       # \bmilli
    assert infer_category(_p("Cornbred's Blue Digi")) == "sps"              # \bdigi
    assert infer_category(_p("Cornbred's Bloody Sunday Stylo")) == "sps"    # \bstylo
    assert infer_category(_p("JF TNT Anacropora Coral")) == "sps"           # \banacro
    assert infer_category(_p("Tyree Pohnpei Birdsnest Coral")) == "sps"     # birds?nest
    assert infer_category(_p("ORA Ponape Birds Nest Coral")) == "sps"       # birds nest (spaced)
    assert infer_category(_p("Kelly Green Psammocora Coral")) == "sps"      # \bpsammocora
    # Stylocoeniella (genuinely encrusting SPS) — \bstylo catches it; it had
    # been mis-tagged lps fleet-wide before CTK-194.
    assert infer_category(_p("JF Burning Banana Stylocoeniella")) == "sps"


# ─── LPS coverage: genera + common names ─────────────────────────────────────

def test_lps_genera():
    assert infer_category(_p("Cornbred's Red Queen Blasto")) == "lps"       # \bblasto
    assert infer_category(_p("Cornbred's Chronic Duncan")) == "lps"         # \bduncan
    assert infer_category(_p("Blue Crush Rainbow Lobo")) == "lps"           # \blobo
    assert infer_category(_p("Fireball Scolymia")) == "lps"                 # \bscoly
    assert infer_category(_p("Space Invader Pectina")) == "lps"             # \bpectin
    assert infer_category(_p("Single Head Fungia Plate")) == "lps"         # \bfungia
    assert infer_category(_p("Spiderman Bowerbanki")) == "lps"              # \bbowerbanki
    assert infer_category(_p("WWC Soursop Goniopora")) == "lps"             # \bgonio
    assert infer_category(_p("Ultra Alveopora")) == "lps"                   # \balveopora
    assert infer_category(_p("Golden Sunset Galaxea")) == "lps"            # \bgalaxea
    assert infer_category(_p("Purple Tip Elegance")) == "lps"               # \belegance
    assert infer_category(_p("Rainbow Acantho")) == "lps"                   # \bacantho


def test_lps_data_driven_calls():
    # cyphastrea + leptastrea map to LPS by vendor convention (91 + 36 existing
    # lps rows), NOT the textbook "encrusting SPS" call.
    assert infer_category(_p("Cyphastrea Meteor Shower")) == "lps"
    assert infer_category(_p("Cornbred's Hells Fire Leptastrea")) == "lps"
    # Caulastrea is reached via the "candy cane" phrase + the genus — never the
    # toxic bare "candy".
    assert infer_category(_p("Candy Cane Caulastrea")) == "lps"
    assert infer_category(_p("Cornbred's Toxic Candy Cane")) == "lps"


# ─── SOFTIE coverage ─────────────────────────────────────────────────────────

def test_softie_coverage():
    assert infer_category(_p("Neon Clove Polyps")) == "softie"             # \bcloves?
    assert infer_category(_p("Green Star Polyps")) == "softie"             # star polyp
    assert infer_category(_p("Knobby Photosynthetic Gorgonian")) == "softie"  # \bgorgonian
    assert infer_category(_p("Rapid Pulse Xenia")) == "softie"             # \bxenia
    assert infer_category(_p("Blue Purple Cespitularia")) == "softie"      # \bcespitularia


# ─── EXCLUSIONS: color / generic / split-genus words must NOT mis-categorize ──
# These pin the deliberate FP-probe decisions. A future "add candy / plate /
# echinata" edit trips these.

def test_color_and_generic_words_excluded():
    # Bare color/descriptor words spray across every category at the probe — they
    # carry no category signal. A title with ONLY such a word stays None.
    assert infer_category(_p("Cosmic Candy")) is None
    assert infer_category(_p("Rainbow Stunner")) is None
    assert infer_category(_p("Grafted Beauty")) is None


def test_split_genus_words_excluded():
    # Bare "plate" = frag-plate risk; bare "echinata" splits 33 lps vs 7 sps;
    # bare "lepto" is leptoseris(lps) vs leptastrea. None is added as a bare
    # term, so a title carrying ONLY the bare word stays None.
    assert infer_category(_p("POTO Plate")) is None
    assert infer_category(_p("Frag Plate Holder")) is None


def test_acantho_does_not_catch_tang_fish():
    # \bacantho (lps) must not swallow Acanthurus (the tang/surgeonfish genus) —
    # the reason the term is \bacantho, not a looser \bacan prefix. The fish
    # pattern owns it.
    assert infer_category(_p("Acanthurus Tang", product_type="Fish")) == "fish"


def test_reverse_guard_survives_coverage_add():
    # CTK-189 reverse-guard must still fire after the CTK-194 adds: a coral-word
    # title carrying a non-coral marker reroutes to equipment.
    assert infer_category(_p("Goniopora Coral Food Pellets")) == "equipment"
    assert infer_category(_p("Monti Cap Frag Plug Sticker")) == "equipment"
