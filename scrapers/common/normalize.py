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
_CATEGORY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("chalice",  re.compile(r"\bchalices?\b|\bechinophyllia\b|\bmycedium\b|\boxypora\b", re.I)),
    ("anemone",  re.compile(r"\banemones?\b|\bbta\b|\brbta\b|\bcondy\b", re.I)),
    ("clam",     re.compile(r"\bclams?\b|\btridacna\b", re.I)),
    ("mushroom", re.compile(r"\bmushrooms?\b|\brhodactis\b|\bdiscosoma\b|\bricordea\b", re.I)),
    ("zoa",      re.compile(r"\bzoa(?:nthid)?s?\b|\bpaly", re.I)),
    ("softie",   re.compile(r"\bsofties?\b|\bsofty\b|\bleather\b|\btoadstool\b|\bkenya\b|\bsinularia\b|\bsarcophyton\b", re.I)),
    ("sps",      re.compile(r"\bsps\b|\bacropora\b|\bmontipora\b|\bstylophora\b|\bseriatopora\b|\bpocillopora\b", re.I)),
    ("lps",      re.compile(r"\blps\b|\beuphyllia\b|\btorch\b|\bhammer\b|\bfrogspawn\b|\bacanthophyllia\b|\btrachyphyllias?\b|\bcynarina\b|\bsymphyllia\b|\bfavia\b|\bfavites\b|\bmicromussa\b|\bacan\b", re.I)),
    ("fish",     re.compile(r"\bfish\b|\bwrasse\b|\btang\b|\bgoby\b|\bclownfish\b|\bblenny\b", re.I)),
    ("invert",   re.compile(r"\bsnails?\b|\bshrimp\b|\bcrabs?\b|\burchin\b|\bstarfish\b|\bcucumber\b", re.I)),
    ("equipment",re.compile(r"\bpumps?\b|\bskimmers?\b|\breactors?\b|\bheaters?\b|\bcontrollers?\b|\bfilters?\b", re.I)),
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
    for label, pat in _CATEGORY_PATTERNS:
        if pat.search(haystack):
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
