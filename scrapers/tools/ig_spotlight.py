"""CTK-159 Slice B — Instagram spotlight publish-or-notify adapter.

Turns a scored ig_select candidate into a postable artifact and notifies Jon to
publish (D-1: semi-automated, human-in-the-loop). Mirrors the pure-core + I/O-
shell shape of ig_select.py / leak_scan.py: caption rendering is pure and unit-
driven; selection and the Slack POST are the I/O shell.

What the pipeline emits (the D-1 output contract, against CTK-157 rev4 — the
caption template of record):

  Line 0  optional personal line   — OMITTED. Never auto-generated; Jon adds a
                                      genuine aside only when he has one (rev4
                                      §"Optional personal line"). A forced-on-
                                      every-post opener is anti-canon.
  Line 1  {coral name} — {detail}  — the searchable lineage/species NAME a
                                      collector types when hunting (rev4 L39 +
                                      plan §Caption-system L107) is pre-filled
                                      from the named_corals match; absent a
                                      match the name slot is a {coral name}
                                      placeholder (the data plane has no clean
                                      lineage name without a match — raw vendor
                                      titles are not searchable names). The
                                      em-dash physical-detail half is LEFT BLANK
                                      for Jon — a human eyes-on-the-photo
                                      observation that D-1 forbids auto-
                                      generating; rendered as a fill-prompt, not
                                      content.
  Line 2  {Verb} at {SH} (@handle) — FULLY rendered. The lead-event arm maps to
                                      the canon verb (just-listed -> Listed,
                                      back-in-stock -> Back in stock,
                                      price-dropped -> Price dropped); vendor
                                      shorthand + parenthetical @handle come from
                                      branding-guide.md §Usage-rules IG-handle
                                      table (mirrored in VENDOR_IG below).
  Line 3  fixed closer             — "Full feed at coralticker.com — link in
                                      bio." Verbatim (rev4 L53).

  First comment  8-12 tag block    — per rev4 §"The hashtag layer". A lineage-
                                      name tag candidate (from the coral slug)
                                      carries a [verify live tag-feed] marker;
                                      the vendor branded tag renders ONLY for a
                                      vendor that has one (VENDOR_IG branded
                                      column — #battlecorals alone today) and
                                      carries a [verify vendor branded tag]
                                      marker. The ~5-7 niche reef-category tags
                                      depend on the coral TYPE, which is not in
                                      the data plane, so the block emits a
                                      {niche reef-category tags} fill-prompt
                                      rather than guess a wrong category. The
                                      [verify ...] markers are the standing
                                      per-post checks rev4 L74/L150 define.

Notify path (D-2 fallback = v1, per Slice-B B-6): render the artifact to the
CTK-011 Slack operator channel; Jon eyeballs the crop (image URL unfurls a
preview — brand-safety per D-1), fills Line 0 / the Line-1 detail, and taps to
post. A programmatic scheduler draft-push (Metricool/Later) is the Phase-2
graduation — when it lands only the final POST target swaps; selection, caption,
and cadence are unchanged. NO unofficial auto-login bots (account-ban risk).

D-5: the image is the STATIC mirrored vendor photo already in the pipeline. No
motion in v1 (Ken Burns deferred to CTK-163's owned-asset data-viz; AI animation
is rejected canon per branding-guide L129).

Run via:
  python -m scrapers.tools.ig_spotlight [--mode daily|weekly-roundup]
                                        [--top-n N] [--dry-run]

--dry-run renders to stdout without posting (the workflow_dispatch dry_run input
+ the path T7b acceptance drives). Reads NEON_DATABASE_URL + SLACK_WEBHOOK_URL
from the environment (.env via scrapers.common.db). Exit 0 on a clean run; 1 on
error (loud-failure posture).
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from scrapers.tools import ig_select
from scrapers.tools.ig_select import Candidate, DEFAULT_TOP_N
from scrapers.tools.content_queries import CONTENT_FORMATS, FormatDescriptor

# A-path reel output dir (CTK-164). Overridable via --out-dir; the GH Actions
# render uploads this dir as the run artifact (post_slack is a text webhook and
# cannot carry the file — Slack gets the pointer, the MP4 rides the artifact).
DEFAULT_REEL_DIR = "build/reels"

# ---------------------------------------------------------------------------
# Brand canon, mirrored from branding-guide.md §Usage-rules IG-handle table
# (CTK-157, Jon-confirmed 2026-06-14). Keyed by DB vendor_slug. CTK-159 renders
# the @mention + branded hashtag from THIS table; canon is the source of truth.
# A vendor missing from this table raises in vendor_attribution() rather than
# emit a handle-less caption — a dropped @mention silently kills the reshare,
# which is the one thing the caption exists to do (rev4 L50). ReefnBid is absent
# by design (no shop account, no active scraper — out of the spotlight rotation).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VendorIG:
    shorthand: str
    handle: str
    branded_hashtag: str | None


VENDOR_IG: dict[str, VendorIG] = {
    "wwc":             VendorIG("WWC",            "@worldwidecorals",             None),
    "jf":              VendorIG("JF",             "@jason_fox_signature_corals",  None),
    "tsa":             VendorIG("TSA",            "@topshelfaquatics",            None),
    "battlecorals":    VendorIG("Battlecorals",   "@battlecorals",                "#battlecorals"),
    "unique_corals":   VendorIG("Unique Corals",  "@uniquecorals",                None),
    "aquasd":          VendorIG("Aqua SD",        "@aqua_sd",                     None),
    "pacific_east":    VendorIG("PEA",            "@pacificeastaquaculture",      None),
    "tidal_gardens":   VendorIG("Tidal Gardens",  "@tidalgardens",                None),
    "vivid_aquariums": VendorIG("Vivid",          "@vivid_aquariums",             None),
    "poto":            VendorIG("POTO",           "@piecesoftheocean",            None),
    "reef_chasers":    VendorIG("Reef Chasers",   "@reefchasers",                 None),
    "cornbred":        VendorIG("Cornbred",       "@cornbredcorals",              None),
    # CTK-146 — williamsons active (vendor_id=33). Handle confirmed canon
    # 2026-06-28 (/brand-manager): @williamsonsreef verified via the IG bio's
    # reverse link to williamsonsreef.com (the site itself exposes no IG link).
    # Canon row lives in branding-guide.md §Usage-rules IG-handle table. No
    # branded hashtag.
    "williamsons":     VendorIG("Williamson's",   "@williamsonsreef",             None),
    # CTK-148 — reefregeneration active (vendor_id=34). Handle confirmed canon
    # 2026-06-28 (/brand-manager): @reef_regeneration. NOT the reverse-link path
    # used for Williamson's — reefregeneration.com exposes no IG link AND the IG
    # bio carries no link back to the site. Confirmed instead by a distinctive
    # positioning match: the bio states fully-aquacultured corals + 10% of profits
    # to coral restoration, the site's own signature claim (not a generic coral-
    # shop line, not a domain-mirror guess). Canon row in branding-guide.md
    # §Usage-rules IG-handle table. No branded hashtag.
    "reefregeneration": VendorIG("Reef Regen",    "@reef_regeneration",           None),
    # CTK-149 — austinaquafarms active (vendor_id=35). Handle confirmed canon
    # 2026-06-28 (/brand-manager): @austinaquafarms. Same path as Reef Regen, NOT
    # Williamson's reverse-link: austinaquafarms.com exposes no IG link, and the
    # bio's outbound link couldn't be read. Confirmed instead by exact display-name
    # match ("Austin Aqua Farms") + a distinctive-positioning match: the bio sells
    # "rare and beautiful corals from the world's most exotic reefs" with diver-
    # direct Australia/Indonesia sourcing — the site's own signature wild-import
    # positioning (/pages/about-us), not a generic coral-shop line, not a domain-
    # mirror guess. Canon row in branding-guide.md §Usage-rules IG-handle table.
    # No branded hashtag.
    "austinaquafarms": VendorIG("AAF",            "@austinaquafarms",             None),
    # CTK-207 — reefundertheroof active (vendor_id=36). Handle confirmed canon
    # 2026-06-28 (/brand-manager): @reefundertheroof. Strongest path of the wave —
    # the FORWARD link, not Williamson's reverse-link or Reef Regen/AAF positioning
    # match: reefundertheroof.com itself exposes the IG link directly
    # (instagram.com/reefundertheroof), and the profile resolves with a matching
    # display name ("Reef Under The Roof - Goran P."). Shorthand stays the full name
    # — no community abbreviation surfaced, and invented codes are banned. Canon row
    # in branding-guide.md §Usage-rules IG-handle table. No branded hashtag.
    "reefundertheroof": VendorIG("Reef Under The Roof", "@reefundertheroof",        None),
    # CTK-209 — coralstop active (vendor_id=37). Handle confirmed canon 2026-06-28:
    # @coralstopsales. The FORWARD-link path (strongest, same as RUTR): coralstop.com
    # itself exposes the IG link directly (instagram.com/coralstopsales) in the
    # storefront markup. NB the handle is @coralstopsales, NOT @coralstop (the bare
    # domain handle is a different/unrelated account) — the live forward link is the
    # disambiguator. Shorthand "Coral Stop" — no community abbreviation surfaced, and
    # invented codes are banned. Canon row in branding-guide.md §Usage-rules IG-handle
    # table (pending /brand-manager). No branded hashtag.
    "coralstop":       VendorIG("Coral Stop",   "@coralstopsales",              None),
    # CTK-212 — biota active (vendor_id=65). Handle confirmed canon 2026-06-29:
    # @biotaaquariums. The FORWARD-link path (strongest, same as RUTR/CoralStop):
    # the LIVE store (shop.thebiotagroup.com) AND thebiotagroup.com both expose the
    # IG link directly (instagram.com/biotaaquariums) in the storefront markup. NB
    # the @handle is @biotaaquariums even though the biotaaquariums.com DOMAIN is
    # parked/dead — the IG account is live + is the one the live store forward-links
    # to (the disambiguator). Shorthand "Biota". Canon row in branding-guide.md
    # §Usage-rules IG-handle table (pending /brand-manager). No branded hashtag.
    "biota":           VendorIG("Biota",          "@biotaaquariums",              None),
    # CTK-143 — cherry active. Handle confirmed canon 2026-07-01 (/brand-manager):
    # @cherrycorals. NOT a forward-link confirm — cherrycorals.com's own IG links are
    # misconfigured (they redirect to the vendor's Facebook, not IG), and the bio's
    # outbound link couldn't be read. Confirmed instead by a distinctive positioning +
    # cross-platform match: @cherrycorals (Livonia, MI — the farm's location) carries
    # the site's own "if it's not HOT, it's not here" WYSIWYG-indoor-farm positioning,
    # and mirrors the vendor's YouTube (@CherryCorals) + TikTok (cherrycorals) — not a
    # bare-domain guess. Same path as Reef Regen/AAF, used here because the site's
    # forward-link is broken. Shorthand "Cherry Corals" (CC reads generic in plain
    # prose). Canon row in branding-guide.md §Usage-rules IG-handle table. No hashtag.
    "cherry":          VendorIG("Cherry Corals",  "@cherrycorals",                None),
}

# Lead-event arm -> canon event verb (rev4 L45-48; cross-channel verb canon).
# price-dropped covers both a CT-observed drop and a vendor markdown (rev4 L45).
EVENT_VERB: dict[str, str] = {
    "just-listed": "Listed",
    "back-in-stock": "Back in stock",
    "price-dropped": "Price dropped",
}

# Line-1 name slot when there is no named_corals match AND no raw_title to clean:
# a fill-prompt, NOT a guess. Raw vendor titles aren't searchable lineage names
# (rev4 L39), but a CLEANED title (mechanism tags shed) is a better Line-1 seed
# than a bare placeholder when an unmatched candidate wins (clean_descriptive_title).
NAME_PLACEHOLDER = "{coral name}"

# Listing-mechanism denylist for clean_descriptive_title (/brand-manager ruling
# 2026-06-17, after the unmatched-$9.59-frag misfire). Case-insensitive, word-
# boundaried regexes; strip ONLY these tokens (listing mechanics, never coral
# description), collapse leftover separators, never reword. Seeded from the ruling
# (WYSIWYG in its -WYSIWYG / WYSIWYG / (WYSIWYG) forms; frag pack / frag-pack; lot;
# pack-size tags); extend as new mechanism tags surface. Sized/multiword patterns
# precede bare words so e.g. "frag pack" and "3-pack" strip before any bare token.
_TITLE_DENYLIST = (
    r"\bWYSIWYG\b",
    r"\bfrag[\s-]*pack\b",          # "frag pack" / "frag-pack"
    r"\b\d+\s*-?\s*pack\b",         # pack-size tags: "3 pack" / "5-pack" / "2pack"
    r"\bpack\s+of\s+\d+\b",         # "pack of 3"
    r"\blot\b",                     # word-boundaried: never touches "Pilot" etc.
)


def clean_descriptive_title(raw_title: str) -> str:
    """Shed listing-mechanism suffixes from a vendor raw_title for the Line-1 name
    slot when an UNMATCHED candidate wins (/brand-manager ruling 2026-06-17). Strips
    only the _TITLE_DENYLIST tokens (case-insensitive), removes empty parens left
    behind, collapses leftover separators, and trims dangling edge punctuation. It
    NEVER rewords and NEVER invents a lineage/strain name (the provenance bar) — the
    output is the vendor's own words minus the mechanism tags. May return "" if the
    title was nothing but mechanism tokens; the caller then falls back to the
    placeholder."""
    text = raw_title or ""
    for pattern in _TITLE_DENYLIST:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE)
    text = re.sub(r"\(\s*\)", " ", text)        # empty parens a stripped token left
    text = re.sub(r"\s+", " ", text)             # collapse whitespace runs
    text = re.sub(r"\s+([,.;:])", r"\1", text)   # tidy space-before-punctuation
    text = re.sub(r"\s*[-–—]\s*$", "", text)     # trailing dangling dash
    text = re.sub(r"^\s*[-–—]\s*", "", text)     # leading dangling dash
    return text.strip(" -–—,").strip()


# ---------------------------------------------------------------------------
# Fold #3 (CTK-170, retro /code-review; fallback revised per Jon ruling 2026-06-17)
# — coral-type-noun survival gate, deciding CLEANED-vs-RAW for the Line-1 seed.
#
# clean_descriptive_title sheds mechanism tags but can leave a MANGLED remnant: a
# mid-string strip leaving an edge-connector fragment ('Frag Pack of Chalices' ->
# 'of Chalices') or a bare 1-token remnant ('WYSIWYG Frag' -> 'Frag') no longer
# cleanly NAMES the piece. The gate (descriptive_name) returns the cleaned title when
# it is NOT an edge-connector fragment AND (a coral-type noun survives OR it is a
# >= 2-token descriptive phrase) — the multi-word arm (close-pass #1) keeps a clean
# typeless title like 'Rainbow Showpiece' instead of leaking 'WYSIWYG' to the raw
# fallback; otherwise it returns None.
#
# The render_caption LADDER (Jon ruling 2026-06-17): matched -> coral_name; else the
# cleaned title when the gate accepts it; else the RAW raw_title VERBATIM; else
# NAME_PLACEHOLDER only when raw_title is empty. Line 1 is an operator SEED Jon edits
# before posting, so a noisy-but-real vendor title beats a placeholder — and verbatim
# vendor words honor the provenance bar (no fabrication, no rewording). The gate is
# the cleaned-vs-raw decision; the placeholder is the no-title-at-all floor.
#
# No runtime coral-type vocabulary exists to reuse: the matcher (scrapers/common/
# matcher.py) runs on named_corals + aliases + trigram, with no type/genus lexicon,
# and the seed list's type/genus columns live in research markdown, not code. So
# this is a hand-rolled curated lexicon of reef coral TYPES + common genera/groups —
# the words that signal "this string describes a coral". Matched word-boundaried,
# case-insensitive, with a trailing-'s' plural tolerance (so 'chalices' -> 'chalice',
# 'acans' -> 'acan'). Extend as new type words surface; over-inclusion only widens
# what substitutes (cleaned vs. the raw title — both are real vendor words).
# ---------------------------------------------------------------------------
_CORAL_TYPE_NOUNS = frozenset({
    # Broad type buckets.
    "sps", "lps", "softie", "zoa", "zoanthid", "paly", "palythoa", "mushroom",
    "shroom", "anemone", "bta", "rbta", "nem", "coral", "clam", "chalice",
    # Genera + common trade group names.
    "acropora", "acro", "millepora", "milli", "tenuis", "montipora", "monti",
    "cap", "digitata", "euphyllia", "torch", "hammer", "frogspawn", "favia",
    "favites", "acan", "acanthastrea", "micromussa", "micro", "lobophyllia",
    "lobo", "scoly", "scolymia", "blasto", "blastomussa", "goniopora", "gonio",
    "alveopora", "leptoseris", "lepto", "cyphastrea", "psammocora", "stylophora",
    "stylo", "stylocoeniella", "seriatopora", "birdsnest", "turbinaria",
    "porites", "anacropora", "pavona", "echinophyllia", "echino", "mycedium",
    "duncan", "candycane", "caulastrea", "trumpet", "ricordea", "ric",
    "discosoma", "rhodactis", "bounce", "gsp", "xenia", "clove", "leather",
    "fungia", "plate", "wellso", "wellsophyllia", "trachyphyllia", "trach",
    "brain", "lobophytum", "sinularia", "nepthea", "cespitularia", "goni",
})

# Orphan connector words: a cleaned title that OPENS or CLOSES on one ('Frag Pack of
# Chalices' -> 'of Chalices') is the signature of a mid-string strip that left a
# fragment, not a name. The gate rejects such fragments to the raw fallback. Interior
# connectors are fine — 'WWC Eye of the Storm Chalice' keeps its 'of'.
_ORPHAN_EDGE_WORDS = frozenset({
    "of", "the", "a", "an", "and", "with", "for", "in", "on", "by", "to", "from",
})


def _contains_coral_type_noun(text: str) -> bool:
    """True when any whole word in `text` is a known coral-type noun (case-
    insensitive, trailing-'s' plural tolerant). The signal that a cleaned title
    still NAMES a coral rather than being a mechanism-only remnant."""
    for tok in re.findall(r"[A-Za-z]+", text.lower()):
        if tok in _CORAL_TYPE_NOUNS or (tok.endswith("s") and tok[:-1] in _CORAL_TYPE_NOUNS):
            return True
    return False


def descriptive_name(raw_title: str) -> str | None:
    """The CLEANED Line-1 seed for an UNMATCHED winner when it still cleanly NAMES the
    piece, else None — the cleaned-vs-raw gate (fold #3; the raw fallback lives in
    render_caption per the Jon ruling 2026-06-17). clean_descriptive_title sheds the
    mechanism tags; this ACCEPTS the result when it is not an edge-connector fragment
    AND (a coral-type noun survives OR it is a >= 2-token descriptive phrase). The
    multi-word arm (close-pass #1 fix) keeps a clean typeless title like 'Rainbow
    Showpiece WYSIWYG' -> 'Rainbow Showpiece' instead of leaking the WYSIWYG by
    falling to raw. REJECTED (-> None -> raw fallback): a bare 1-token remnant
    ('WYSIWYG Frag' -> 'Frag'), an edge-connector fragment ('Frag Pack of Chalices' ->
    'of Chalices'), and '' / a mechanism-only title (cleans empty). A None routes the
    caller to the raw title, NOT the placeholder — verbatim vendor words beat a
    fragment (provenance-safe)."""
    cleaned = clean_descriptive_title(raw_title)
    if not cleaned:
        return None
    toks = cleaned.split()
    if (toks[0].lower().strip(",.;:") in _ORPHAN_EDGE_WORDS
            or toks[-1].lower().strip(",.;:") in _ORPHAN_EDGE_WORDS):
        return None  # edge-connector fragment -> mangled; prefer the raw title
    alpha_tokens = re.findall(r"[A-Za-z]+", cleaned)
    if _contains_coral_type_noun(cleaned) or len(alpha_tokens) >= 2:
        return cleaned
    return None  # bare 1-token typeless remnant -> prefer the raw title


# Line-1 em-dash detail: the human photo-observation D-1 forbids auto-generating.
# Rendered as a fill-prompt so the blank slot is unambiguous in the operator
# channel; this is NOT generated description.
DETAIL_PROMPT = "[one thing you can see in the photo]"

# First-comment niche tags depend on coral TYPE (not in the data plane) — a
# fill-prompt, not a guess at the category (rev4 L68 ~5-7 niche reef tags).
NICHE_PROMPT = "{niche reef-category tags}"

CLOSER = "Full feed at coralticker.com — link in bio."


# ---------------------------------------------------------------------------
# CTK-161 D-2 — content-format auto-publish gate.
#
# The publish gate lives HERE in the Slice-B adapter, NOT the query layer: the
# content query layer (content_queries.py) computes every format ungated; the
# adapter decides what auto-publishes. Only NON-comparative formats (aggregate
# activity, most-restocked, single-listing drop) enter the auto-publish path. A
# COMPARATIVE format (cheapest-across-vendors, market-report) — one whose render
# names which shop is cheapest — computes + renders to a draft but routes to
# manual hold: a public price-ranking waits for Jon's deliberate publish call
# (plan §Build-vs-publish split), because it commoditizes the vendor pricing the
# reshare strategy + future partnerships lean on.
#
# WIRING: the content-format render/publish loop is a future CTK-161 consumer
# slice (the data-post rendering on top of the shared layer). It MUST route its
# format descriptors through auto_publishable() before any auto-POST, so a
# comparative format can never auto-publish by omission. Pre-wired here, ahead of
# that loop, so the gate exists before the first content post can be drafted.
# ---------------------------------------------------------------------------


def auto_publishable(descriptor: FormatDescriptor) -> bool:
    """D-2 gate: True only for a NON-comparative format. The single code
    obligation of the build-vs-publish split — comparative formats never enter
    the auto-publish path."""
    return not descriptor.comparative


def auto_publishable_formats() -> list[FormatDescriptor]:
    """The content formats cleared for auto-publish (comparative == false). The
    comparative ones (cheapest-across-vendors, market-report) are computed +
    render-ready but excluded here — manual-hold until Jon's publish call."""
    return [d for d in CONTENT_FORMATS.values() if auto_publishable(d)]


# ---------------------------------------------------------------------------
# Pure core — no DB, no network. Tests drive these directly.
# ---------------------------------------------------------------------------


def vendor_attribution(vendor_slug: str) -> VendorIG:
    """The vendor's IG attribution (shorthand / @handle / branded hashtag).
    Raises KeyError loudly on an unmapped slug — a missing @mention silently
    kills the reshare, so a map-miss must fail the run, not emit a broken
    caption (loud-failure posture)."""
    try:
        return VENDOR_IG[vendor_slug]
    except KeyError:
        raise KeyError(
            f"vendor_slug {vendor_slug!r} not in VENDOR_IG (branding-guide.md "
            f"§Usage-rules IG-handle table). Add the handle before this vendor "
            f"can enter the spotlight rotation."
        ) from None


def event_verb(arm: str) -> str:
    """The canon event verb for a lead-event arm. Raises loudly on an unknown
    arm — get_listing_lead_event only emits the three mapped arms, so an unmapped
    value is a contract break, not a row to paper over."""
    try:
        return EVENT_VERB[arm]
    except KeyError:
        raise KeyError(
            f"lead-event arm {arm!r} has no canon verb (expected one of "
            f"{sorted(EVENT_VERB)})."
        ) from None


def lineage_hashtag(coral_slug: str | None) -> str | None:
    """A best-guess lineage-name hashtag candidate from the named_corals slug,
    or None when there is no match. Per rev4 L74 lineage tags are candidates,
    not confirmed — the [verify live tag-feed] marker (added by the caller) is
    the standing check Jon runs before posting. Returns just the bare #tag."""
    if not coral_slug:
        return None
    token = "".join(ch for ch in coral_slug.lower() if ch.isalnum())
    return f"#{token}" if token else None


def render_caption(c: Candidate) -> str:
    """The three-line caption skeleton (Line 0 omitted; Line 1 name-filled,
    detail-blank; Line 2 fully rendered; Line 3 verbatim closer). The poster
    fills the Line-1 detail and may prepend an optional Line 0.

    Line-1 name slot ladder (fold #3, Jon ruling 2026-06-17): matched -> the canonical
    coral name; else the cleaned descriptive title when it still NAMES a coral (a
    coral-type noun survives the mechanism strip, no edge-connector mangle); else the
    RAW raw_title VERBATIM (a noisy-but-real vendor title beats a placeholder — Line 1
    is an operator seed Jon edits pre-post, and verbatim vendor words honor the
    provenance bar); else the {coral name} placeholder ONLY when there is no raw_title
    at all. Never a fabricated lineage name at any rung."""
    if c.named_coral_id is not None and c.coral_name:
        name = c.coral_name
    else:
        name = descriptive_name(c.raw_title) or (c.raw_title if c.raw_title.strip() else NAME_PLACEHOLDER)
    v = vendor_attribution(c.vendor_slug)
    line1 = f"{name} — {DETAIL_PROMPT}"
    line2 = f"{event_verb(c.arm)} at {v.shorthand} ({v.handle})."
    return "\n".join([line1, line2, CLOSER])


# ---------------------------------------------------------------------------
# CTK-177 — IG niche-hashtag seeding (text-derived, Jon-gated, no inference).
#
# branding-guide.md §"IG niche-hashtag seeding (CTK-177, 2026-06-20)" CLEARED the
# canon: the first-comment niche layer MAY be auto-seeded from coral-type nouns
# literally present in the vendor raw_title, on two honest sources — (a) type tags
# via a FIXED type-noun -> tag-family map, (b) a standing community-tag set true for
# any coral spotlight. The seeded block is a Jon-edited candidate (same human gate
# as the lineage [verify live tag-feed] marker); nothing reaches IG unread.
#
# Hard floor (canon L194): no color-morph / strain / grade / WYSIWYG tag, no
# mega-tag (#coral / #reef), no vision. Enforced STRUCTURALLY — every emitted tag
# is a deterministic lookup off a token literally in the title (map value or its
# bare form) or a member of the fixed standing set; nothing requiring the photo,
# and nothing outside the closed vocabulary, can emit. Genus-expansion of an
# explicit abbreviation IS within "what the title states" (canon L195): an
# acanthastrea IS an acan and IS an LPS for every specimen, from the table, no
# look-at-the-photo judgment.
#
# NICHE_TYPE_TAGS is SEPARATE from _CORAL_TYPE_NOUNS (the Line-1 name gate lexicon)
# on purpose — the gate decides cleaned-vs-raw for the NAME; this maps a matched
# type noun to its tag family. Keyed by the canonical (singular) lexicon token.
# Any _CORAL_TYPE_NOUNS token with no entry here falls back to its bare #<token>
# (never silently drop a real type signal) — EXCEPT the _NICHE_SUPPRESS tokens,
# whose bare form is a banned mega-tag and emit nothing.
# ---------------------------------------------------------------------------

# Tokens in _CORAL_TYPE_NOUNS whose bare #<token> would be a banned mega-tag (canon
# floor). "coral" is in the Line-1 lexicon but #coral is exactly the mega-tag the
# rev4 hashtag layer bans — suppress it (other matched type nouns + standing carry
# the discoverability). No usable type signal from a "coral"-only title -> fallback.
_NICHE_SUPPRESS = frozenset({"coral"})

# Standing community-tag set (canon L193) — type-independent, niche-not-mega, real
# reefer community feeds; honest on any coral post. Fixed canonical order, NO
# rotation in v1 (rotation is posting-craft, not canon; directive point 3).
STANDING_COMMUNITY_TAGS: tuple[str, ...] = (
    "#reeftank", "#reefkeeping", "#coralfrags", "#reef2reef",
    "#reefaquarium", "#reefersofinstagram",
)

# Type-noun -> tag-family map. abbreviation -> full-name + genus -> broad category
# ONLY (canon L195); every value is a fixed lookup with one right answer for every
# specimen of that type. Curated + closed: extend as new type nouns surface.
NICHE_TYPE_TAGS: dict[str, tuple[str, ...]] = {
    # Broad type buckets (already a category; emit the niche form).
    "sps": ("#sps",),
    "lps": ("#lps",),
    "softie": ("#softcorals",),
    "zoa": ("#zoa", "#zoanthid"),
    "zoanthid": ("#zoanthid", "#zoa"),
    "paly": ("#paly", "#palythoa"),
    "palythoa": ("#palythoa", "#paly"),
    "mushroom": ("#mushroomcoral",),
    "shroom": ("#mushroomcoral",),
    "anemone": ("#anemone",),
    "bta": ("#bta", "#anemone"),
    "rbta": ("#rbta", "#anemone"),
    "nem": ("#anemone",),
    "clam": ("#clam", "#tridacna"),
    "chalice": ("#chalice", "#chalicecoral", "#lps"),
    # Acropora group -> SPS.
    "acropora": ("#acropora", "#sps"),
    "acro": ("#acro", "#acropora", "#sps"),
    "millepora": ("#millepora", "#acropora", "#sps"),
    "milli": ("#milli", "#millepora", "#sps"),
    "tenuis": ("#tenuis", "#acropora", "#sps"),
    # Montipora group -> SPS.
    "montipora": ("#montipora", "#sps"),
    "monti": ("#monti", "#montipora", "#sps"),
    "cap": ("#montipora", "#sps"),
    "digitata": ("#digitata", "#montipora", "#sps"),
    # Other SPS genera.
    "cyphastrea": ("#cyphastrea", "#sps"),
    "psammocora": ("#psammocora", "#sps"),
    "stylophora": ("#stylophora", "#stylo", "#sps"),
    "stylo": ("#stylo", "#stylophora", "#sps"),
    "stylocoeniella": ("#stylocoeniella", "#sps"),
    "seriatopora": ("#seriatopora", "#birdsnest", "#sps"),
    "birdsnest": ("#birdsnest", "#seriatopora", "#sps"),
    "porites": ("#porites", "#sps"),
    "anacropora": ("#anacropora", "#sps"),
    "pavona": ("#pavona", "#sps"),
    # Euphyllia group -> LPS.
    "euphyllia": ("#euphyllia", "#lps"),
    "torch": ("#torchcoral", "#euphyllia", "#lps"),
    "hammer": ("#hammercoral", "#euphyllia", "#lps"),
    "frogspawn": ("#frogspawn", "#euphyllia", "#lps"),
    # Other LPS genera.
    "favia": ("#favia", "#lps"),
    "favites": ("#favites", "#lps"),
    "acan": ("#acan", "#acanthastrea", "#lps"),
    "acanthastrea": ("#acanthastrea", "#acan", "#lps"),
    "micromussa": ("#micromussa", "#micro", "#lps"),
    "micro": ("#micromussa", "#lps"),
    "lobophyllia": ("#lobophyllia", "#lobo", "#lps"),
    "lobo": ("#lobo", "#lobophyllia", "#lps"),
    "scoly": ("#scoly", "#scolymia", "#lps"),
    "scolymia": ("#scolymia", "#scoly", "#lps"),
    "blasto": ("#blasto", "#blastomussa", "#lps"),
    "blastomussa": ("#blastomussa", "#blasto", "#lps"),
    "goniopora": ("#goniopora", "#gonio", "#lps"),
    "gonio": ("#gonio", "#goniopora", "#lps"),
    "goni": ("#goniopora", "#lps"),
    "alveopora": ("#alveopora", "#lps"),
    "leptoseris": ("#leptoseris", "#lepto", "#lps"),
    "lepto": ("#lepto", "#leptoseris", "#lps"),
    "turbinaria": ("#turbinaria", "#lps"),
    "echinophyllia": ("#echinophyllia", "#echino", "#chalice", "#lps"),
    "echino": ("#echino", "#echinophyllia", "#lps"),
    "mycedium": ("#mycedium", "#chalice", "#lps"),
    "duncan": ("#duncan", "#duncancoral", "#lps"),
    "candycane": ("#candycane", "#caulastrea", "#lps"),
    "caulastrea": ("#caulastrea", "#candycane", "#lps"),
    "trumpet": ("#trumpetcoral", "#caulastrea", "#lps"),
    "fungia": ("#fungia", "#platecoral", "#lps"),
    "plate": ("#platecoral", "#fungia", "#lps"),
    "wellso": ("#wellso", "#wellsophyllia", "#lps"),
    "wellsophyllia": ("#wellsophyllia", "#wellso", "#lps"),
    "trachyphyllia": ("#trachyphyllia", "#trach", "#lps"),
    "trach": ("#trach", "#trachyphyllia", "#lps"),
    "brain": ("#braincoral", "#lps"),
    # Mushroom / corallimorph group.
    "ricordea": ("#ricordea", "#mushroomcoral"),
    "ric": ("#ric", "#ricordea", "#mushroomcoral"),
    "discosoma": ("#discosoma", "#mushroomcoral"),
    "rhodactis": ("#rhodactis", "#mushroomcoral"),
    "bounce": ("#bounce", "#mushroomcoral"),
    # Softies.
    "gsp": ("#gsp", "#greenstarpolyp", "#softcorals"),
    "xenia": ("#xenia", "#softcorals"),
    "clove": ("#clovepolyp", "#softcorals"),
    "leather": ("#leathercoral", "#softcorals"),
    "lobophytum": ("#lobophytum", "#softcorals"),
    "sinularia": ("#sinularia", "#softcorals"),
    "nepthea": ("#nepthea", "#softcorals"),
    "cespitularia": ("#cespitularia", "#softcorals"),
}

FIRST_COMMENT_TAG_CAP = 12  # rev4 "8-12 tag block" — hard maximum

# Precedence tiers: kept on overflow in this order (lower = higher precedence).
# Drop the lowest-precedence (standing) first (directive point 4).
_TIER_LINEAGE, _TIER_BRANDED, _TIER_TYPE, _TIER_STANDING = 0, 1, 2, 3
# Display order is independent of precedence: niche block (type) first, standing
# next, the verify-marked lineage/branded candidates last so Jon spots the
# [verify ...] markers at the tail (mirrors the pre-CTK-177 niche-then-markers shape).
_DISPLAY_RANK = {_TIER_TYPE: 0, _TIER_STANDING: 1, _TIER_LINEAGE: 2, _TIER_BRANDED: 3}


def title_type_nouns(raw_title: str) -> list[str]:
    """The coral-type nouns literally present in raw_title, as their canonical
    (singular) _CORAL_TYPE_NOUNS keys, in first-appearance order, deduped. Reuses
    _contains_coral_type_noun's plural-tolerant matching (trailing-'s'), but
    RETURNS the matches instead of a bool — the seed set for the niche tags."""
    found: list[str] = []
    seen: set[str] = set()
    for tok in re.findall(r"[A-Za-z]+", (raw_title or "").lower()):
        if tok in _CORAL_TYPE_NOUNS:
            key = tok
        elif tok.endswith("s") and tok[:-1] in _CORAL_TYPE_NOUNS:
            key = tok[:-1]
        else:
            continue
        if key not in seen:
            seen.add(key)
            found.append(key)
    return found


def type_tags_for_title(raw_title: str) -> list[str]:
    """The ordered, deduped type/genus hashtags for the type nouns in raw_title.
    Each matched noun maps through NICHE_TYPE_TAGS, or falls back to its bare
    #<token> when unmapped (never drop a real type signal). _NICHE_SUPPRESS tokens
    (whose bare form is a banned mega-tag) emit nothing. Empty when the title has
    no recognizable type noun (or only suppressed ones) -> the caller falls back to
    the {niche reef-category tags} fill-prompt."""
    tags: list[str] = []
    seen: set[str] = set()
    for key in title_type_nouns(raw_title):
        if key in _NICHE_SUPPRESS:
            continue
        for tag in NICHE_TYPE_TAGS.get(key, (f"#{key}",)):
            if tag not in seen:
                seen.add(tag)
                tags.append(tag)
    return tags


def _assemble_first_comment_tags(type_tags: list[str], lineage: str | None,
                                 branded: str | None) -> list[str]:
    """Dedup + precedence-cap the real first-comment tags, returned in display
    order. Precedence (kept on overflow): lineage > branded > type/genus >
    standing — standing drops first, then type, never the verify-marked
    lineage/branded. The markers ride the display string; dedup compares the bare
    tag so a lineage/type collision can't double-emit."""
    entries: list[tuple[int, str, str]] = []  # (tier, display, bare) — precedence order
    if lineage:
        entries.append((_TIER_LINEAGE, f"{lineage}[verify live tag-feed]", lineage))
    if branded:
        entries.append((_TIER_BRANDED, f"{branded}[verify vendor branded tag]", branded))
    entries.extend((_TIER_TYPE, t, t) for t in type_tags)
    entries.extend((_TIER_STANDING, t, t) for t in STANDING_COMMUNITY_TAGS)

    seen: set[str] = set()
    deduped: list[tuple[int, str]] = []
    for tier, display, bare in entries:  # precedence order -> first occurrence wins
        if bare in seen:
            continue
        seen.add(bare)
        deduped.append((tier, display))

    deduped = deduped[:FIRST_COMMENT_TAG_CAP]  # precedence-ordered -> tail (standing) drops first
    deduped.sort(key=lambda d: _DISPLAY_RANK[d[0]])  # stable -> display order
    return [display for _, display in deduped]


def render_first_comment(c: Candidate) -> str:
    """The first-comment hashtag block (rev4 §"The hashtag layer"; CTK-177 seeding):
    text-derived type/genus tags from the coral-type nouns in raw_title + the
    standing community set + the lineage candidate ([verify live tag-feed]) when a
    named match exists + the vendor branded tag ([verify vendor branded tag]) for a
    vendor that has one. Deduped, capped at 12 (standing drops first on overflow).

    Fallback (canon CTK-177): a raw_title with no recognizable type noun preserves
    the {niche reef-category tags} fill-prompt ahead of the standing tags — Jon
    hand-fills the type tags only when the title gave no honest signal. The seeded
    block is a Jon-edited candidate, never auto-posted."""
    type_tags = type_tags_for_title(c.raw_title)
    lineage = lineage_hashtag(c.coral_slug)
    branded = vendor_attribution(c.vendor_slug).branded_hashtag
    tags = _assemble_first_comment_tags(type_tags, lineage, branded)
    if not type_tags:
        tags = [NICHE_PROMPT] + tags
    return " ".join(tags)


def render_operator_block(c: Candidate) -> str:
    """The Slack operator-channel render for one candidate (the "help me send"
    surface): the image URL (Slack unfurls a preview so Jon eyeballs the crop),
    the copy-paste caption skeleton, the first-comment block, the listing URL,
    and the score breakdown. Code-fenced blocks copy cleanly on tap."""
    coral = c.coral_name or c.raw_title or f"id={c.listing_id}"
    sh = vendor_attribution(c.vendor_slug).shorthand
    xv = " · cross-vendor-cheapest" if c.is_cross_vendor_cheapest else ""
    return (
        f"*{sh} — {coral}*  (score {c.score:.1f}{xv})\n"
        f"image (eyeball the crop): {c.image_url}\n"
        f"listing: {c.product_url}\n"
        f"caption skeleton — add an optional Line 0, fill the Line-1 photo detail:\n"
        f"```\n{render_caption(c)}\n```\n"
        f"first comment — fill the niche tags, verify the marked tags:\n"
        f"```\n{render_first_comment(c)}\n```"
    )


def render_notification(mode: str, candidate_count: int, gated_count: int,
                        selected: list[Candidate]) -> str:
    """The full operator-channel message: a header summary + one block per
    selected candidate. daily -> one block; weekly-roundup -> the top-N set."""
    header = (
        f"ig-spotlight {mode} — {len(selected)} candidate(s) to post "
        f"({candidate_count} scanned, {gated_count} passed the image gate)"
    )
    if not selected:
        return header + "\n(nothing cleared the image gate this window.)"
    blocks = "\n\n".join(render_operator_block(c) for c in selected)
    return f"{header}\n\n{blocks}"


# ---------------------------------------------------------------------------
# I/O shell — selection (via ig_select) + Slack POST.
# ---------------------------------------------------------------------------


def _post_and_record(conn, message: str, picks: list[Candidate], mode: str) -> int:
    """The shared non-dry-run tail of run()/run_reels(): POST the operator message,
    then record the surfaced picks to the band-history (Item C). Records AFTER a
    successful post so the balance window reflects what went out (D-1: surfaced-pick
    proxy). Returns the rows recorded. post_slack stays a local import so the module
    doesn't drag the Slack client at load."""
    from scrapers.common.cohort_signal import post_slack
    post_slack(message)
    return ig_select.record_picks(conn, picks, mode)


def run(mode: str, top_n: int, dry_run: bool = False) -> int:
    from scrapers.common import db

    conn = db.get_conn()
    try:
        candidates, gated, selected = ig_select.select(conn, mode, top_n)

        message = render_notification(mode, len(candidates), len(gated), selected)

        if dry_run:
            print(message)
            return 0

        recorded = _post_and_record(conn, message, selected, mode)
    finally:
        conn.close()

    print(f"ig-spotlight {mode}: posted {len(selected)} candidate(s) to the operator "
          f"channel ({recorded} recorded to pick history).")
    return 0


# ---------------------------------------------------------------------------
# CTK-164 A-path — Ken Burns reel render + delivery.
#
# Surface is LOCKED A-path only: pan/zoom the CLEAN mirrored vendor photo. No
# card, no baked data row, no CoralTicker branding on the image (CTK-157 §5
# reshare canon; attribution rides the caption per CTK-159 D-4). INV-01 does
# NOT apply — no listing line renders on the image, so data_row.py is untouched.
# ---------------------------------------------------------------------------


def render_reel(c: Candidate, out_dir: str | Path) -> Path:
    """Render one candidate's clean mirrored photo to a Ken Burns MP4. Fetches
    the 600px mirror, composes the 9:16 blurred-fill frame, encodes the pan.
    Raises on fetch or render failure (the batch driver catches + skips)."""
    from scrapers.common import video
    from scrapers.common.http import fetch_image

    if not c.image_url:
        raise RuntimeError(f"candidate id={c.listing_id} has no image_url (image gate should have dropped it)")
    image_bytes = fetch_image(c.image_url)
    if image_bytes is None:
        raise RuntimeError(f"fetch_image returned None for {c.image_url}")

    frame = video.compose_9x16_blurred_fill(image_bytes)
    out_path = Path(out_dir) / f"{c.vendor_slug}-{c.listing_id}.mp4"

    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    try:
        frame.save(tmp, "PNG")
        tmp.close()
        video.render_kenburns(tmp.name, out_path, motion_spec=video.DEFAULT_MOTION)
    finally:
        os.unlink(tmp.name)
    return out_path


def write_caption_sidecar(c: Candidate, out_dir: str | Path) -> Path:
    """Write the caption sidecar next to a rendered reel (CTK-176): the same
    {vendor_slug}-{listing_id} stem as render_reel's .mp4, with a .txt extension.
    Content is render_caption(c) + a blank line + render_first_comment(c) — Jon
    needs BOTH the caption skeleton and the first-comment tag block to post by
    hand. ig_deliver reads this pair off disk so delivery never re-runs selection
    (non-idempotent: re-fires record_picks, may pick a different candidate than
    the one rendered). Returns the .txt path."""
    out_path = Path(out_dir) / f"{c.vendor_slug}-{c.listing_id}.txt"
    body = f"{render_caption(c)}\n\n{render_first_comment(c)}\n"
    out_path.write_text(body, encoding="utf-8")
    return out_path


def render_batch(conn, mode: str, top_n: int, out_dir: str | Path):
    """Select candidates and render each selected one to a reel. A single
    render failure skips that candidate (logged) rather than crashing the batch
    — the grid-stocking pass should bank the reels that do render. Returns
    (all_candidates, gated, results) where results is [(Candidate, Path|None)]."""
    candidates, gated, selected = ig_select.select(conn, mode, top_n)
    Path(out_dir).mkdir(parents=True, exist_ok=True)

    results: list[tuple[Candidate, Path | None]] = []
    for c in selected:
        try:
            path: Path | None = render_reel(c, out_dir)
        except Exception as e:  # noqa: BLE001 — skip one, keep the batch going
            print(
                f"WARN: reel render failed for {c.vendor_slug} id={c.listing_id}: "
                f"{type(e).__name__}: {e}",
                file=sys.stderr,
            )
            path = None
        # CTK-176: emit the caption sidecar only for a reel that actually rendered
        # (no .mp4 means nothing to deliver, so a lone .txt would be a dangling
        # half-pair). A sidecar-write failure must not crash the batch — mirror the
        # render skip above; the reel still banks, it just lands without its caption.
        if path is not None:
            try:
                write_caption_sidecar(c, out_dir)
            except Exception as e:  # noqa: BLE001 — skip the sidecar, keep the batch going
                print(
                    f"WARN: caption sidecar failed for {c.vendor_slug} id={c.listing_id}: "
                    f"{type(e).__name__}: {e}",
                    file=sys.stderr,
                )
        results.append((c, path))
    return candidates, gated, results


def render_reel_block(c: Candidate, path: Path | None) -> str:
    """The operator block for one rendered reel: the existing caption/eyeball
    block plus a pointer to the MP4 on disk (Slack carries text only)."""
    pointer = (
        f"reel rendered -> {path}"
        if path is not None
        else "reel render FAILED (see logs) — post the static image instead"
    )
    return f"{render_operator_block(c)}\n{pointer}"


def render_reel_notification(mode: str, candidate_count: int, gated_count: int,
                             results: list[tuple[Candidate, Path | None]],
                             out_dir: str | Path) -> str:
    """The operator-channel message for a reel batch: a header summary + one
    block per candidate, each pointing at its MP4. The MP4s ride the run
    artifact / out-dir — post_slack is a webhook and cannot upload files."""
    rendered = sum(1 for _, p in results if p is not None)
    header = (
        f"ig-spotlight {mode} reels — {rendered}/{len(results)} rendered "
        f"({candidate_count} scanned, {gated_count} passed the image gate). "
        f"Grab the MP4s from {out_dir} (run artifact)."
    )
    if not results:
        return header + "\n(nothing cleared the image gate this window.)"
    blocks = "\n\n".join(render_reel_block(c, p) for c, p in results)
    return f"{header}\n\n{blocks}"


def run_reels(mode: str, top_n: int, out_dir: str | Path, dry_run: bool = False) -> int:
    from scrapers.common import db

    conn = db.get_conn()
    try:
        candidates, gated, results = render_batch(conn, mode, top_n, out_dir)

        message = render_reel_notification(mode, len(candidates), len(gated), results, out_dir)

        if dry_run:
            print(message)
            return 0

        # Record the surfaced picks (the selected candidates, not the render outcome)
        # so a render miss still counts as "this band went to the queue".
        recorded = _post_and_record(conn, message, [c for c, _ in results], mode)
    finally:
        conn.close()

    rendered = sum(1 for _, p in results if p is not None)
    print(f"ig-spotlight {mode} reels: {rendered} rendered to {out_dir}; notified operator "
          f"channel ({recorded} recorded to pick history).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mode", choices=("daily", "weekly-roundup"), default="daily",
                        help="Selection window + size (daily top-1 / weekly-roundup top-N).")
    parser.add_argument("--top-n", type=int, default=None,
                        help="Override the per-mode default selection size.")
    parser.add_argument("--reels", action="store_true",
                        help="Render Ken Burns reels (CTK-164 A-path) instead of the static-image block.")
    parser.add_argument("--out-dir", default=DEFAULT_REEL_DIR,
                        help="Reel output dir (--reels mode; uploaded as the GH Actions artifact).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Render to stdout without posting to the operator channel.")
    args = parser.parse_args()
    top_n = args.top_n if args.top_n is not None else DEFAULT_TOP_N[args.mode]
    try:
        if args.reels:
            return run_reels(args.mode, top_n, args.out_dir, dry_run=args.dry_run)
        return run(args.mode, top_n, dry_run=args.dry_run)
    except Exception as e:  # noqa: BLE001 — surface loudly, exit 1 (loud-failure posture)
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
