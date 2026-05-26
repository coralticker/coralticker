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
        raise SchemaChangeError("config.category_paths is empty — BC scrape requires at least one path")
    max_pages = int(config.get("max_pages", 30))
    delay = float(config.get("request_delay_sec", 2.0))
    auction_detection = config.get("auction_detection")
    originator_prefix = config.get("originator_prefix")

    items: list[dict] = []
    html_hash: str | None = None
    http_status_last: int | None = None

    for cpath in category_paths:
        cpath_norm = cpath if cpath.startswith("/") else f"/{cpath}"
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
                result.body, base_url, cpath_norm, auction_detection, originator_prefix,
            )

            if not page_items:
                log.info("%s page %d: 0 cards — pagination terminated", cpath_norm, page)
                break

            # html_hash anchor pin: first li.product outer HTML from first non-empty
            # page of FIRST iterated category_paths entry. YAML list order =
            # iteration order = deterministic. Don't let the anchor float on
            # iteration accidents (CTK-090 Session 1 anchor pin).
            if html_hash is None and first_card_html is not None:
                html_hash = _compute_card_skeleton_hash(first_card_html)

            items.extend(page_items)

    if not items:
        raise SchemaChangeError("zero items parsed across all category_paths — scrape produced nothing")

    return ParseResult(items=items, html_hash=html_hash, http_status_last=http_status_last)


def _parse_one_page(
    html_bytes: bytes,
    base_url: str,
    category_path: str,
    auction_detection: dict | None,
    originator_prefix: str | None,
) -> tuple[list[dict], str | None]:
    """Pure HTML→items. Returns (items, first_card_outer_html_or_None) so the
    caller can compute html_hash deterministically. Tested directly against
    locked fixtures in test_aquasd_parse.py — no HTTP layer involved."""
    soup = BeautifulSoup(html_bytes, "html.parser")
    cards = soup.select("li.product")
    if not cards:
        return [], None

    is_auction_path = _is_auction_category(category_path, auction_detection)
    items: list[dict] = []
    first_card_html: str | None = str(cards[0])

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
