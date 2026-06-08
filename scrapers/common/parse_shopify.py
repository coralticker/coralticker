"""Shopify /products.json parser. Iterates pages, yields normalized item
dicts in the shape diff.py expects. Computes html_hash per arch §2.6
(Shopify variant: hash sorted key set of first product object) — F5 fold
verified at write time below.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field

from scrapers.common import http, normalize

log = logging.getLogger(__name__)

# CTK-088 fold #3: product_types that the POTO allowlist deliberately excludes.
# A buyable item dropped for one of these is an EXPECTED drop (merch / gift
# card / addon / auction), not a new-bucket miss — so it must NOT raise the
# new-bucket WARN. The aggregate skip-count (fetch_and_parse) still tallies it.
# Auctions are ReefnBid's contract (CTK-007), never POTO Shopify coral.
_KNOWN_EXCLUDED_PRODUCT_TYPES = frozenset({"merch", "Gift Card", "addon", "auction"})

_TRUE_STRINGS = frozenset({"true", "1", "yes", "on"})


def _coerce_bool(value) -> bool:
    """CTK-088 fold #10: coerce a config value to bool WITHOUT the
    bool('false') == True footgun. A YAML scalar quoted as "false" loads as
    the string 'false', and bare bool('false') is True — which would silently
    flip in_stock_only on. Real bools pass through; recognized string spellings
    map by value; everything else falls back to truthiness.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in _TRUE_STRINGS
    return bool(value)


class SchemaChangeError(Exception):
    """Shopify /products.json returned a shape we don't recognize. Per arch §2.4
    schema-change row: best-effort persist whatever parsed; status='partial';
    no retry. Orchestrator catches + records error_class='html_schema_change'.

    CTK-094 Session 5 fold #2 (/code-review F2): optional `result` kwarg carries
    a partial ParseResult on marker-broken escalation (parse_bigcommerce.py
    fold #3 escalates from PartialCategoryWarning to SchemaChangeError when the
    silent-zero count breaches threshold). The carrier shape mirrors
    PartialCategoryWarning — orchestrator catches in the parser try-block,
    extracts result, persists the healthy-categories' items, and finalizes
    status='partial' rather than dropping the harvest. Absent result kwarg
    preserves the original semantic — orchestrator outer-except catches and
    finalizes status='partial' with no persist (no items to save anyway, the
    raise interrupted parse before items existed)."""
    def __init__(self, message: str, *, result: "ParseResult | None" = None):
        super().__init__(message)
        self.result = result


class BlockedError(Exception):
    """http.fetch returned error_class='block'. NO retry per arch §2.4."""


class FetchError(RuntimeError):
    """http.fetch returned a non-success, non-block error_class (network /
    http_429 / http_5xx / other). Orchestrator catches + records the typed
    error_class on scraper_runs without sniffing strings."""

    def __init__(self, error_class: str, message: str) -> None:
        super().__init__(message)
        self.error_class = error_class


@dataclass
class ParseResult:
    items: list[dict]
    html_hash: str | None
    http_status_last: int | None
    # CTK-094 §4.2 completeness signal source — every parser populates this
    # with the count of pages actually fetched (Shopify /products.json
    # pagination, BC Stencil category_paths cross-product, Magento ?p=N).
    # None only on the early-exit / never-fetched paths so the field is
    # never load-bearing without a successful fetch.
    pages_fetched: int | None = None
    # CTK-094 §5.2 category-cohort signal — populated by parsers that loop
    # over category_paths AND have category_cohort_signal:true in YAML
    # (AquaSD BC Stencil at v1). Default {} keeps the contract platform-
    # agnostic: parse_shopify writes {} (no category axis), tidal_gardens
    # writes {} (enumerated genus subpaths are coverage-filter, not partial-
    # cohort surface), parse_bigcommerce writes the populated dict only
    # when the YAML opt-in fires. NOTE per /code-review F7+F13: counts are
    # PRE-overlap-dedup raw card counts, not post-dedup unique listings.
    # Vendors with category overlap (AquaSD /softies/ ∩ /zoanthids/ ~57
    # cards) will see sum(per_category_counts.values()) > len(items).
    # Downstream consumers (CTK-097 operator alerting) MUST treat these as
    # raw-card-per-path observability, not unique-product-per-category.
    per_category_counts: dict = field(default_factory=dict)
    # CTK-094 fold #4 (/code-review F4) + CTK-096 close-fold F9 2026-06-01:
    # URLs the parser actively rejected via YAML filter (in_stock_only sold-
    # out drop, product_type_allowlist mismatch, tag_allowlist miss,
    # tag_denylist match, title_denylist / title_denylist_prefix match
    # (CTK-119)). diff.classify excludes these
    # from the cohort-OOS absent-set so a parser-filter rejection (vendor
    # re-categorized item to a non-allowlisted bucket, vendor renamed item
    # to hit a title-denylist substring) doesn't conflate with vendor-sold-
    # out. parse_bigcommerce + tidal_gardens return empty set (no filter
    # axis today; plumbing exists for future filter additions on those
    # platforms).
    filtered_urls: set = field(default_factory=set)


def fetch_and_parse(config: dict) -> ParseResult:
    """Fetch all pages from base_url + products_path, normalize, return items
    + the §2.6 html_hash sentinel + last HTTP status for scraper_runs."""
    base_url = config["base_url"].rstrip("/")
    products_path = config.get("products_path", "/products.json")
    page_size = int(config.get("page_size", 250))
    max_pages = int(config.get("max_pages", 30))
    delay = float(config.get("request_delay_sec", 2.0))
    originator_prefix = config.get("originator_prefix")  # null or string per decision #23
    image_strategy = config.get("image_strategy", "mirror")
    category_filter = config.get("category_filter")  # CTK-037: None or {} = no gate (permissive default)
    auction_detection = config.get("auction_detection")  # CTK-041: None = no-op (permissive default; WWC only at ship)
    in_stock_only = _coerce_bool(config.get("in_stock_only", False))  # CTK-088: POTO live-sale archive — keep only buyable; default False = fleet behavior

    items: list[dict] = []
    skipped_unavailable = 0  # CTK-088 fold #4: dropped by the in_stock_only availability gate
    skipped_category = 0     # CTK-088 fold #4: dropped by product_type_allowlist / tag_allowlist / tag_denylist
    skipped_title_denylist = 0  # CTK-096 D-1: dropped by title_denylist axis (split out from skipped_category so an operator can tell which YAML axis catches the row); CTK-119 prefix-axis drops share this counter (same title-axis bucket)
    filtered_urls: set[str] = set()  # CTK-094 fold #4: URLs rejected by _should_keep, excluded from cohort absent-set
    html_hash: str | None = None
    http_status_last: int | None = None
    pages_fetched = 0        # CTK-094 §4.2 completeness signal — increment per fetched page

    # CTK-096 D-1: hoist title_denylist out of the per-product loop so we don't
    # re-read the dict on every iteration. Used at the call-site attribution
    # below to discriminate skipped_title_denylist from skipped_category.
    title_denylist_lower = [
        e.lower() for e in ((category_filter or {}).get("title_denylist") or [])
    ]
    # CTK-119 D-1: hoist the anchored-prefix entries alongside, as a tuple so
    # the attribution branch below can hand it straight to str.startswith.
    title_denylist_prefix_lower = tuple(
        e.lower() for e in ((category_filter or {}).get("title_denylist_prefix") or [])
    )
    # CTK-096 close-fold F5 2026-06-01: hoist tag_denylist as a lowercased set
    # at fetch_and_parse scope too — needed at the call-site attribution to
    # detect the dual-hit case (tag_denylist + title_denylist both match the
    # same product, intentional UC belt-and-suspenders overlap on Dalua /
    # Illumagic / Panta Rhei per unique_corals.yaml). Pre-fold the attribution
    # branch checked title_denylist first and over-counted skipped_title_denylist
    # by ~70 rows per UC scrape — see F5 disposition below.
    tag_denylist_lower = {
        e.lower() for e in ((category_filter or {}).get("tag_denylist") or [])
    }

    for page in range(1, max_pages + 1):
        url = f"{base_url}{products_path}?limit={page_size}&page={page}"
        result = http.fetch(url, request_delay_sec=delay)
        http_status_last = result.status_code

        if result.error_class == "block":
            raise BlockedError(result.error_message or "block detected")
        if result.error_class is not None:
            # network / 429 / 5xx / other — bubble up as a structured exception so
            # the orchestrator can record the right error_class without re-mapping.
            raise _to_exception(result)

        pages_fetched += 1  # CTK-094 §4.2 — count after success, not after attempt

        try:
            payload = json.loads(result.body)
        except json.JSONDecodeError as e:
            raise SchemaChangeError(f"page {page}: JSON decode failed: {e}") from e

        products = payload.get("products")
        if products is None:
            raise SchemaChangeError(f"page {page}: response missing 'products' key")

        if not products:
            # Empty page — natural pagination terminator.
            break

        # F5 fold — html_hash anchor on FIRST page's FIRST product.
        # Per arch §2.6 Shopify variant: hash sorted key set of first product
        # JSON object. Sort BEFORE hash — Shopify can change JSON key emission
        # order across versions without a real schema change; sorting collapses
        # ordering noise. The hash flips ONLY when keys are added/removed.
        if page == 1:
            keys = sorted(products[0].keys())
            html_hash = hashlib.sha256(",".join(keys).encode("utf-8")).hexdigest()

        # CTK-037: iteration-site category-filter pre-_normalize_product. Rejected
        # products never enter parse → diff → Phase A → Phase B. Skip-count
        # accumulated across pages and logged at parse-end below. Permissive
        # default — config without category_filter block bypasses the gate.
        for p in products:
            if not _should_keep(p, category_filter, in_stock_only):
                # CTK-088 fold #4: attribute the drop. An unavailable item is
                # short-circuited by the availability gate FIRST, so under
                # in_stock_only any sold-out row is an availability drop; a
                # buyable row that still got dropped failed the category filter.
                # CTK-094 Session 4 fold #1 (/code-review F1): filtered_urls
                # only collects category-rejected URLs (vendor still buyable).
                # Sold-out rejects (skipped_unavailable) ARE the cohort-OOS
                # signal — they must NOT enter filtered_urls or diff.classify
                # will exclude them from the cohort absent-set and the in_stock
                # row stays TRUE despite the vendor selling out (Session 3
                # fold-batch regressed this for the POTO in_stock_only + cohort
                # combo; Session 4 restores the discrimination).
                if in_stock_only and not any(v.get("available") for v in (p.get("variants") or [])):
                    skipped_unavailable += 1
                else:
                    # CTK-096 close-fold F5 2026-06-01: attribute the drop to
                    # the FIRST-firing axis per _should_keep's short-circuit
                    # order (in_stock_only > allowlist > tag_allowlist >
                    # tag_denylist > title_denylist). The DOMINANT mis-
                    # attribution class fixed here is the tag_denylist +
                    # title_denylist dual-hit (intentional UC belt-and-
                    # suspenders overlap on Dalua / Illumagic / Panta Rhei —
                    # ~70 rows per UC scrape): tag_denylist fires first in
                    # _should_keep, so attribution must go to skipped_
                    # category. The check below mirrors that axis order:
                    # tag_denylist re-check first; if it would have fired,
                    # attribute to category. Otherwise fall through to the
                    # title_denylist check.
                    #
                    # SCOPE LIMITATION: allowlist-rejected + title-coincidence
                    # still attributes to skipped_title_denylist (the
                    # title-hit elif fires). Not corrected here — would
                    # require re-checking product_type_allowlist + tag_
                    # allowlist + axis-order-flag from _should_keep. UC's
                    # equipment-row class is dominated by tag-hits so the
                    # residue is small; if a future audit shows the residue
                    # matters, evolve _should_keep to return a tagged-reason
                    # enum (altitude-correct fix).
                    tags_lower = [(t or "").lower() for t in (p.get("tags") or [])]
                    tag_denylist_hit = bool(tag_denylist_lower) and any(
                        t in tag_denylist_lower for t in tags_lower
                    )
                    if tag_denylist_hit:
                        skipped_category += 1
                    elif title_denylist_lower and any(
                        e in (p.get("title") or "").lower() for e in title_denylist_lower
                    ):
                        skipped_title_denylist += 1
                    elif title_denylist_prefix_lower and (
                        (p.get("title") or "").lower().startswith(title_denylist_prefix_lower)
                    ):
                        # CTK-119 D-1: anchored-prefix axis shares the title-
                        # axis counter. Mirrors _should_keep's axis order
                        # (substring before prefix) so a dual-hit attributes
                        # to the substring branch above, same as the gate.
                        skipped_title_denylist += 1
                    else:
                        skipped_category += 1
                    # CTK-094 fold #4 + Session 4 fold #1: scope-gated to
                    # category-rejection only. URL shape matches
                    # _normalize_product (base_url + /products/handle).
                    # CTK-096 note: title_denylist drops also enter filtered_urls
                    # (parser-active rejection on a buyable row; same cohort-
                    # OOS exclusion contract as category-axis drops — a vendor
                    # renaming a buyable item to hit title_denylist would
                    # otherwise mass-fire false OOS).
                    handle = p.get("handle", "")
                    if handle:
                        filtered_urls.add(f"{base_url}/products/{handle}")
                continue
            items.append(_normalize_product(p, base_url, image_strategy, originator_prefix, auction_detection))

        if len(products) < page_size:
            # Short page = last page. Spares one wasted round-trip.
            break

    # CTK-088 fold #4: split the skip-count so an operator can't read a large
    # "skipped" total and blame the allowlist — POTO drops ~5,300 rows on
    # availability and only a handful on the category filter.
    if category_filter or in_stock_only:
        log.info(
            "filter: kept %d, skipped %d (unavailable %d, category-filter %d, title-denylist %d)",
            len(items), skipped_unavailable + skipped_category + skipped_title_denylist,
            skipped_unavailable, skipped_category, skipped_title_denylist,
        )

    return ParseResult(
        items=items,
        html_hash=html_hash,
        http_status_last=http_status_last,
        pages_fetched=pages_fetched,
        per_category_counts={},  # Shopify single-endpoint — no category axis
        filtered_urls=filtered_urls,
    )


def _normalize_tag(value: str) -> str:
    """CTK-117 Arm 2 — tolerant tag normalization for tag_denylist membership.
    Folds the label-shape variants TSA emits on the reef-safety rating family
    that exact lowercased membership missed (CTK-104 close /code-review #5):
    hyphen-vs-space (`Reef-Safe` vs `Reef Safe`), leading/trailing whitespace,
    and internal whitespace runs. Applied to BOTH sides of the membership test
    so a vendor tag-shape drift (`Reef-Safe`) matches a `Reef Safe` denylist
    entry — symmetric, so every pre-existing exact match still matches (same
    transform both sides; no entry that matched before stops matching).

    Scope note: full-phrase variants that are NOT punctuation/whitespace-
    equivalent (e.g. `Reef Safe with Caution` — a distinct phrase, not a
    spacing variant of `Reef Safe`) are out of this fold's reach by design;
    they are covered by an explicit YAML denylist entry so membership stays
    exact-match and no substring/prefix matching is introduced (substring
    matching on the denylist would collide fleet-wide). Applied to the
    tag_denylist axis only — tag_allowlist keeps the CTK-096 D-2 lowercase
    membership untouched (normalizing the allowlist would only widen it, and
    it's out of this ticket's scope)."""
    return " ".join(value.lower().replace("-", " ").split())


def _should_keep(product: dict, category_filter: dict | None, in_stock_only: bool = False) -> bool:
    """CTK-037 category-filter gate. Returns True if product passes; False if
    rejected by the availability gate, the allowlist, the tag-denylist, or the
    title-denylist. None or empty dict category_filter = no category gate
    (permissive default for Phase 2 vendor onboarding inheritance).

    Six filter axes, AND-semantics when more than one is configured:
      - in_stock_only (CTK-088) — when True, drop any product with no buyable
        variant (`not any(v.available ...)`). Opt-in per-vendor (default False
        = fleet behavior). For vendors whose catalog is a permanent archive of
        mostly sold-out items (POTO live-sale archive: ~5,466 published / ~164
        buyable / 159 kept after the filter), this keeps only currently-buyable
        inventory out of the diff. Checked FIRST + short-circuits before the
        category gate.
      - product_type_allowlist (CTK-037 Q-B lock) — product_type must be in the
        list. Skipped when unset.
      - tag_allowlist (CTK-086 Q-4) — at least one product tag must intersect
        the list. Skipped when unset. Use for vendors whose taxonomy lives in
        tags rather than product_type (Reef Chasers: product_type='' universal,
        every coral row tagged 'Coral'). Membership is lowercase-runtime per
        CTK-096 D-2 symmetric extension (close-fold F2 2026-05-31) so a vendor's
        tag-shape drift between mixed-case and lowercase doesn't silently miss
        the entry — RC's `tag_allowlist: ['Coral']` is the sole coral signal
        for ~143 corals and an API drift to lowercase 'coral' would otherwise
        empty the catalog.
      - tag_denylist (CTK-041) — no product tag may appear in the list.
        Membership is lowercase-runtime per CTK-096 D-2 (both sides .lower()
        at the predicate) so a vendor's tag-shape drift between mixed-case
        and lowercase doesn't silently miss the entry — YAML stays mixed-
        case readable.
      - title_denylist (CTK-096) — no entry may appear as a case-insensitive
        substring of raw_title. Per CTK-096 D-1; closes the empty-tag +
        permissive-PT bypass class on JF / BC / UC + the tagged-but-not-
        denylisted equipment-brand class on UC. Each entry is matched as
        `entry.lower() in title.lower()`; compound substrings preferred
        over single-word when coral-noun collision is possible (e.g., JF
        uses `Hybrid Tang` not `Tang` — `Tang` would false-fire on the
        Tangerine/Tango/Tangelo coral lineages).
      - title_denylist_prefix (CTK-119) — no entry may match raw_title as a
        case-insensitive PREFIX (`title.lower().startswith(entry.lower())`).
        Anchored variant of title_denylist for vendor channel-prefix
        conventions (WWC `WS - ` wholesale/live-sale SKUs: feed-published
        with dead retail routes). Use over a substring entry when the
        pattern could collide word-final inside coral names — substring
        `ws - ` would false-kill "Rainbows - ..." / "Jaws - ..."; the
        anchor kills exactly the title-initial class.

    Each axis short-circuits to False on miss; permissive when unset (so a
    config carrying only one axis behaves identically to the prior single-axis
    shape for that axis's consumers — in_stock_only default False keeps the 9
    pre-CTK-088 vendors byte-identical).
    """
    if in_stock_only:
        variants = product.get("variants") or []
        if not any(v.get("available") for v in variants):
            return False
    if not category_filter:
        return True
    allowlist = category_filter.get("product_type_allowlist") or []
    tag_allowlist = category_filter.get("tag_allowlist") or []
    tag_denylist = category_filter.get("tag_denylist") or []
    title_denylist = category_filter.get("title_denylist") or []
    title_denylist_prefix = category_filter.get("title_denylist_prefix") or []  # CTK-119: anchored variant
    product_type = product.get("product_type") or ""  # CTK-037 Session 5.5: normalize None/absent to "" so allowlist entry "" matches both shapes
    tags = product.get("tags") or []
    if allowlist and product_type not in allowlist:
        if in_stock_only and product_type not in _KNOWN_EXCLUDED_PRODUCT_TYPES:
            # CTK-088 fold #3: under in_stock_only, reaching this point means the
            # product is BUYABLE (it passed the availability gate above) but its
            # product_type isn't in the allowlist. WARN only when the bucket is
            # genuinely unknown — a NEW product_type the allowlist silently
            # misses (the listings_seen canary can't catch an additive bucket).
            # Buckets in _KNOWN_EXCLUDED_PRODUCT_TYPES (merch / Gift Card /
            # addon / auction) are EXPECTED drops; they stay silent here so the
            # WARN keeps its signal (the aggregate skip-count still tallies them).
            log.warning(
                "in_stock_only: buyable item dropped by product_type_allowlist "
                "(possible new bucket — check allowlist): product_type=%r title=%r",
                product_type, product.get("title"),
            )
        return False
    # CTK-096 D-2 symmetric extension (close-fold F2 2026-05-31): lowercase
    # both sides at membership for cross-fleet case-mismatch defense. Mirrors
    # the tag_denylist mitigation shape below. RC's load-bearing
    # `tag_allowlist: ['Coral']` would otherwise empty the catalog on an
    # API-side drift to lowercase 'coral'.
    #
    # CTK-096 close-fold F11 2026-06-01: hoist the lowercased allow/deny sets
    # ABOVE their any(...) generators. Pre-fold the set-comprehension
    # `{e.lower() for e in <list>}` lived inside the any(...) body, so Python
    # rebuilt it once per outer tag (O(tags × entries) lowers + per-tag set
    # allocation). Hoisted shape is O(entries + tags) lowers + one set
    # allocation per axis per call. Bounded today by ~10-13 entries × ~5 tags
    # × catalog-size — non-load-bearing perf, but the pre-fold comment
    # under-stated cost by a factor of ~5 (tags/row).
    if tag_allowlist:
        tag_allowlist_lc = {e.lower() for e in tag_allowlist}
        if not any(t.lower() in tag_allowlist_lc for t in tags):
            return False
    if tag_denylist:
        # CTK-117 Arm 2: normalize both sides via _normalize_tag (hyphen->space
        # + whitespace-collapse + lower) so reef-safety label-shape variants
        # (`Reef-Safe`, trailing whitespace) match their canonical denylist
        # entry. Symmetric — supersedes the CTK-096 D-2 lowercase-only
        # membership without dropping any prior match. Full-phrase variants
        # (`Reef Safe with Caution`) ride explicit YAML entries, not this fold.
        tag_denylist_norm = {_normalize_tag(e) for e in tag_denylist}
        if any(_normalize_tag(t) in tag_denylist_norm for t in tags):
            return False
    # CTK-096 D-1: 5th axis. Case-insensitive substring against raw_title.
    if title_denylist:
        title_lower = (product.get("title") or "").lower()
        if any(e.lower() in title_lower for e in title_denylist):
            return False
    # CTK-119 D-1: 6th axis. Case-insensitive ANCHORED prefix against raw_title
    # (lowercase-runtime both sides per the CTK-096 axis convention).
    if title_denylist_prefix:
        title_lower = (product.get("title") or "").lower()
        if title_lower.startswith(tuple(e.lower() for e in title_denylist_prefix)):
            return False
    return True


def _is_auction(product: dict, auction_detection: dict) -> bool:
    """CTK-041 auction detection. Tag-set match is primary; slug_suffix is a
    sanity log-warning to catch tag-shape drift (vendor drops the auction tag
    but keeps the URL pattern) without false-deny. Returns True iff tag-match
    fires; suffix-only matches log a warning and return False so a tag-shape
    regression surfaces in observability without silently re-pricing auctions.
    """
    auction_tags = set(auction_detection.get("tags") or [])
    slug_suffix = auction_detection.get("slug_suffix")
    product_tags = product.get("tags") or []
    tag_match = bool(auction_tags & set(product_tags))
    handle = product.get("handle", "")
    suffix_match = bool(slug_suffix and handle.endswith(slug_suffix))
    if suffix_match and not tag_match:
        log.warning(
            "auction slug_suffix=%s matched but no tag match (tag-shape drift?); handle=%s tags=%s",
            slug_suffix, handle, product_tags,
        )
    return tag_match


def _normalize_product(
    product: dict,
    base_url: str,
    image_strategy: str,
    originator_prefix: str | None,
    auction_detection: dict | None = None,
) -> dict:
    """Map a Shopify product dict to the diff.py + DB shape. Stage 4 (Normalize)
    of the arch §2.1 lifecycle — title/category/price/stock coercion happens here.

    product_url is built ABSOLUTE (base_url joined to /products/<handle>) so it
    matches the canonical key shape stored in vendor_listings.product_url. The
    diff.classify() lookup against existing_by_url + the persist_phase_a Phase B
    mirror-queue check both depend on this being absolute — relative URLs would
    miss the dict and force-classify every existing listing as 'new' on the
    next-day scrape (price_history explosion + redundant re-mirroring).

    CTK-041: when auction_detection config block is present and the product
    matches, current_price is null-out'd so the frontend renders "price on
    request" via formatPrice(null) instead of the Shopify variant placeholder.
    Permissive default — None = no-op (matches the category_filter shape).
    """
    raw_title = product.get("title", "")
    handle = product.get("handle", "")
    product_url = f"{base_url.rstrip('/')}/products/{handle}" if handle else ""

    variants = product.get("variants") or []
    in_stock = any(v.get("available") for v in variants)
    current_price = normalize.coerce_price(variants)
    sku = next((v.get("sku") for v in variants if v.get("sku")), None)

    if auction_detection and _is_auction(product, auction_detection):
        log.info("auction detected: %s — null-out current_price", handle)
        current_price = None

    # CTK-100 L4: sequence AFTER the auction null-out so compare_at_price
    # inherits the auction carve-out structurally — coerce_compare_at_price's
    # `current_price is None` guard returns None for auction rows regardless
    # of source DOM (matches INV-05 writer-side obligation #1: auction rows
    # never carry a vendor markdown).
    compare_at_price = normalize.coerce_compare_at_price(variants, current_price)

    images = product.get("images") or []
    vendor_image_url = images[0].get("src") if images else None

    return {
        "raw_title": raw_title,
        "normalized_title": normalize.normalize_title(raw_title, originator_prefix=originator_prefix),
        "product_url": product_url,
        "vendor_sku": sku,
        "current_price": current_price,
        "compare_at_price": compare_at_price,  # CTK-100: vendor-set markdown reference; NULL when no markdown / stale / auction
        "currency": "USD",                     # Phase 1 vendors all USD per Q1-3
        "in_stock": in_stock,
        "vendor_image_url": vendor_image_url,  # raw vendor URL; image-pipeline decides what becomes image_url
        "category": normalize.infer_category(product),
        "lineage_flag": normalize.infer_lineage_flag(raw_title),
    }


def _to_exception(result: http.FetchResult) -> FetchError:
    """Map an http.FetchResult error_class to a typed FetchError. Orchestrator
    catches FetchError and records error_class on scraper_runs; the named
    subclass replaces a runtime-attached attribute on a bare RuntimeError."""
    cls = result.error_class or "other"
    return FetchError(cls, f"{cls}: {result.error_message}")
