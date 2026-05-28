"""Shopify /products.json parser. Iterates pages, yields normalized item
dicts in the shape diff.py expects. Computes html_hash per arch §2.6
(Shopify variant: hash sorted key set of first product object) — F5 fold
verified at write time below.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass

from scrapers.common import http, normalize

log = logging.getLogger(__name__)


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
    in_stock_only = bool(config.get("in_stock_only", False))  # CTK-088: POTO live-sale archive — keep only buyable; default False = fleet behavior

    items: list[dict] = []
    skipped = 0
    html_hash: str | None = None
    http_status_last: int | None = None

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
                skipped += 1
                continue
            items.append(_normalize_product(p, base_url, image_strategy, originator_prefix, auction_detection))

        if len(products) < page_size:
            # Short page = last page. Spares one wasted round-trip.
            break

    if category_filter:
        log.info("category_filter: kept %d, skipped %d products", len(items), skipped)
    elif in_stock_only:
        # CTK-088: distinct log line keeps the existing category_filter output
        # byte-identical for the 9 prior vendors (none set in_stock_only).
        log.info("in_stock_only: kept %d, skipped %d products", len(items), skipped)

    return ParseResult(items=items, html_hash=html_hash, http_status_last=http_status_last)


def _should_keep(product: dict, category_filter: dict | None, in_stock_only: bool = False) -> bool:
    """CTK-037 category-filter gate. Returns True if product passes; False if
    rejected by the availability gate, the allowlist, or the tag-denylist.
    None or empty dict category_filter = no category gate (permissive default
    for Phase 2 vendor onboarding inheritance).

    Four filter axes, AND-semantics when more than one is configured:
      - in_stock_only (CTK-088) — when True, drop any product with no buyable
        variant (`not any(v.available ...)`). Opt-in per-vendor (default False
        = fleet behavior). For vendors whose catalog is a permanent archive of
        mostly sold-out items (POTO live-sale archive: ~3,500 published / ~21-41
        buyable), this keeps only currently-buyable inventory out of the diff.
        Checked FIRST + independent of category_filter — it gates POTO, which
        carries no category_filter (coral-pure catalog).
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
        if in_stock_only:
            # CTK-088 fold: under in_stock_only, reaching this point means the
            # product is BUYABLE (it passed the availability gate above) but its
            # product_type isn't in the allowlist — i.e., a buyable item is being
            # dropped. For POTO this surfaces an additive product_type bucket the
            # allowlist silently misses (the listings_seen canary can't catch a
            # new-bucket drop). Converts silent-miss to a visible WARN.
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
