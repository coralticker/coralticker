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

    items: list[dict] = []
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

        items.extend(_normalize_product(p, image_strategy, originator_prefix) for p in products)

        if len(products) < page_size:
            # Short page = last page. Spares one wasted round-trip.
            break

    return ParseResult(items=items, html_hash=html_hash, http_status_last=http_status_last)


def _normalize_product(product: dict, image_strategy: str, originator_prefix: str | None) -> dict:
    """Map a Shopify product dict to the diff.py + DB shape. Stage 4 (Normalize)
    of the arch §2.1 lifecycle — title/category/price/stock coercion happens here."""
    raw_title = product.get("title", "")
    handle = product.get("handle", "")
    product_url = f"/products/{handle}" if handle else ""

    variants = product.get("variants") or []
    in_stock = any(v.get("available") for v in variants)
    current_price = normalize.coerce_price(variants)
    sku = next((v.get("sku") for v in variants if v.get("sku")), None)

    images = product.get("images") or []
    vendor_image_url = images[0].get("src") if images else None

    return {
        "raw_title": raw_title,
        "normalized_title": normalize.normalize_title(raw_title, originator_prefix=originator_prefix),
        "product_url": product_url,            # vendor-relative; orchestrator joins base_url at persist
        "vendor_sku": sku,
        "current_price": current_price,
        "currency": "USD",                     # Phase 1 vendors all USD per Q1-3
        "in_stock": in_stock,
        "vendor_image_url": vendor_image_url,  # raw vendor URL; image-pipeline decides what becomes image_url
        "category": normalize.infer_category(product),
        "lineage_flag": normalize.infer_lineage_flag(raw_title),
    }


def _to_exception(result: http.FetchResult) -> Exception:
    """Map an http.FetchResult error_class to the right Exception. Orchestrator
    catches BaseException and records error_class on scraper_runs; passing a
    typed marker lets us tell network from 429 from 5xx without sniffing strings."""
    cls = result.error_class
    msg = f"{cls}: {result.error_message}"
    err = RuntimeError(msg)
    err.error_class = cls  # type: ignore[attr-defined]
    return err
