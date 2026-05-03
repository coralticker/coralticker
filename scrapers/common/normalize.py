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
_CATEGORY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("chalice",  re.compile(r"\bchalice|echinophyllia|mycedium|oxypora\b", re.I)),
    ("anemone",  re.compile(r"\banemone|bta|rbta|condy\b", re.I)),
    ("clam",     re.compile(r"\bclam\b|tridacna", re.I)),
    ("mushroom", re.compile(r"\bmushroom|rhodactis|discosoma|ricordea\b", re.I)),
    ("zoa",      re.compile(r"\bzoa(?:nthid)?s?\b|paly", re.I)),
    ("softie",   re.compile(r"\bsoftie|softy|leather|toadstool|kenya|sinularia|sarcophyton\b", re.I)),
    ("sps",      re.compile(r"\bsps\b|acropora|montipora|stylophora|seriatopora|pocillopora", re.I)),
    ("lps",      re.compile(r"\blps\b|euphyllia|torch|hammer|frogspawn|acanthophyllia|trachyphyllia|cynarina|symphyllia|favia|favites|micromussa|acan\b", re.I)),
    ("fish",     re.compile(r"\bfish|wrasse|tang|goby|clownfish|blenny\b", re.I)),
    ("invert",   re.compile(r"\bsnail|shrimp|crab|urchin|starfish|cucumber\b", re.I)),
    ("equipment",re.compile(r"\bpump|skimmer|reactor|heater|controller|filter\b", re.I)),
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
