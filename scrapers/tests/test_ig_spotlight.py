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
  test_first_comment_no_lineage_no_match   no match -> niche prompt only, no lineage tag
  test_operator_block_carries_artifact     image URL + listing URL + caption + first comment
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
    NAME_PLACEHOLDER,
    NICHE_PROMPT,
    VENDOR_IG,
    clean_descriptive_title,
    event_verb,
    lineage_hashtag,
    render_caption,
    render_first_comment,
    render_operator_block,
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


def test_caption_unmatched_with_title_prefills_cleaned():
    # Unmatched (no named_coral_id) WITH a raw_title: Line 1 pre-fills the CLEANED
    # title (mechanism tags shed), never a fabricated lineage name, never the placeholder.
    c = Candidate.from_row(_cand_row(raw_title="WWC Eye of the Storm Chalice WYSIWYG"))
    line1 = render_caption(c).split("\n")[0]
    assert line1.startswith("WWC Eye of the Storm Chalice — "), line1
    assert NAME_PLACEHOLDER not in line1


def test_caption_unmatched_without_title_falls_back():
    # No raw_title -> the {coral name} placeholder.
    c = Candidate.from_row(_cand_row(raw_title=""))
    assert render_caption(c).split("\n")[0].startswith(f"{NAME_PLACEHOLDER} — ")
    # A raw_title that cleans to empty (all mechanism tokens) also falls back.
    c2 = Candidate.from_row(_cand_row(raw_title="WYSIWYG Lot"))
    assert render_caption(c2).split("\n")[0].startswith(f"{NAME_PLACEHOLDER} — ")


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
    fc = render_first_comment(Candidate.from_row(_named()))
    assert "#sunkistbounce[verify live tag-feed]" in fc, fc
    assert fc.startswith(NICHE_PROMPT), fc


def test_first_comment_no_lineage_no_match():
    fc = render_first_comment(Candidate.from_row(_cand_row()))
    assert "[verify live tag-feed]" not in fc, fc
    assert fc == NICHE_PROMPT, fc


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
