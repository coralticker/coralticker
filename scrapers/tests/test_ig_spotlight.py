"""scrapers/tests/test_ig_spotlight.py — CTK-159 Slice B unit coverage for the
Instagram spotlight publish-or-notify adapter's caption render.

Pure tests — no DB, no network. They drive the caption core
(scrapers/tools/ig_spotlight.py) directly: the D-1 output contract (Line 0
omitted, Line 1 name-filled / detail-blank, Line 2 fully rendered from the verb
map + IG-handle table, Line 3 verbatim), the handle-map-miss loud-failure, the
verb map, and the first-comment hashtag block (lineage candidate + verify
markers + the conditional vendor branded slot).

Runnable as:
  python -m scrapers.tests.test_ig_spotlight

Coverage:
  test_handle_table_covers_active_vendors  all 11 active scraper slugs mapped
  test_vendor_attribution_raises           unmapped slug -> KeyError (loud-fail)
  test_event_verb_map                      three arms -> canon verbs
  test_event_verb_raises_unknown_arm       unmapped arm -> KeyError (loud-fail)
  test_lineage_hashtag_from_slug           slug -> bare alnum #tag; None passthrough
  test_caption_line0_omitted               skeleton is exactly 3 lines, no opener
  test_caption_named_match                 Line 1 leads with the named coral name
  test_caption_no_named_match              Line 1 uses the {coral name} placeholder
  test_caption_detail_blank                em-dash half is the fill-prompt, not content
  test_caption_line2_by_arm                verb x vendor shorthand + @handle, all arms
  test_caption_line3_verbatim              fixed closer, exact
  test_first_comment_branded_battlecorals  #battlecorals carries the verify marker
  test_first_comment_no_branded_other      a vendor without one renders no branded slot
  test_first_comment_lineage_marker        named match -> lineage tag + verify marker
  test_first_comment_no_lineage_no_match   no match -> fill-prompt + standing tags preserved
  test_operator_block_carries_artifact     image URL + listing URL + caption + first comment

  CTK-177 niche-hashtag seeding:
  test_title_type_nouns_plural_tolerant            canonical keys, order, plural-tolerant
  test_seed_acan_expands_to_family                 acan -> #acan #acanthastrea #lps (canon)
  test_first_comment_seeds_type_and_standing       type noun -> type tags + standing, no prompt
  test_first_comment_dedups_across_sources         shared #lps appears once
  test_first_comment_caps_at_twelve_dropping_standing_first  cap at 12, standing drops first
  test_first_comment_closed_vocabulary_no_megatags structural floor: closed vocab, no #coral/#reef
  test_suppressed_coral_noun_falls_back            "coral" suppressed -> fill-prompt, never #coral
  test_every_lexicon_token_emits_or_is_suppressed  coverage: every type noun maps/bare-falls
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from scrapers.tools.ig_select import Candidate, MIRROR_HOST
from scrapers.tools import ig_spotlight
from scrapers.tools.ig_spotlight import (
    CLOSER,
    DETAIL_PROMPT,
    FIRST_COMMENT_TAG_CAP,
    NAME_PLACEHOLDER,
    NICHE_PROMPT,
    NICHE_TYPE_TAGS,
    STANDING_COMMUNITY_TAGS,
    VENDOR_IG,
    _CORAL_TYPE_NOUNS,
    _NICHE_SUPPRESS,
    clean_descriptive_title,
    descriptive_name,
    event_verb,
    lineage_hashtag,
    render_caption,
    render_first_comment,
    render_operator_block,
    title_type_nouns,
    type_tags_for_title,
    vendor_attribution,
)

NOW = datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc)

# The active scraper slugs = scrapers/vendors/*.yaml stems (= DB vendors.slug).
# Derived from the dir, NOT hardcoded: when a new scraper lands (e.g. Cherry,
# CTK-143) its YAML appears here automatically, so test_handle_table_covers_
# active_vendors fails at CI if VENDOR_IG lacks the row — caught in review, not
# as a live spotlight crash on the first event from that vendor. ReefnBid has no
# YAML (no shop account, no scraper), so it's correctly absent.
_VENDORS_DIR = Path(__file__).resolve().parent.parent / "vendors"
ACTIVE_SLUGS = {p.stem for p in _VENDORS_DIR.glob("*.yaml")}


def _cand_row(**kw) -> dict:
    """A get_listing_lead_event-shaped row; override any field."""
    base = dict(
        id=1, vendor_slug="wwc", vendor_display_name="World Wide Corals",
        raw_title="WYSIWYG Frag", named_coral_canonical_name=None,
        named_coral_slug=None, named_coral_id=None, event="just-listed",
        event_at=NOW, current_price=Decimal("89.99"), prior_price=None,
        compare_at_price=None, image_url=MIRROR_HOST + "/wwc/coral.webp",
        product_url="https://wwc.example/products/coral",
    )
    base.update(kw)
    return base


def _named(**kw) -> dict:
    """A row with a named_corals match (the common spotlight shape)."""
    return _cand_row(
        named_coral_id=100,
        named_coral_canonical_name="WWC Sunkist Bounce Mushroom",
        named_coral_slug="sunkist-bounce",
        **kw,
    )


# --- handle table + verb map (loud-failure contracts) --------------------

def test_handle_table_covers_active_vendors():
    missing = ACTIVE_SLUGS - set(VENDOR_IG)
    assert not missing, f"VENDOR_IG missing active vendor slug(s): {missing}"
    # Every entry has a non-empty shorthand + @handle (the reshare mechanism).
    for slug, v in VENDOR_IG.items():
        assert v.shorthand and v.handle.startswith("@"), f"bad attribution for {slug}"


def test_vendor_attribution_raises():
    raised = False
    try:
        vendor_attribution("reefnbid")  # real vendor, no shop account -> not mapped
    except KeyError:
        raised = True
    assert raised, "unmapped slug must raise (a dropped @mention kills the reshare)"


def test_event_verb_map():
    assert event_verb("just-listed") == "Listed"
    assert event_verb("back-in-stock") == "Back in stock"
    assert event_verb("price-dropped") == "Price dropped"


def test_event_verb_raises_unknown_arm():
    raised = False
    try:
        event_verb("price-raised")
    except KeyError:
        raised = True
    assert raised, "an unmapped arm is a contract break, not a row to paper over"


def test_lineage_hashtag_from_slug():
    assert lineage_hashtag("sunkist-bounce") == "#sunkistbounce"
    assert lineage_hashtag("WWC Nuclear-Green") == "#wwcnucleargreen"
    assert lineage_hashtag(None) is None
    assert lineage_hashtag("") is None


# --- caption skeleton (D-1 output contract) ------------------------------

def test_caption_line0_omitted():
    lines = render_caption(Candidate.from_row(_named())).split("\n")
    assert len(lines) == 3, "skeleton is exactly the 3 base lines; Line 0 is never auto-added"


def test_caption_named_match():
    line1 = render_caption(Candidate.from_row(_named())).split("\n")[0]
    assert line1.startswith("WWC Sunkist Bounce Mushroom — "), line1
    assert NAME_PLACEHOLDER not in line1


def test_clean_descriptive_title():
    # WYSIWYG in its three forms, all stripped; the real name survives.
    assert clean_descriptive_title("WWC Sunkist Bounce -WYSIWYG") == "WWC Sunkist Bounce"
    assert clean_descriptive_title("WWC Sunkist Bounce WYSIWYG") == "WWC Sunkist Bounce"
    assert clean_descriptive_title("(WYSIWYG) Rainbow Acan") == "Rainbow Acan"
    # frag-pack / pack-size / lot tags shed.
    assert clean_descriptive_title("Rainbow Acan Frag Pack") == "Rainbow Acan"
    assert clean_descriptive_title("Zoa Garden 5-Pack") == "Zoa Garden"
    assert clean_descriptive_title("Zoa Garden 3 pack") == "Zoa Garden"
    assert clean_descriptive_title("Mystery Coral Lot") == "Mystery Coral"
    # Mixed case, multiple tokens.
    assert clean_descriptive_title("Acan wysiwyg LOT") == "Acan"
    # Control: a real-name word that CONTAINS a denylist substring is NOT stripped
    # (word-boundaried — 'lot' inside 'Pilot' survives), and a clean title passes verbatim.
    assert clean_descriptive_title("Pilot Whale Paly") == "Pilot Whale Paly"
    assert clean_descriptive_title("WWC Eye of the Storm Chalice") == "WWC Eye of the Storm Chalice"
    # Nothing but mechanism tokens -> empty (caller falls back to placeholder).
    assert clean_descriptive_title("WYSIWYG Lot") == ""


def test_descriptive_name_type_noun_survival():
    # Fold #3 — the gate returns the CLEANED title ONLY when a coral-type noun
    # survives the strip (and it isn't an edge-connector fragment); else None.
    # 'WYSIWYG Frag' cleans to 'Frag' (NOT a coral type) -> None.
    assert descriptive_name("WYSIWYG Frag") is None
    # A clean typed title passes through (type noun present, interior 'of' kept).
    assert descriptive_name("WWC Eye of the Storm Chalice") == "WWC Eye of the Storm Chalice"
    # 'Rainbow Lot Chalice': 'lot' is stripped mid-string, but 'Chalice' survives and
    # the result isn't an edge-connector fragment -> a clean noun-bearing seed.
    rlc = descriptive_name("Rainbow Lot Chalice")
    assert rlc is not None and "Chalice" in rlc
    assert not rlc.lower().startswith(("of ", "the ", "and "))  # no orphan-connector lead


def test_descriptive_name_rejects_edge_connector_fragment():
    # 'Frag Pack of Chalices' -> mechanism strip leaves 'of Chalices', a fragment that
    # OPENS on the connector 'of'. Even though 'Chalices' is a type noun, the gate
    # rejects the fragment (-> None) so the caller falls back to the RAW title, not the
    # mangled fragment (Jon ruling 2026-06-17).
    assert descriptive_name("Frag Pack of Chalices") is None


def test_descriptive_name_accepts_multiword_typeless():
    # #1 fold: a clean, >= 2-token descriptive title with NO coral-type noun is still
    # accepted (mechanism tags shed) — it names the piece without leaking 'WYSIWYG'.
    assert descriptive_name("Rainbow Showpiece WYSIWYG") == "Rainbow Showpiece"
    assert descriptive_name("Mystery Showpiece Colony") == "Mystery Showpiece Colony"


def test_descriptive_name_rejects_bare_and_empty():
    # A bare 1-token remnant is not a name -> None (falls to raw); empty / cleans-empty
    # -> None.
    assert descriptive_name("WYSIWYG Frag") is None   # cleans to the 1-token 'Frag'
    assert descriptive_name("") is None
    assert descriptive_name("WYSIWYG Lot") is None    # cleans to empty


def test_caption_multiword_typeless_renders_cleaned():
    # #1 regression fix at the caption level: an unmatched 'Rainbow Showpiece WYSIWYG'
    # renders the CLEANED 'Rainbow Showpiece' (WYSIWYG shed), not the raw title with
    # the mechanism tag still on it.
    c = Candidate.from_row(_cand_row(raw_title="Rainbow Showpiece WYSIWYG"))
    line1 = render_caption(c).split("\n")[0]
    assert line1.startswith("Rainbow Showpiece — "), line1
    assert "WYSIWYG" not in line1


def test_caption_misfire_shape_falls_back_to_raw():
    # The exact #3 misfire shape at the caption level: an unmatched 'WYSIWYG Frag' has
    # no surviving type noun, so Line 1 now renders the RAW vendor title verbatim (an
    # operator seed Jon edits pre-post), NOT the placeholder and NOT the 'Frag' fragment.
    c = Candidate.from_row(_cand_row(raw_title="WYSIWYG Frag"))
    line1 = render_caption(c).split("\n")[0]
    assert line1.startswith("WYSIWYG Frag — "), line1
    assert NAME_PLACEHOLDER not in line1


def test_caption_mangled_fragment_falls_back_to_raw():
    # 'Frag Pack of Chalices' cleans to the edge-connector fragment 'of Chalices' ->
    # gate rejects -> Line 1 renders the RAW title verbatim, never 'of Chalices'.
    c = Candidate.from_row(_cand_row(raw_title="Frag Pack of Chalices"))
    line1 = render_caption(c).split("\n")[0]
    assert line1.startswith("Frag Pack of Chalices — "), line1
    assert not line1.startswith("of Chalices")
    assert NAME_PLACEHOLDER not in line1


def test_caption_unmatched_with_title_prefills_cleaned():
    # Unmatched (no named_coral_id) WITH a raw_title that still names a coral: Line 1
    # pre-fills the CLEANED title (mechanism tags shed), never a fabricated lineage name.
    c = Candidate.from_row(_cand_row(raw_title="WWC Eye of the Storm Chalice WYSIWYG"))
    line1 = render_caption(c).split("\n")[0]
    assert line1.startswith("WWC Eye of the Storm Chalice — "), line1
    assert NAME_PLACEHOLDER not in line1


def test_caption_empty_title_uses_placeholder():
    # The placeholder is the floor — ONLY when there is no raw_title at all.
    c = Candidate.from_row(_cand_row(raw_title=""))
    assert render_caption(c).split("\n")[0].startswith(f"{NAME_PLACEHOLDER} — ")


def test_caption_mechanism_only_title_falls_back_to_raw():
    # A raw_title that cleans to empty (all mechanism tokens) is still non-empty, so it
    # renders the RAW title verbatim — placeholder is reserved for an empty raw_title.
    c = Candidate.from_row(_cand_row(raw_title="WYSIWYG Lot"))
    line1 = render_caption(c).split("\n")[0]
    assert line1.startswith("WYSIWYG Lot — "), line1
    assert NAME_PLACEHOLDER not in line1


def test_caption_detail_blank():
    # The em-dash detail half is the human photo-observation: a fill-prompt,
    # NOT generated description. It must be exactly the prompt.
    line1 = render_caption(Candidate.from_row(_named())).split("\n")[0]
    detail = line1.split(" — ", 1)[1]
    assert detail == DETAIL_PROMPT, detail


def test_caption_line2_by_arm():
    # just-listed at WWC
    c = Candidate.from_row(_named(event="just-listed"))
    assert render_caption(c).split("\n")[1] == "Listed at WWC (@worldwidecorals)."
    # back-in-stock at Battlecorals
    c = Candidate.from_row(_named(vendor_slug="battlecorals", event="back-in-stock"))
    assert render_caption(c).split("\n")[1] == "Back in stock at Battlecorals (@battlecorals)."
    # price-dropped at PEA
    c = Candidate.from_row(_named(vendor_slug="pacific_east", event="price-dropped"))
    assert render_caption(c).split("\n")[1] == "Price dropped at PEA (@pacificeastaquaculture)."


def test_caption_line3_verbatim():
    assert render_caption(Candidate.from_row(_named())).split("\n")[2] == CLOSER
    assert CLOSER == "Full feed at coralticker.com — link in bio."


# --- first-comment hashtag block -----------------------------------------

def test_first_comment_branded_battlecorals():
    fc = render_first_comment(Candidate.from_row(_named(vendor_slug="battlecorals")))
    assert "#battlecorals[verify vendor branded tag]" in fc, fc


def test_first_comment_no_branded_other():
    fc = render_first_comment(Candidate.from_row(_named(vendor_slug="wwc")))
    assert "[verify vendor branded tag]" not in fc, fc


def test_first_comment_lineage_marker():
    # _named() raw_title is "WYSIWYG Frag" (no type noun) -> fallback keeps the
    # fill-prompt at the head; the lineage candidate still carries its marker.
    fc = render_first_comment(Candidate.from_row(_named()))
    assert "#sunkistbounce[verify live tag-feed]" in fc, fc
    assert fc.startswith(NICHE_PROMPT), fc


def test_first_comment_no_lineage_no_match():
    # CTK-177: "WYSIWYG Frag" has no recognizable type noun -> fallback preserves
    # the {niche reef-category tags} fill-prompt AND seeds the standing community
    # set (the old behavior was prompt-only; superseded by canon 2026-06-20).
    fc = render_first_comment(Candidate.from_row(_cand_row()))
    assert "[verify live tag-feed]" not in fc, fc
    assert fc.startswith(NICHE_PROMPT), fc
    for tag in STANDING_COMMUNITY_TAGS:
        assert tag in fc, f"standing tag {tag} missing from fallback: {fc}"


# --- CTK-177 niche-hashtag seeding ---------------------------------------

def _fc_tags(fc: str) -> list[str]:
    """Split a first-comment string into tags. The [verify ...] markers carry
    internal spaces, so a naive str.split() over-counts — match each #tag (plus an
    optional bracketed marker) or the {fill-prompt} as one token."""
    import re
    return re.findall(r"#[^\s\[]+(?:\[[^\]]*\])?|\{[^}]*\}", fc)


def test_title_type_nouns_plural_tolerant():
    # canonical singular keys, first-appearance order, deduped; "chalices" -> chalice.
    assert title_type_nouns("WWC Acan Lordhowensis") == ["acan"]
    assert title_type_nouns("Rainbow Chalices and Acans") == ["chalice", "acan"]
    assert title_type_nouns("WYSIWYG Frag") == []  # no type noun


def test_seed_acan_expands_to_family():
    # canon L195 worked example: acan -> abbreviation + full name + broad category.
    tags = type_tags_for_title("WWC Acan Lordhowensis")
    assert tags == ["#acan", "#acanthastrea", "#lps"], tags


def test_first_comment_seeds_type_and_standing():
    # A title WITH a type noun seeds type tags + the standing set; the fill-prompt
    # is GONE (the title gave an honest signal), and there is no lineage match here.
    c = Candidate.from_row(_cand_row(raw_title="WWC Torch Coral", vendor_slug="wwc"))
    fc = render_first_comment(c)
    assert NICHE_PROMPT not in fc, f"fill-prompt must drop when a type noun seeds: {fc}"
    assert "#torchcoral" in fc and "#euphyllia" in fc and "#lps" in fc, fc
    for tag in STANDING_COMMUNITY_TAGS:
        assert tag in fc, fc


def test_first_comment_dedups_across_sources():
    # "Acan Micromussa" both roll up to #lps -> it must appear exactly once.
    c = Candidate.from_row(_cand_row(raw_title="Acan Micromussa Combo"))
    fc = render_first_comment(c)
    assert _fc_tags(fc).count("#lps") == 1, fc


def test_first_comment_caps_at_twelve_dropping_standing_first():
    # A type-dense title overflows; the cap holds at 12 and standing drops before
    # the type tags (precedence: type > standing).
    c = Candidate.from_row(_named(
        raw_title="Acan Lobo Scoly Blasto Chalice Micromussa Combo",
        vendor_slug="battlecorals",  # adds a branded verify tag
    ))
    fc = render_first_comment(c)
    tags = _fc_tags(fc)
    assert len(tags) <= FIRST_COMMENT_TAG_CAP, f"{len(tags)} tags > cap: {fc}"
    # the highest-precedence candidates survive the cap
    assert any("[verify live tag-feed]" in t for t in tags), fc       # lineage kept
    assert any("[verify vendor branded tag]" in t for t in tags), fc  # branded kept
    # standing dropped first: at least one standing tag is gone under overflow
    dropped = [s for s in STANDING_COMMUNITY_TAGS if s not in tags]
    assert dropped, f"expected standing tags to drop under overflow: {fc}"


def test_first_comment_closed_vocabulary_no_megatags():
    # Structural floor: every emitted tag is in the closed vocabulary (map values
    # u bare-token forms u standing u lineage/branded u the fill-prompt); no
    # #coral / #reef mega-tag can ever appear.
    allowed = set()
    for fam in NICHE_TYPE_TAGS.values():
        allowed.update(fam)
    allowed.update(f"#{t}" for t in _CORAL_TYPE_NOUNS if t not in _NICHE_SUPPRESS)
    allowed.update(STANDING_COMMUNITY_TAGS)
    allowed.add(NICHE_PROMPT)
    for raw, slug in [
        ("WWC Acan Lordhowensis", "wwc"),
        ("Coral Frag", "wwc"),                 # only the suppressed "coral" noun
        ("Torch Hammer Frogspawn", "battlecorals"),
        ("WYSIWYG Frag", "wwc"),
    ]:
        c = Candidate.from_row(_named(raw_title=raw, vendor_slug=slug))
        fc = render_first_comment(c)
        tags = _fc_tags(fc)
        for tag in tags:
            bare = tag.split("[", 1)[0]  # strip any [verify ...] marker
            ok = bare in allowed or bare == lineage_hashtag(c.coral_slug) \
                or bare == vendor_attribution(slug).branded_hashtag
            assert ok, f"tag {tag!r} not in closed vocabulary for {raw!r}: {fc}"
        assert "#coral" not in tags, f"banned mega-tag #coral emitted: {fc}"
        assert "#reef" not in tags, f"banned mega-tag #reef emitted: {fc}"


def test_suppressed_coral_noun_falls_back():
    # "Coral" alone is a matched noun but suppressed -> no usable type tag -> the
    # fill-prompt fallback (never emits #coral).
    c = Candidate.from_row(_cand_row(raw_title="Mystery Coral", coral_slug=None,
                                     named_coral_id=None))
    fc = render_first_comment(c)
    assert "#coral" not in fc.split(), fc
    assert fc.startswith(NICHE_PROMPT), fc


def test_every_lexicon_token_emits_or_is_suppressed():
    # Coverage guarantee: every _CORAL_TYPE_NOUNS token either maps to a family or
    # bare-falls to #<token>, and is never silently dropped UNLESS suppressed.
    for tok in _CORAL_TYPE_NOUNS:
        tags = type_tags_for_title(tok)
        if tok in _NICHE_SUPPRESS:
            assert tags == [], f"{tok} is suppressed but emitted {tags}"
        else:
            assert tags, f"{tok} produced no tag (silently dropped)"


# --- operator block ------------------------------------------------------

def test_operator_block_carries_artifact():
    c = Candidate.from_row(_named())
    c.score = 174.8
    block = render_operator_block(c)
    assert c.image_url in block
    assert c.product_url in block
    assert render_caption(c) in block
    assert render_first_comment(c) in block
    assert "174.8" in block


def _run_all():
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failures = 0
    for fn in fns:
        try:
            fn()
            print(f"ok   {fn.__name__}")
        except AssertionError as e:
            failures += 1
            print(f"FAIL {fn.__name__}: {e}")
    print(f"\n{len(fns) - failures}/{len(fns)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    import sys
    sys.exit(_run_all())
