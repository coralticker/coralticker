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
    no retry. Orchestrator catches + records error_class='html_schema_change'."""


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
    # CTK-094 fold #4 (/code-review F4): URLs the parser actively rejected
    # via YAML filter (in_stock_only sold-out drop, product_type_allowlist
    # mismatch, tag_denylist match, tag_allowlist miss). diff.classify
    # excludes these from the cohort-OOS absent-set so a parser-filter
    # rejection (vendor re-categorized item to a non-allowlisted bucket)
    # doesn't conflate with vendor-sold-out. parse_bigcommerce +
    # tidal_gardens return empty set (no filter axis today; plumbing
    # exists for future filter additions on those platforms).
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
    filtered_urls: set[str] = set()  # CTK-094 fold #4: URLs rejected by _should_keep, excluded from cohort absent-set
    html_hash: str | None = None
    http_status_last: int | None = None
    pages_fetched = 0        # CTK-094 §4.2 completeness signal — increment per fetched page

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
                    skipped_category += 1
                    # CTK-094 fold #4 + Session 4 fold #1: scope-gated to
                    # category-rejection only. URL shape matches
                    # _normalize_product (base_url + /products/handle).
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
            "filter: kept %d, skipped %d (unavailable %d, category-filter %d)",
            len(items), skipped_unavailable + skipped_category,
            skipped_unavailable, skipped_category,
        )

    return ParseResult(
        items=items,
        html_hash=html_hash,
        http_status_last=http_status_last,
        pages_fetched=pages_fetched,
        per_category_counts={},  # Shopify single-endpoint — no category axis
        filtered_urls=filtered_urls,
    )


def _should_keep(product: dict, category_filter: dict | None, in_stock_only: bool = False) -> bool:
    """CTK-037 category-filter gate. Returns True if product passes; False if
    rejected by the availability gate, the allowlist, or the tag-denylist.
    None or empty dict category_filter = no category gate (permissive default
    for Phase 2 vendor onboarding inheritance).

    Four filter axes, AND-semantics when more than one is configured:
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
        every coral row tagged 'Coral').
      - tag_denylist (CTK-041) — no product tag may appear in the list.

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
    if tag_allowlist and not any(t in tag_allowlist for t in tags):
        return False
    if tag_denylist and any(t in tag_denylist for t in tags):
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

    images = product.get("images") or []
    vendor_image_url = images[0].get("src") if images else None

    return {
        "raw_title": raw_title,
        "normalized_title": normalize.normalize_title(raw_title, originator_prefix=originator_prefix),
        "product_url": product_url,
        "vendor_sku": sku,
        "current_price": current_price,
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
