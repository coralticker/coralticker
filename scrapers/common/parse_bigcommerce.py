"""BigCommerce Stencil category-page parser. Iterates a per-vendor YAML
`category_paths` list × `?page=N` pagination, yields normalized item dicts
in the shape diff.py expects. Computes html_hash per arch §2.6 BC Stencil
variant (first li.product outer HTML with text + non-class attrs stripped —
theme-engine template-stable across BC Stencil stores).

Decision register row #66 (CTK-090): three-class platform model. This file
is the BigCommerce-Stencil-shared parser; AquaSD is the first consumer
(~30 LOC vendor module). Exception classes inherited from parse_shopify
(SchemaChangeError / BlockedError / FetchError) — no BC-specific
equivalents until a third platform class fires.
"""

from __future__ import annotations

import hashlib
import logging
import re
from decimal import Decimal, InvalidOperation

from bs4 import BeautifulSoup

from scrapers.common import http, normalize
from scrapers.common.errors import ConfigError
from scrapers.common.parse_shopify import (
    BlockedError,
    FetchError,
    ParseResult,
    SchemaChangeError,
)

log = logging.getLogger(__name__)


def fetch_and_parse(config: dict) -> ParseResult:
    """Iterate `category_paths` × `?page=N` until natural terminator (HTTP 404
    or empty card set). Returns ParseResult matching the parse_shopify shape
    so run.py dispatch can branch on platform without re-shaping downstream."""
    base_url = config["base_url"].rstrip("/")
    category_paths = config.get("category_paths") or []
    if not category_paths:
        # Config-side mistake (empty YAML field), not vendor-side schema drift.
        # ConfigError routes to error_class='config' so on-call investigates
        # the YAML, not the vendor (CTK-090 Session 4 /code-review finding #13).
        raise ConfigError("config.category_paths is empty — BC scrape requires at least one path")
    max_pages = int(config.get("max_pages", 30))
    delay = float(config.get("request_delay_sec", 2.0))
    auction_detection = config.get("auction_detection")
    originator_prefix = config.get("originator_prefix")
    # CTK-090 Session 4 finding #3: opt-in per-category min. Absent → no
    # check (current behavior); set → raise SchemaChangeError when any
    # single category produces fewer items than the threshold. Distinguishes
    # single-category schema drift (e.g., per-category template override
    # silently emptying /acropora/) from the all-categories-empty raise at
    # function bottom.
    expected_min_per_category = config.get("expected_min_per_category")

    items: list[dict] = []
    html_hash: str | None = None
    http_status_last: int | None = None

    for cpath in category_paths:
        cpath_norm = cpath if cpath.startswith("/") else f"/{cpath}"
        category_item_count = 0
        for page in range(1, max_pages + 1):
            url = f"{base_url}{cpath_norm}?page={page}"
            result = http.fetch(url, request_delay_sec=delay)
            http_status_last = result.status_code

            # BC pagination natural terminator: 404 = page beyond catalog.
            # http.fetch returns FetchResult(error_class='other', status_code=404)
            # for 4xx-other; we intercept BEFORE the error_class check below so
            # 404-overshoot doesn't fail the scrape.
            if result.status_code == 404:
                if page == 1:
                    # Page-1 404 is a real schema-change signal (path retired /
                    # renamed since YAML write). Loud-fail per arch §2.4.
                    raise SchemaChangeError(f"{cpath_norm}: page 1 returned 404 — path retired or renamed")
                log.info("%s page %d: 404 natural pagination terminator", cpath_norm, page)
                break

            if result.error_class == "block":
                raise BlockedError(result.error_message or "block detected")
            if result.error_class is not None:
                raise FetchError(result.error_class, f"{result.error_class}: {result.error_message}")

            page_items, first_card_html = _parse_one_page(
                result.body, base_url, cpath_norm, auction_detection, originator_prefix, page,
            )

            if not page_items:
                log.info("%s page %d: 0 cards — pagination terminated", cpath_norm, page)
                break

            # html_hash anchor pin: first li.product outer HTML from first non-empty
            # page of FIRST iterated category_paths entry. YAML list order =
            # iteration order = deterministic. Don't let the anchor float on
            # iteration accidents (CTK-090 Session 1 anchor pin). Per-card-
            # validated anchor capture per finding #4 lives in _parse_one_page.
            if html_hash is None and first_card_html is not None:
                html_hash = _compute_card_skeleton_hash(first_card_html)

            items.extend(page_items)
            category_item_count += len(page_items)

        # Finding #3: per-category min threshold. Opt-in via yaml field. When
        # set, any category producing fewer items than the threshold raises
        # — single-category schema drift surfaces as loud-fail rather than
        # silent ~5% catalog loss.
        if expected_min_per_category is not None and category_item_count < expected_min_per_category:
            raise SchemaChangeError(
                f"{cpath_norm}: {category_item_count} items (expected ≥{expected_min_per_category}) — "
                "likely per-category template override or schema drift"
            )

    if not items:
        raise SchemaChangeError("zero items parsed across all category_paths — scrape produced nothing")

    # Overlap dedup by product_url, first-seen wins. BC vendors carry category
    # overlap (e.g., AquaSD /softies/ ∩ /zoanthids/ ~57 cards 2026-05-26 probe)
    # that surfaces the same product under multiple category_paths. Downstream
    # vendor_listings.product_url is UNIQUE (vendor_id, product_url) so a
    # second insert is a no-op — but diff.classify emits one ItemDecision per
    # input item, and persist_phase_a appends one price_history row per
    # decision. Without dedup at the parser, overlap products write two
    # price_history rows per scrape (CTK-090 Session 4 /code-review finding
    # #1). Dedup here keeps the price_history append-only invariant aligned
    # with the catalog uniqueness contract.
    seen_urls: set[str] = set()
    deduped: list[dict] = []
    for item in items:
        url = item["product_url"]
        if url in seen_urls:
            continue
        seen_urls.add(url)
        deduped.append(item)

    return ParseResult(items=deduped, html_hash=html_hash, http_status_last=http_status_last)


def _parse_one_page(
    html_bytes: bytes,
    base_url: str,
    category_path: str,
    auction_detection: dict | None,
    originator_prefix: str | None,
    page_number: int = 1,
) -> tuple[list[dict], str | None]:
    """Pure HTML→items. Returns (items, first_card_outer_html_or_None) so the
    caller can compute html_hash deterministically. Tested directly against
    locked fixtures in test_aquasd_parse.py — no HTTP layer involved.

    Raises SchemaChangeError when cards are present on the page but ALL fail
    per-card validation (no <article>, no data-name, no href). Distinguishes
    class-rename theme drift from natural pagination end (cards selector
    empty) per CTK-090 Session 4 /code-review finding #2 / #7.
    """
    soup = BeautifulSoup(html_bytes, "html.parser")
    cards = soup.select("li.product")
    if not cards:
        return [], None

    is_auction_path = _is_auction_category(category_path, auction_detection)
    items: list[dict] = []
    # Hash anchor captured AFTER per-card validation per CTK-090 Session 4
    # /code-review finding #4 — pre-validation cards[0] could be an ad slot
    # / promo banner / malformed card that flips the hash on theme cosmetic
    # noise. Sit anchor on the first card that actually appends to items.
    first_card_html: str | None = None

    for card in cards:
        article = card.find("article")
        if article is None:
            log.warning("li.product without nested <article> — skipping card")
            continue
        raw_title = (article.get("data-name") or "").strip()
        if not raw_title:
            log.warning("card missing data-name attr — skipping")
            continue

        link = card.select_one("a.card-figure__link")
        product_url = (link.get("href") if link else "") or ""
        if not product_url:
            log.warning("card %r missing card-figure__link href — skipping", raw_title)
            continue

        price_str = (article.get("data-product-price") or "").strip()
        try:
            current_price = Decimal(price_str) if price_str else None
        except InvalidOperation:
            current_price = None
        # Decimal accepts 'NaN' / 'Infinity' / '-Infinity' without raising
        # InvalidOperation; downstream diff.classify compares old != new and
        # NaN != NaN is always True, so a single NaN-priced card writes one
        # price_history row per scrape forever (CTK-090 Session 4 /code-review
        # finding #6). Coerce non-finite values to None so the listing
        # persists with null price (same shape as a missing data-product-price).
        if current_price is not None and not current_price.is_finite():
            log.warning("card %r non-finite price %r — coercing to None", raw_title, price_str)
            current_price = None
        if is_auction_path:
            current_price = None

        img = card.select_one("img.card-image")
        vendor_image_url = (img.get("src") if img else None) or None

        # Category inference reuses normalize.infer_category against a synthetic
        # product dict (Stencil cards have no Shopify-equivalent product_type
        # field, but data-product-category carries the BC site's category
        # hierarchy and is a useful proxy).
        data_cat = (article.get("data-product-category") or "").strip()
        fake_product = {"product_type": data_cat, "tags": [], "title": raw_title}

        # First card to pass all validation owns the hash anchor for this
        # page (finding #4) — see hash-anchor rationale at function top.
        if first_card_html is None:
            first_card_html = str(card)

        items.append({
            "raw_title": raw_title,
            "normalized_title": normalize.normalize_title(raw_title, originator_prefix=originator_prefix),
            "product_url": product_url,
            "vendor_sku": None,  # BC data-entity-id is internal, not a vendor SKU
            "current_price": current_price,
            "currency": "USD",
            "in_stock": True,  # Stencil hides OOS from category view; silent-OOS gap Q-N flagged in aquasd.yaml
            "vendor_image_url": vendor_image_url,
            "category": normalize.infer_category(fake_product),
            "lineage_flag": normalize.infer_lineage_flag(raw_title),
        })

    # Finding #2 / #7: cards present in DOM but ALL skipped per-card means
    # the wrapper selector still matches (li.product survives) but the inner
    # contract drifted (article rename, data-name attr renamed, link class
    # renamed). Without this raise, the caller would see page_items=[] and
    # treat it as natural pagination end — silent catalog loss class.
    if not items:
        raise SchemaChangeError(
            f"{category_path} page {page_number}: {len(cards)} cards present, 0 parsed — "
            "likely class rename or DOM contract drift (article / data-name / card-figure__link)"
        )

    return items, first_card_html


def _is_auction_category(category_path: str, auction_detection: dict | None) -> bool:
    """Permissive default — None or empty config = no-op (mirrors parse_shopify
    auction_detection None=no-op shape). Future BC vendor with a literal-URL
    auction subpath lights up by adding the YAML block."""
    if not auction_detection:
        return False
    paths = auction_detection.get("category_paths") or []
    # Trailing-slash invariant: normalize both sides before comparison.
    cp = category_path.rstrip("/") + "/"
    return any(p.rstrip("/") + "/" == cp for p in paths)


def _compute_card_skeleton_hash(card_outer_html: str) -> str:
    """Tags + class attrs only per arch §2.6 BC Stencil bullet — strip all
    text + non-class attributes so the hash flips only on theme-engine
    structural change. Walks the BS4 tree to emit `<tag class="...">`
    per descendant in document order."""
    soup = BeautifulSoup(card_outer_html, "html.parser")
    parts: list[str] = []
    for tag in soup.find_all(True):
        cls = tag.get("class")
        if cls:
            parts.append(f'<{tag.name} class="{" ".join(cls)}">')
        else:
            parts.append(f"<{tag.name}>")
    skeleton = "".join(parts)
    return hashlib.sha256(skeleton.encode("utf-8")).hexdigest()
