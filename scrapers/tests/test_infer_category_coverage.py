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


def test_plate_floor_is_guarded():
    # CTK-199 round 3 supersedes the round-2 "bare plate stays None" rule with a
    # NULL-only loose-plate FLOOR: a bare trailing "plate" trade name floors to
    # lps, but the frag-mounting / bundle guard keeps equipment + multi-item lots
    # out. (echinata + lepto, also formerly excluded as split-genus, now classify
    # lps by the round-3 fleet vote — pinned in test_ctk199_lps_round3.)
    assert infer_category(_p("POTO Plate")) == "lps"             # bare plate trade name -> floor
    assert infer_category(_p("Oil Spill Plate")) == "lps"        # directive-named trade form
    assert infer_category(_p("Burning Shadow Plate")) == "lps"
    assert infer_category(_p("Frag Plate Holder")) is None       # holder -> equipment, guarded
    assert infer_category(_p("Frag Mounting Plate")) is None     # mounting -> equipment, guarded
    assert infer_category(_p("Coral Plate Mystery Box")) is None  # box/mystery lot, guarded
    # "Plate Coral" (the phrase) still classifies via the main lps term, floor or
    # not — so a frag-pack of plate corals stays lps (status quo; bundle-as-coral
    # is Lever B's lane, parked).
    assert infer_category(_p("Plate Coral Frag Pack")) == "lps"
    # The WWC non-coral that must NOT floor: \bplate\b does not match "plating".
    assert infer_category(_p("Purple Plating Sponge")) is None


def test_acantho_does_not_catch_tang_fish():
    # \bacantho (lps) must not swallow Acanthurus (the tang/surgeonfish genus) —
    # the reason the term is \bacantho, not a looser \bacan prefix. The fish
    # pattern owns it.
    assert infer_category(_p("Acanthurus Tang", product_type="Fish")) == "fish"


def test_abbreviation_prefixes_are_whole_word_anchored():
    # /code-review fold: the abbreviations whose prefix collides with a common
    # English / equipment word are whole-word anchored (the CTK-186 \bpump ->
    # "Pumpkin" trap). sps is checked before equipment, so an open prefix would
    # tag an equipment item a coral category and slip the feed exclusion.
    # Equipment items must NOT become sps:
    assert infer_category(_p("Neptune Apex Digital Controller")) == "equipment"  # \bdigi\b not \bdigi
    assert infer_category(_p("Digital Refractometer")) is None                   # 'digital' alone -> not sps
    assert infer_category(_p("5 milliliter Coral Dose Cup")) is None             # \bmilli\b not \bmilli
    assert infer_category(_p("100 millimeter Acrylic Tube")) is None             # 'millimeter' -> not sps
    assert infer_category(_p("Frags Across the Board Sale")) is None             # \bacro\b not \bacro
    assert infer_category(_p("Apple Pectin Powder")) is None                     # 'pectin' additive -> not lps
    # ...but the real abbreviations + full genera still classify:
    assert infer_category(_p("Cornbred's Blue Digi")) == "sps"        # \bdigi\b (standalone abbrev)
    assert infer_category(_p("Green Digitata Colony")) == "sps"       # \bdigitata\b
    assert infer_category(_p("Cornbred's Creamsicle Milli")) == "sps"  # \bmilli\b
    assert infer_category(_p("POTO Pink Millie")) == "sps"           # \bmillie (Millepora diminutive)
    assert infer_category(_p("Red Millepora")) == "sps"              # \bmillepora\b
    assert infer_category(_p("Cornbred's Green Slimer Acro")) == "sps"  # \bacro\b
    assert infer_category(_p("Space Invader Pectina")) == "lps"        # \bpectina\b
    assert infer_category(_p("Rose Gold Pectinia")) == "lps"           # \bpectinia\b


def test_reverse_guard_survives_coverage_add():
    # CTK-189 reverse-guard must still fire after the CTK-194 adds: a coral-word
    # title carrying a non-coral marker reroutes to equipment.
    assert infer_category(_p("Goniopora Coral Food Pellets")) == "equipment"
    assert infer_category(_p("Monti Cap Frag Plug Sticker")) == "equipment"


# ─── CTK-199 round-2 coverage: the genus/common-name anchors CTK-194 left on the
# residual in_stock NULL population (titles drawn from the 2026-06-25 audit). Each
# positive assert FAILS if its term is removed from _CATEGORY_PATTERNS.

def test_ctk199_sps_round2():
    assert infer_category(_p("ATL Blue Clover Stag")) == "sps"              # \bstag
    assert infer_category(_p("Blue Bottlebrush Staghorn")) == "sps"        # \bstaghorn
    assert infer_category(_p("JF Psammacora")) == "sps"                     # psammacora spelling
    assert infer_category(_p("Kelly Green Psammocora Coral")) == "sps"      # psammocora still works


def test_ctk199_lps_round2():
    assert infer_category(_p("TSA Sour Orange Lithophyllon Coral")) == "lps"  # \blithophyllon
    assert infer_category(_p("JF Sly Devil Litho")) == "lps"                # \blitho (abbrev)
    assert infer_category(_p("Berrylicious Indophyllia")) == "lps"          # \bindophyllia
    assert infer_category(_p("JF Nuclear Trumpet")) == "lps"                # \btrumpet (Caulastrea)
    assert infer_category(_p("WWC Diablo Diaseris")) == "lps"               # \bdiaseris
    assert infer_category(_p("Neon Green Plate Coral")) == "lps"            # \bplate coral (phrase)
    assert infer_category(_p("Rainbow Bubble Coral")) == "lps"              # \bbubble coral (phrase)
    # hydnophora + astreopora: textbook SPS, but the fleet files them LPS
    # (41:3 and 8:1) — vendor convention wins per the CTK-194 rule.
    assert infer_category(_p("WWC Fuzzy Leprechaun Hydnophora")) == "lps"   # \bhydnophora
    assert infer_category(_p("JF Blueberry Blast Hydno XXL Frag")) == "lps"  # \bhydno (abbrev)
    assert infer_category(_p("JF Lime Time Astreopora")) == "lps"           # \bastreopora


def test_ctk199_softie_round2():
    assert infer_category(_p("Waving Hand Anthelia Coral")) == "softie"     # \banthelia
    assert infer_category(_p("Daisy Polyps Coral")) == "softie"            # \bdaisy polyps (Clavularia)
    assert infer_category(_p("Bicolor Pipe Organ")) == "softie"            # \bpipe organ
    assert infer_category(_p("Tubipora Musica Colony")) == "softie"        # \btubipora (octocoral, NOT lps)


def test_ctk199_trap_tokens_are_phrase_scoped():
    # The common-word trap tokens must NEVER fire bare — only the phrase form.
    # These pin the round-2 traps the directive flagged (bubble / daisy / stag).
    assert infer_category(_p("BC Bubblebath Unicorn")) is None     # bare "bubble" must not -> lps
    assert infer_category(_p("Neon Green Bubble")) is None         # bubble w/o "coral" stays None
    assert infer_category(_p("Lazy Daisy Stunner")) is None        # bare "daisy" must not -> softie
    assert infer_category(_p("Main Stage Display Rack")) is None   # "stage" must not hit \bstag


# ─── CTK-199 round-3 coverage: the genus/common-name anchors round 2 left on the
# ~60-row obviously-typed NULL remainder (titles from the 2026-06-26 audit). Each
# positive assert FAILS if its term is removed from _CATEGORY_PATTERNS.

def test_ctk199_lps_round3():
    assert infer_category(_p("Cornbred's Lava Flow Lepto")) == "lps"      # \blepto (Leptoseris abbrev)
    assert infer_category(_p("JF Lunar Lepto")) == "lps"
    assert infer_category(_p("Golden Galaxia")) == "lps"                  # \bgalaxia (Galaxea variant)
    assert infer_category(_p("Worms Platygyra Brain")) == "lps"          # \bplatygyra
    assert infer_category(_p("Red Heliofungia")) == "lps"                # \bheliofungia (Fungiidae)
    assert infer_category(_p("WWC Scroll Coral")) == "lps"               # \bscroll coral
    assert infer_category(_p("Yellow Turbinaria")) == "lps"              # \bturbinaria (scroll genus)
    assert infer_category(_p("Rainbow War Coral")) == "lps"              # \bwar coral (Favites/Cyphastrea)
    assert infer_category(_p("Neon Maze Brain")) == "lps"                # \bmaze brain
    # echinata: directive mapped chalice (Echinophyllia), but the fleet files it
    # lps 97:20:0 (Acanthastrea echinata dominates) — convention rule -> lps.
    assert infer_category(_p("Master Rainbow Echinata")) == "lps"        # \bechinata -> lps (fleet vote)
    assert infer_category(_p("Mango Tango Echinata")) == "lps"
    # ...but a genuine Echinophyllia still hits the chalice pattern FIRST.
    assert infer_category(_p("Echinophyllia echinata Chalice")) == "chalice"


def test_ctk199_sps_round3():
    assert infer_category(_p("JF Homewrecker Tenuis")) == "sps"          # \btenuis (Acropora tenuis)
    assert infer_category(_p("POTO Pink Mille")) == "sps"                # \bmille (Acropora millepora abbrev)
    # \bmille\b is distinct from the round-2 \bmilli\b / \bmillie / \bmillepora\b.
    assert infer_category(_p("Red Millepora")) == "sps"                  # round-2 term still classifies


def test_ctk199_softie_round3():
    # sympodium is an octocoral — softie, overriding the fleet's lps default
    # (the round-2 Tubipora call applied again: octocoral-as-LPS is a category
    # error, not an LPS/SPS tie).
    assert infer_category(_p("Green Sympodium Coral")) == "softie"       # \bsympodium


def test_ctk199_round3_skipped_tokens_stay_unclassified():
    # bare grandis (zoa trade-name signal) was deliberately NOT added — a title
    # carrying ONLY the bare word, with no other coral term, must stay None so a
    # future "just add grandis" edit trips a red test and re-checks the fleet vote.
    #
    # CTK-207 NOTE: pavona was the OTHER skipped token here (CTK-199 round-3 fleet
    # near-tie 30:26). CTK-207 re-decides it sps after a fresh fleet FP audit
    # (0 matched-coral mis-tags; the 30 lps-stored Pavona rows that flip lps->sps
    # are an intended standardization, not a regression) — see
    # test_ctk207_classifier_patch + CTK-207 results.md. This guard now pins only
    # grandis.
    assert infer_category(_p("Cosmic Grandis")) is None                  # bare grandis not added
    # ...but a real Palythoa Grandis still classifies zoa via the existing \bpaly.
    assert infer_category(_p("Palythoa Grandis")) == "zoa"


def test_ctk207_classifier_patch():
    # CTK-207 coverage-ADD pass (FP-gated, CTK-189 bar clean). New genus/common-name
    # title tokens for the blank-product_type Reef Under The Roof vendor; also
    # recovers ~31 in_stock fleet rows the title-classifier missed.
    # sps additions:
    assert infer_category(_p("Cali Tort")) == "sps"                      # \btort (Acropora tortuosa abbrev)
    assert infer_category(_p("Miyagi Acropora tortuosa")) == "sps"       # \btortuosa
    assert infer_category(_p("Bali Green Slimer")) == "sps"              # \bslimer (Acropora yongei trade)
    assert infer_category(_p("WWC Cactus Pavona")) == "sps"              # \bpavona (CTK-207 re-decision)
    assert infer_category(_p("JF Red Hot Setosa")) == "sps"             # \bsetosa (Montipora/Seriatopora)
    assert infer_category(_p("Pink Millepora Mili")) == "sps"           # \bmili (single-L millepora variant)
    # bird's-nest apostrophe fix: the apostrophe-s live form now matches alongside
    # "birds nest" / "bird nest" / "birdsnest".
    assert infer_category(_p("Pohnpei Bird's Nest")) == "sps"           # \bbird'?s?\s*nest
    assert infer_category(_p("Green Birdsnest Coral")) == "sps"         # one-word form still hits
    assert infer_category(_p("Pink Birds Nest")) == "sps"              # space form still hits
    # lps addition:
    assert infer_category(_p("Alveo Sunburst")) == "lps"               # \balveo (Alveopora abbrev/hyphen)
    assert infer_category(_p("Sunset Alveopora")) == "lps"             # full genus still classifies

    # FP guards — the whole-word anchors must NOT bleed into common English:
    assert infer_category(_p("Massively Distorted Frag Rack")) is None  # \btort must not catch "distort"
    assert infer_category(_p("Contorted Wire Holder")) is None          # ...nor "contort"
    # bare grandis still unclassified (unchanged by this ticket).
    assert infer_category(_p("Cosmic Grandis")) is None


def test_ctk209_fox_coral_phrase_token():
    # CTK-209 lps coverage-ADD: Fox Coral (Nemenzophyllia turbida), the Coral Stop
    # NULL "Baby Fox Coral" + 3 fleet rows. The token is the PHRASE "fox coral".
    assert infer_category(_p("Baby Fox Coral")) == "lps"      # Coral Stop door-buster-shape NULL
    assert infer_category(_p("Fox Coral")) == "lps"
    assert infer_category(_p("Turquoise Fox Coral")) == "lps"
    assert infer_category(_p("Green Fox Corals")) == "lps"    # plural form
    # CRITICAL FP guard — bare "Fox" must NEVER classify. "Jason Fox" (the jf
    # vendor) puts "Fox" in hundreds of unrelated coral titles; a bare \bfox\b
    # token would mis-tag all of them lps. These MUST stay their real category /
    # None, NOT lps.
    assert infer_category(_p("Jason Fox Acropora")) == "sps"  # \bacropora wins; fox must not force lps
    assert infer_category(_p("JF Fox Flame Zoa")) == "zoa"    # \bzoa wins; bare fox inert
    assert infer_category(_p("Jason Fox Mystery")) is None    # no coral term + bare fox => still None


def test_ctk199_round3_bare_phrase_traps_stay_none():
    # The round-3 phrase tokens (war coral / scroll coral / maze brain) must NEVER
    # fire on the bare leading word — those are common English / trade words.
    assert infer_category(_p("War Paint Zoa Stunner")) == "zoa"          # "war" must not bare-hit lps
    assert infer_category(_p("Scroll Saw Frag Rack")) is None            # "scroll" alone -> None
    assert infer_category(_p("Amazing Maze Runner")) is None             # "maze" alone -> None
    assert infer_category(_p("Brain Freeze Stunner")) is None            # bare "brain" must not -> lps
