"""Title / category / price / stock coercion. Stage 4 of the arch §2.1
lifecycle. Same rules apply at scrape-time (vendor_listings.normalized_title)
and at named_corals seed-time (named_corals.normalized_name) per arch §3.3.
"""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation


# Strip-trailing-junk patterns per arch §3.3 example
# ("jf homewrecker tenuis 57xec_a5-041626 $650 in-stock" → "jf homewrecker tenuis").
# Order matters — the most specific patterns run first so the more aggressive
# fallbacks don't eat real title tokens.
_STRIP_PATTERNS = [
    re.compile(r"\$\s*\d+(?:\.\d+)?\s*(?:usd|\busd\b)?\s*$", re.IGNORECASE),  # trailing price
    re.compile(r"\b(?:in[- ]stock|out[- ]of[- ]stock|sold[- ]out|wysiwyg)\b\s*$", re.IGNORECASE),
    re.compile(r"\b\d+[a-z]+_[a-z0-9]+-\d+\b\s*$", re.IGNORECASE),  # SKU-shaped trailing tokens
    re.compile(r"\s+-\s*$"),  # trailing dash separator
]

_WHITESPACE_RUN = re.compile(r"\s+")


# Category inference from Shopify product_type + tags + title. Arch §1.4 enum:
# ('sps','lps','softie','zoa','mushroom','anemone','clam','chalice',
#  'fish','invert','equipment','other').
# Order matters — first hit wins. More specific labels before generic ones.
#
# CTK-186: each alternative is boundary-anchored PER-TERM (`\bTERM\b`). The
# pre-CTK-186 form anchored `\b` only on the first/last alternative of each
# pattern, so every MIDDLE term substring-matched: `\bpump` hit "Pumpkin",
# `tang` hit "Tangerine"/"Tango" — real corals false-tagged equipment/fish on
# the live feed. Same alternation-boundary bug documented in
# ctk117_fish_leak_detector.py:14-23 (fixed there only inside the WIDE operator
# probe; production stays NARROW per CTK-117 — anchor existing terms, add no
# nouns/genera). `s?` plural-tolerance is retained where a live product_type/
# title/tag plural needs it (chalice/softie/crab/clam + the six equipment
# terms: bare `\bpump\b` would drop "ECM Pumps" to NULL and re-leak equipment
# past the step-2 feed exclusion; `trachyphyllias?` keeps Vivid's pluralised
# genus bucket tag "WYSIWYG Scolymias Trachyphyllias & Wellsophyllias" matching
# lps — 17 live LPS rows would otherwise drop to NULL, caught in the CTK-186
# backfill dry run) or to preserve an original open-trailing form
# (anemone/mushroom/snail). Deliberate structures kept verbatim: the
# `\bzoa(?:nthid)?s?\b` suffix flex (test_tidal_gardens_parse.py:523), the
# leading-anchored/trailing-open `\bpaly` (catches "palythoa" + the Cornbred
# "Paly" product_type), and the `\bacan\b` abbreviation.
#
# CTK-194: a coverage-ADD pass (the OPPOSITE of CTK-117/186's NARROW "anchor
# existing terms, add no genera" posture — this ticket explicitly authorizes new
# genera/common-names, FP-gated). 718 in_stock rows sat at category IS NULL
# fleet-wide (POTO 305 + Cornbred 165 = 470; the two recently-onboarded vendors
# arrive with generic product_types — collection / live sale / Other / Blasto /
# Paly — and coral common-name titles absent from the patterns). The shipped
# 8-type category INCLUDE filter (WHERE category = …) drops NULL rows, so those
# corals vanished from any type-filtered view (Tier 1B). Terms below are
# evidence-driven (fleet audit + a full-catalog FP probe): each fills NULL rows
# and its category is the MAJORITY-VOTE of the already-categorized rows that
# carry it — so cyphastrea + leptastrea map to lps (91 + 36 existing lps rows;
# the textbook "encrusting SPS" call loses to vendor convention), not sps. Bare
# color/generic words (candy / rainbow / grafted) and split-genus words (bare
# echinata 33 lps vs 7 sps; bare plate = frag-plate risk; bare lepto =
# leptoseris-lps vs leptastrea) were EXCLUDED at the probe — Caulastrea is caught
# via the "candy cane" phrase, not bare "candy". Prefix anchors (`\bblasto`,
# `\bmonti`, `\bstylo`, `\bscoly`, `\bgoni`, `\blobo`, `\banacro`) catch genus +
# its vendor abbreviation in one term (`\bmonti` = montipora + "Monti"); the SPS
# abbreviations were the single biggest uncaught bucket (Cornbred/BattleCorals
# "...Milli / ...Monti / ...Digi / ...Acro / ...Stylo").
#
# /code-review fold (CTK-194 close): the abbreviations whose prefix collides with
# a common English / equipment word are WHOLE-WORD anchored, not open-prefixed —
# the same substring trap CTK-186 fixed (`\bpump`->"Pumpkin"). `\bdigi\b` (not
# `\bdigi` -> "digital"), `\bmilli\b`/`\bmillie` (not `\bmilli` -> "milliliter/
# millimeter"; `\bmillie` keeps the "Millie" Millepora diminutive, which is not a
# milliliter prefix), `\bacro\b` (not `\bacro` -> "across/acrobat"), and
# `\bpectinia\b|\bpectina\b` (not `\bpectin` -> the food additive). sps is checked
# before equipment, so an open prefix would have tagged "Digital Controller" sps
# -> a coral category that slips the CTK-186 equipment feed-exclusion. The full
# genus each abbreviation implied is now explicit (`\bdigitata\b`, `\bmillepora\b`;
# `\bacropora\b` was already present). Real Acro-/Millie-prefix coral trade names
# (Acroiris, Acroberry, "Pink Millie") stay sps via their product_type/tags, so
# the whole-word title anchors cost ~0 real rows (confirmed in the close DRY
# reconcile). 0 named-coral collisions; CTK-189 reverse-guard intact.
#
# CTK-199: a coverage-ADD round 2 (same sanctioned path as CTK-194 — explicitly
# authorized new genera/common-names, FP-gated via the dry-run backfill diff +
# the 0/248 matched-coral FP check). CTK-194 cut fleet in_stock NULL 718 -> 312;
# ~89 of the residual still carry a genus/common-name anchor the pattern set
# lacked. Each term below was evidence-driven (in_stock NULL audit 2026-06-25)
# and FP-checked against the 248 matched corals (named_coral_id NOT NULL, the
# CTK-189 0/237 method, now 0/248): 0 matched corals are mis-categorized by any
# new token. Each category is the MAJORITY VOTE of the already-categorized fleet
# rows carrying the term (the CTK-194 rule — vendor convention beats textbook),
# verified against the live fleet at build (2026-06-25 majority-vote pull):
#   sps   — stag/staghorn (Acropora common name, fleet 86:0); psammocora
#           widened to the live vendor spelling psammacora via [oa] (fleet
#           sps 98 : lps 30 — sps is the convention; the lps minority is the
#           mis-tag this round corrects).
#   lps   — lithophyllon + "litho" abbrev (fleet 59), indophyllia (45),
#           trumpet (Caulastrea), diaseris (29), plate coral (133), bubble
#           coral (31), AND hydnophora/hydno (fleet lps 41 : sps 3) +
#           astreopora (lps 8 : sps 1). hydnophora + astreopora are textbook
#           Merulinidae/Acroporidae "SPS", but the fleet overwhelmingly files
#           them LPS — so lps, per the CTK-194 convention rule (the directive's
#           sps guess lost to the live majority vote at the backfill dry run).
#   softie — anthelia (fleet softie 2 : lps 1), daisy polyps (Clavularia),
#           pipe organ + its genus tubipora. Tubipora musica is an OCTOCORAL
#           (subclass Octocorallia) — softie, NOT the fleet's lps default (19
#           rows): an octocoral-as-LPS is a stony-vs-soft category error, not an
#           LPS/SPS tie the convention rule would settle, so taxonomy wins here
#           and the CTK-199 backfill re-tags the 19 legacy lps pipe-organ rows.
# TRAP TOKENS (common-word collision) are PHRASE/whole-word scoped, never bare,
# per the directive + the CTK-186 substring lesson:
#   - `\bplate\s+coral\b` ONLY (never bare `plate`: it hits frag mounting
#     plates + "plate coral frag pack" bundles); the diaseris genus carries the
#     rest of the Fungiidae plate population via `\bdiaseris\b`.
#   - `\bbubble\s+coral\b` ONLY (never bare `bubble`: live NULL set has "bc
#     bubblebath unicorn", a trade name, not a Plerogyra bubble coral; a bare
#     token would also collide with bubble-tip anemones — though those hit the
#     anemone pattern first).
#   - `\bdaisy\s+polyps?\b` (never bare `daisy`: POTO/whimsical trade names).
#   - `\bstag(?:horn)?\b`, `\btrumpet\b` whole-word (no "stagger"/"trumpetfish"
#     substring bleed; fish is checked after lps but neither appears as a
#     coral-vendor fish row in the fleet — confirmed in the dry-run diff).
_CATEGORY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("chalice",  re.compile(r"\bchalices?\b|\bechinophyllia\b|\bmycedium\b|\boxypora\b", re.I)),
    ("anemone",  re.compile(r"\banemones?\b|\bbta\b|\brbta\b|\bcondy\b", re.I)),
    ("clam",     re.compile(r"\bclams?\b|\btridacna\b", re.I)),
    ("mushroom", re.compile(r"\bmushrooms?\b|\brhodactis\b|\bdiscosoma\b|\bricordea\b", re.I)),
    ("zoa",      re.compile(r"\bzoa(?:nthid)?s?\b|\bpaly", re.I)),
    ("softie",   re.compile(r"\bsofties?\b|\bsofty\b|\bleather\b|\btoadstool\b|\bkenya\b|\bsinularia\b|\bsarcophyton\b|\bcloves?\b|\bgorgonian|\bxenia\b|\bcespitularia\b|\bstar\s+polyps?\b|\banthelia\b|\bdaisy\s+polyps?\b|\bpipe\s+organ\b|\btubipora\b", re.I)),
    ("sps",      re.compile(r"\bsps\b|\bacropora\b|\bmontipora\b|\bstylophora\b|\bseriatopora\b|\bpocillopora\b|\bmonti|\bacro\b|\bmilli\b|\bmillie|\bmillepora\b|\bdigi\b|\bdigitata\b|\bstylo|\banacro|\bpsamm[oa]cora\b|\bstag(?:horn)?\b|\bbirds?\s*nest\b", re.I)),
    ("lps",      re.compile(r"\blps\b|\beuphyllia\b|\btorch\b|\bhammer\b|\bfrogspawn\b|\bacanthophyllia\b|\btrachyphyllias?\b|\bcynarina\b|\bsymphyllia\b|\bfavia\b|\bfavites\b|\bmicromussa\b|\bacan\b|\bacantho|\bblasto|\bduncan|\blobo|\bscoly|\bpectinia\b|\bpectina\b|\bfungia|\bbowerbanki\b|\bgoni|\balveopora\b|\bgalaxea\b|\belegance\b|\baustralomussa\b|\bleptoseris\b|\bleptastrea\b|\bcyphastrea\b|\bcaulastrea\b|\bcandy\s+cane\b|\blithophyllon\b|\blitho\b|\bindophyllia\b|\btrumpet\b|\bbubble\s+coral\b|\bdiaseris\b|\bplate\s+coral\b|\bhydnophora\b|\bhydno\b|\bastreopora\b", re.I)),
    ("fish",     re.compile(r"\bfish\b|\bwrasse\b|\btang\b|\bgoby\b|\bclownfish\b|\bblenny\b", re.I)),
    ("invert",   re.compile(r"\bsnails?\b|\bshrimp\b|\bcrabs?\b|\burchin\b|\bstarfish\b|\bcucumber\b", re.I)),
    ("equipment",re.compile(r"\bpumps?\b|\bskimmers?\b|\breactors?\b|\bheaters?\b|\bcontrollers?\b|\bfilters?\b", re.I)),
)


# CTK-189 reverse-precision guard. The CATEGORY_PATTERNS above match a coral
# category whenever a coral WORD appears in product_type/tags/title — but a
# non-coral product can carry a coral word ("Marine Anemone Pellets", "Rio
# Precision SPS Coral Clipper", "Bejeweled Favites Sticker", "Salinity Probe
# Stability Kit (SPS)"). Those mis-tag into a coral category, and the CTK-186
# step-2 feed exclusion (category IS DISTINCT FROM 'equipment') can't touch a
# coral-tagged row. This is the reverse of CTK-186's direction (which fixed
# corals mis-tagged equipment/fish); CTK-186 cannot reach it.
#
# Guard: when a coral-category pattern wins AND the TITLE carries a non-coral
# marker, reroute to 'equipment' so the feed exclusion drops it. 'equipment'
# is the established "non-livestock, exclude-from-feed" bucket (deliberately
# overloaded — a coral-food/sticker row reading 'equipment' is CORRECT, not a
# bug to fix later; a dedicated 'food' enum would need a migration + a CTK-186
# exclusion-set addition, over-engineering at this tier).
#
# Marker set finalized against the live catalog (CTK-189 FP check 2026-06-23):
#   - TITLE-scoped only — a coral whose vendor TAGS carry "kit" must not flip.
#   - bare 'food' DROPPED: it false-matched only real corals (Battle Corals'
#     whimsical names "Fairy Food", "...trying to steal my food") and 0 real
#     food products — every real food item carries 'pellet'. Replaced by the
#     phrase 'coral food' (0 coral-categoried FPs; forward-insurance for a
#     future "X Coral Food" that lacks 'pellet').
#   - 'pellet' uses a TRAILING boundary only (`pellets?\b`, no leading \b) so
#     it catches the brand portmanteau "Benepellet" (Benepets fish-food) where
#     a full `\bpellet\b` would miss it — substring-pellet is FP-safe (0/237
#     matched corals). The other markers keep BOTH boundaries: a leading-loose
#     "kit" would false-fire on real coral names ("S[kit]tles").
#   - FP check (final set): 0/237 matched corals (named_coral_id NOT NULL)
#     carry a marker; all coral-categoried reroutes are genuinely non-coral.
_CORAL_CATEGORIES = frozenset(
    {"sps", "lps", "softie", "zoa", "mushroom", "anemone", "clam", "chalice"}
)
_NONCORAL_TITLE_MARKERS = re.compile(
    r"\b(?:sticker|kit|probe|clipper|cartridge|earrings)s?\b"
    r"|pellets?\b"
    r"|\bcoral\s+foods?\b",
    re.I,
)


def normalize_title(raw_title: str, originator_prefix: str | None = None) -> str:
    """Lowercase + unaccent + whitespace-collapse + strip trailing junk.
    Vendor prefix PRESERVED per decision #18 (§3.2 cascade fix); the matcher
    cascade depends on the prefix being present in normalized_title.

    The originator_prefix param is YAML-config (decision #23) — currently unused
    in normalize because the matcher (§3.4 stage 3) prepends it at match time
    rather than burning it into normalized_title. Param stays in the signature
    so the call shape doesn't change if matcher integration ever wants to push
    prefix-handling here instead.
    """
    if not raw_title:
        return ""
    s = raw_title.lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    # Run strip patterns to convergence — multiple trailing tokens (price + SKU
    # + stock verb) can stack, and each pattern is end-anchored, so a single
    # pass over the list strips only the outermost token. Loop until stable.
    while True:
        before = s
        for pat in _STRIP_PATTERNS:
            s = pat.sub("", s).rstrip()
        if s == before:
            break
    s = _WHITESPACE_RUN.sub(" ", s).strip()
    return s


def coerce_price(variants: list[dict]) -> Decimal | None:
    """Pull the first non-empty price from variants as Decimal. Nullable per
    arch §1.4 — price-on-request (JF event drops, TSA cut-to-order) is the
    null state. Shopify prices are dollar-denominated strings ('45.00')."""
    for v in variants:
        price = v.get("price")
        if price in (None, "", "0.00"):
            continue
        try:
            return Decimal(str(price))
        except InvalidOperation:
            continue
    return None


def coerce_compare_at_price(variants: list[dict], current_price: Decimal | None) -> Decimal | None:
    """CTK-100: read the compare_at_price of the SAME variant whose price
    coerce_price would have chosen as current_price. Pair-discipline —
    variant[i]'s compare_at is consulted only when variant[i] is also the
    one whose price became current_price.

    Returns None on:
      - current_price is None (price-on-request OR auction null-out per L4
        structural carve-out — INV-05 writer-side obligation #1)
      - chosen variant's compare_at_price missing / empty / '0.00'
      - chosen variant's compare_at_price unparseable / NaN / Infinity
      - chosen variant's compare_at_price <= current_price (L2 stale; vendors
        forget to clear compare_at after a sale ends, so any non-strictly-
        greater value is treated as stale)
      - all variants have empty/unparseable price (coerce_price would also
        return None; nothing to pair against)

    /code-review F1 (Wave-1.5 fold 2026-06-01): pre-fix the helper walked
    ALL variants looking for any non-empty compare_at, which on multi-
    variant frags would pair variant[1]'s compare_at with variant[0]'s
    price ("phantom markdown"). The walk now mirrors coerce_price's:
    first non-empty/parseable price wins; THAT variant's compare_at is
    the only one consulted. Single-variant rows are unaffected.

    /code-review F2 (same fold): explicit is_finite() guard catches NaN
    / Infinity / -Infinity which Decimal(str(...)) accepts but
    Decimal-comparison raises InvalidOperation on, taking out the whole
    scrape.

    /code-review F3 (same fold): the "early-return drops later valid
    variants" hazard structurally dissolves under F1 — only the chosen
    variant is consulted; "later valid variants" no longer exist as a
    category.

    /code-review F15 (Wave-2 fold 2026-06-01): numeric(10,2) parse-side
    clamp. Without the clamp, a vendor typo (compare_at_price field
    set to '99999999999.99' — billion-dollar misclick) parses as a
    finite Decimal, passes the L2 > current_price gate, and writes to
    the numeric(10,2) column which raises NumericValueOutOfRange
    mid-batch — taking out the whole scrape. The clamp returns None on
    values that won't fit numeric(10,2) (max = 99999999.99; boundary
    sits at 10^8 = Decimal("100000000")). Same predicate mirrored at
    the BC and Magento helpers (parse_bigcommerce._extract_compare_at_price,
    tidal_gardens._extract_compare_at_price) for single-semantic
    coverage across all three platforms.
    """
    if current_price is None:
        return None
    for v in variants:
        price = v.get("price")
        if price in (None, "", "0.00"):
            continue
        try:
            Decimal(str(price))
        except InvalidOperation:
            continue
        # Chosen variant — its compare_at is the only one we consult.
        compare_at = v.get("compare_at_price")
        if compare_at in (None, "", "0.00"):
            return None
        try:
            value = Decimal(str(compare_at))
        except InvalidOperation:
            return None
        if not value.is_finite():
            return None
        if value >= Decimal("100000000"):
            return None
        if value > current_price:
            return value
        # L2 stale: compare_at <= current_price (vendor forgot to clear
        # post-sale, or no markdown at all). Null out.
        return None
    return None


def infer_category(product: dict) -> str | None:
    """Match against product_type + tags + title via _CATEGORY_PATTERNS. Returns
    a string from the arch §1.4 vendor_listings.category CHECK enum, or None
    if no pattern hits — the column accepts NULL for unknown."""
    haystack_parts = [
        product.get("product_type") or "",
        " ".join(product.get("tags") or []) if isinstance(product.get("tags"), list) else (product.get("tags") or ""),
        product.get("title") or "",
    ]
    haystack = " ".join(haystack_parts)
    title = product.get("title") or ""
    for label, pat in _CATEGORY_PATTERNS:
        if pat.search(haystack):
            # CTK-189 reverse-precision guard — surgical: only intervene when a
            # CORAL pattern wins AND the TITLE carries a non-coral marker. Every
            # other path (non-coral matches, clean coral matches, NULL) is
            # untouched, so blast radius is exactly the coral-tagged-non-coral
            # failure mode and nothing else.
            if label in _CORAL_CATEGORIES and _NONCORAL_TITLE_MARKERS.search(title):
                return "equipment"
            return label
    return None


def infer_lineage_flag(raw_title: str) -> str:
    """vendor_listings.lineage_flag default value — the SCRAPER's heuristic
    guess at lineage shape. Distinct from match_confidence (matcher's verdict).
    Phase 1 PE shakedown: heuristic is intentionally simple — title with
    title-case proper-noun pairs (e.g. "Holy Grail") flips to vendor-named.
    Cheap signal; the §3 matcher does the real work later."""
    if not raw_title:
        return "unknown"
    # Only fire on the strongest Phase 1 signal: a 2-4 char ALL-CAPS prefix
    # ("JF" / "WWC" / "TSA" / "ECC" / "ORA") followed by a title-cased token.
    # Generic title-cased pairs ("Coral Colony", "Acanthophyllia Rainbow")
    # are too noisy — they false-positive on every PE descriptor title and
    # don't carry lineage signal. The §3 matcher does the real work; this
    # column is just a hint about which titles to prioritize.
    if re.search(r"^[A-Z]{2,4}\s+[A-Z][a-z]+", raw_title):
        return "vendor-named"
    return "unknown"
