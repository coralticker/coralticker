"""Tidal Gardens — Phase 2 scraper #11 (CTK-087 Session 2, 2026-05-28).

Vendor: https://tidalgardens.com (Copley, OH). vendor_id=11, the last Phase-2
vendor — completes the v1 launch vendor list. Daily cadence (monthly YouTube-
Live drops; not hourly-volatile).

PLATFORM DIVERGENCE — Magento (single-file, not a shared parser).
================================================================
vendor-scan §8 flagged the platform as "unclear, confirm with BuiltWith." The
CTK-087 Session 1 investigation resolved it: Magento (x-magento-cache-debug
header + 48 body markers, WeltPixel/Pearl theme, Cloudflare CDN in front).
Server-rendered category-grid HTML → BS4 static parse, NO Playwright. This is
the THIRD platform class after Shopify (parse_shopify) and BigCommerce Stencil
(parse_bigcommerce). Per arch §2.8 rule-of-three, it stays a single-file
vendor module — there is no shared parse_magento.py until a second Magento
vendor lands. run.py dispatches platform=='magento' directly to this module's
fetch_and_parse.

What diverges from the Shopify/BC parsers (only fetch + parse — the §2.1
lifecycle from diff onward inherits unchanged):

1. CARD GRID. Products are `li.item.product.product-item` cards in a server-
   rendered grid (probe 2026-05-28: 48 cards/page on full categories, matching
   the Magento toolbar "Items 1-48 of N"). Per card:
     - title + url: `a.product-item-link` (text + href). URLs are absolute,
       e.g. https://tidalgardens.com/wysiwyg-all-american-favia.html. NOTE the
       URL prefix is NOT uniformly /stock-*.html (the plan's assumption) —
       both /wysiwyg-*.html and /stock-*.html occur. Do NOT filter on a URL
       prefix; take the href verbatim.
     - price: `span[data-price-type="finalPrice"]` carries a clean
       `data-price-amount` integer/decimal (e.g. "50") — preferred over
       parsing the "$50.00" display text. Sale items expose finalPrice as the
       current price (oldPrice is ignored).
     - image: the grid `<img>` `src` is a lazy-load placeholder (a /static/...
       Loader.gif). The REAL media URL is in `data-original` (Magento
       /media/catalog/product/<x>/<y>/<file>.jpg?<resize params>). The bare
       URL (resize params stripped) returns byte-identical content (probe
       2026-05-28), so we store the param-stripped canonical URL — stable
       across theme resize-param tweaks, avoids spurious image-change churn.

2. PAGINATION — `?p=N`, and MAGENTO CLAMPS PAST-THE-END PAGES. Requesting a
   page beyond the last returns PAGE 1 again (probe 2026-05-28: ?p=9 on an
   8-page category == ?p=1; a 1-page category's ?p=2 == ?p=1). So the
   Shopify/BC empty-page / short-page / 404 terminators NEVER FIRE — Magento
   serves a full page every time. The terminator is the toolbar: "Items X-Y of
   Z", stop when Y >= Z (_is_last_page). A first-title-repeat clamp guard is
   the safety net if the toolbar markup ever drifts. max_pages is the final
   ceiling.

3. OOS HIDDEN. Magento excludes out-of-stock items from category listings
   (probe 2026-05-28: zero OOS markers across all coral paths; every card
   carries Add-to-Cart). Same silent-OOS shape as AquaSD (BigCommerce) and
   POTO — every parsed card lands in_stock=True. Absent-from-scrape items
   never flip in_stock=false (the §2.2 diff iterates present items only). v1
   accepts the ~7-day stale-available window (POTO Tier-3 precedent); TG joins
   CTK-094's cohort-OOS consumer set (fast-follow). The §2.4 listings_seen
   canary applies normally.

4. CATEGORY via PATH ENUMERATION (not an anchor sweep). The /corals.html
   parent anchor DOES aggregate all coral subcategories in one sweep (probe
   2026-05-28: 338 == union of subpaths), but two findings rule it out as the
   scrape source: (a) title-only category inference on the anchor is 38% NULL
   vs 0% NULL when each subpath passes its genus as a category hint; (b) the
   anchor's only 2 extra items over the subpath union are "MEGA Mystery Box"
   grab-bag bundles — aggregator noise we exclude anyway (cf. AquaSD dropping
   frag-packs / multiples buckets). So we enumerate the genus subpaths and
   pass each path's category hint to normalize.infer_category. The hint is the
   product_type proxy (Magento cards carry no product_type field); a title-
   specific pattern can still win over the hint (e.g. an LPS-path "X Chalice"
   resolves to 'chalice', not 'lps' — desirable). Anemones come via
   /corals/anemones.html and clams via /inverts/clams.html, both KEPT with no
   exclusion (CTK-087 Jon 2026-05-28 + CTK-037 D1 fleet anemone/clam-keep).

html_hash sentinel (arch §2.6 Magento variant): skeleton of the first card's
tag + class structure in document order, with per-product numeric class
suffixes stripped (`product-image-container-221` -> `product-image-container`)
so the hash flips ONLY on a real theme-engine structural change, not on the
per-product id baked into the WeltPixel image-container class.

robots.txt audit (Session 1, per arch §2.5): blocks only /catalogsearch/.
The coral genus paths + /inverts/clams.html are crawlable. Standard Chrome UA
(decision #13) + request_delay_sec=2 polite-scraper hygiene inherited.

Test fixture regen path:
  UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 \\
       (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
  curl -sS -A "$UA" 'https://tidalgardens.com/corals/sps.html?p=1' \\
    > /tmp/tg_sps.html
  # Trim to first ~3 li.item.product.product-item cards + the page shell +
  # the toolbar-amount block (needed for _is_last_page). See
  # scrapers/tests/test_tidal_gardens_parse.py for fixture shape assertions.
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

_CARD_SELECTOR = "li.item.product.product-item"
# Strip a trailing per-product numeric suffix from a class token so the
# html_hash skeleton is stable across products (WeltPixel bakes the product id
# into `product-image-container-<id>` / `hover-animation-<n>` classes).
_CLASS_NUM_SUFFIX = re.compile(r"[-_]\d+$")


def fetch_and_parse(config: dict) -> ParseResult:
    """Iterate `category_paths` x `?p=N` until the Magento toolbar reports the
    last page (Y >= Z in "Items X-Y of Z"), with a clamp guard for past-the-end
    pages. Returns ParseResult in the parse_shopify shape so run.py dispatch and
    everything downstream (diff / match / persist) is platform-agnostic.

    category_paths entries are either a plain string path or a
    {path, category} dict — the optional `category` is passed to
    normalize.infer_category as a product_type hint (Magento cards carry no
    product_type). Plain-string entries fall back to title-only inference.
    """
    base_url = config["base_url"].rstrip("/")
    raw_paths = config.get("category_paths") or []
    if not raw_paths:
        # Config-side mistake (empty YAML field), not vendor schema drift —
        # ConfigError routes to error_class='config' so on-call checks the
        # YAML, not the vendor (mirrors parse_bigcommerce).
        raise ConfigError("config.category_paths is empty — Magento scrape requires at least one path")

    paths: list[tuple[str, str | None]] = []
    for entry in raw_paths:
        if isinstance(entry, dict):
            p = entry.get("path")
            if not p:
                raise ConfigError(f"category_paths dict entry missing 'path': {entry!r}")
            paths.append((p, entry.get("category")))
        else:
            paths.append((entry, None))

    max_pages = int(config.get("max_pages", 15))
    delay = float(config.get("request_delay_sec", 2.0))
    originator_prefix = config.get("originator_prefix")

    items: list[dict] = []
    html_hash: str | None = None
    http_status_last: int | None = None

    for cpath, cat_hint in paths:
        cpath_norm = cpath if cpath.startswith("/") else f"/{cpath}"
        first_page_first_title: str | None = None
        for page in range(1, max_pages + 1):
            url = f"{base_url}{cpath_norm}?p={page}"
            result = http.fetch(url, request_delay_sec=delay)
            http_status_last = result.status_code

            if result.status_code == 404:
                if page == 1:
                    # Page-1 404 = path retired/renamed since YAML write.
                    raise SchemaChangeError(f"{cpath_norm}: page 1 returned 404 — path retired or renamed")
                log.info("%s page %d: 404 terminator", cpath_norm, page)
                break
            if result.error_class == "block":
                raise BlockedError(result.error_message or "block detected")
            if result.error_class is not None:
                raise FetchError(result.error_class, f"{result.error_class}: {result.error_message}")

            page_items, first_card_html, page_first_title = _parse_one_page(
                result.body, cpath_norm, cat_hint, originator_prefix, page,
            )

            if not page_items:
                # Magento clamps rather than emptying, so this is unusual — a
                # genuinely empty category or a fetch hiccup. Treat as terminator.
                log.info("%s page %d: 0 cards — terminator", cpath_norm, page)
                break

            # Clamp guard: a past-the-end ?p=N returns page 1 again. If the
            # first title repeats page 1's, we've overshot — stop WITHOUT
            # re-adding page-1 items (the toolbar terminator below normally
            # stops us first; this is the markup-drift safety net).
            if page > 1 and page_first_title == first_page_first_title:
                log.info("%s page %d: clamp detected (first title repeats page 1) — terminator", cpath_norm, page)
                break
            if page == 1:
                first_page_first_title = page_first_title

            if html_hash is None and first_card_html is not None:
                html_hash = _compute_card_skeleton_hash(first_card_html)

            items.extend(page_items)

            if _is_last_page(result.body):
                break

    if not items:
        raise SchemaChangeError("zero items parsed across all category_paths — scrape produced nothing")

    # Dedup by product_url, first-seen wins. Genus subpaths are largely disjoint
    # but a cross-listed piece (cf. AquaSD softies/zoanthids overlap) would
    # otherwise write two price_history rows per scrape. vendor_listings is
    # UNIQUE(vendor_id, product_url); the dedup keeps the price_history append
    # aligned with that uniqueness contract.
    seen_urls: set[str] = set()
    deduped: list[dict] = []
    for item in items:
        u = item["product_url"]
        if u in seen_urls:
            continue
        seen_urls.add(u)
        deduped.append(item)

    return ParseResult(items=deduped, html_hash=html_hash, http_status_last=http_status_last)


def _parse_one_page(
    html_bytes: bytes,
    category_path: str,
    category_hint: str | None,
    originator_prefix: str | None,
    page_number: int = 1,
) -> tuple[list[dict], str | None, str | None]:
    """Pure HTML -> items. Returns (items, first_card_outer_html_or_None,
    first_card_title_or_None). Tested directly against locked fixtures — no HTTP.

    Raises SchemaChangeError when cards are present but ALL fail per-card
    validation (no product-item-link / no href) — discriminates a WeltPixel
    theme class-rename from a genuinely empty page (cards selector empty).
    """
    soup = BeautifulSoup(html_bytes, "html.parser")
    cards = soup.select(_CARD_SELECTOR)
    if not cards:
        return [], None, None

    items: list[dict] = []
    first_card_html: str | None = None
    page_first_title: str | None = None

    for card in cards:
        link = card.select_one("a.product-item-link")
        raw_title = link.get_text(strip=True) if link else ""
        if not raw_title:
            log.warning("%s: card missing a.product-item-link title — skipping", category_path)
            continue
        product_url = (link.get("href") or "").strip()
        if not product_url:
            log.warning("%s: card %r missing href — skipping", category_path, raw_title)
            continue

        if page_first_title is None:
            page_first_title = raw_title

        current_price = _extract_price(card, category_path, raw_title)
        vendor_image_url = _extract_image(card)

        # Magento cards carry no product_type field; the path's genus is the
        # product_type proxy. A title-specific pattern can still win over the
        # hint (e.g. "X Chalice" on the LPS path -> 'chalice').
        fake_product = {"product_type": category_hint or "", "tags": [], "title": raw_title}

        if first_card_html is None:
            first_card_html = str(card)

        items.append({
            "raw_title": raw_title,
            "normalized_title": normalize.normalize_title(raw_title, originator_prefix=originator_prefix),
            "product_url": product_url,
            "vendor_sku": None,  # Magento has no per-card vendor SKU in the grid
            "current_price": current_price,
            "currency": "USD",
            "in_stock": True,  # Magento hides OOS from category view; silent-OOS gap (CTK-094)
            "vendor_image_url": vendor_image_url,
            "category": normalize.infer_category(fake_product),
            "lineage_flag": normalize.infer_lineage_flag(raw_title),
        })

    if not items:
        raise SchemaChangeError(
            f"{category_path} page {page_number}: {len(cards)} cards present, 0 parsed — "
            "likely WeltPixel class rename or DOM contract drift (product-item-link / href)"
        )

    return items, first_card_html, page_first_title


def _extract_price(card, category_path: str, raw_title: str) -> Decimal | None:
    """finalPrice data-price-amount, falling back to any data-price-amount.
    Coerces missing / unparseable / non-finite (NaN/Infinity Decimal accepts
    without raising) to None — same shape as a missing price, so diff.classify
    doesn't write a price_history row per scrape forever."""
    price_el = card.select_one('[data-price-type="finalPrice"]') or card.select_one("[data-price-amount]")
    if price_el is None:
        return None
    amt = (price_el.get("data-price-amount") or "").strip()
    if not amt:
        return None
    try:
        price = Decimal(amt)
    except InvalidOperation:
        return None
    if not price.is_finite():
        log.warning("%s: card %r non-finite price %r — coercing None", category_path, raw_title, amt)
        return None
    return price


def _extract_image(card) -> str | None:
    """Real media URL lives in data-original (the grid src is a lazy-load
    placeholder). Strip resize query params to the canonical /media/ URL
    (probe 2026-05-28: bare URL byte-identical to the param'd URL). Returns
    None when only the /static/ Loader.gif placeholder is present."""
    img = card.select_one("img.product-image-photo") or card.select_one("img")
    if img is None:
        return None
    raw = img.get("data-original") or img.get("data-origsrc") or img.get("src")
    if not raw or "/static/" in raw:  # /static/ = WeltPixel lazy-loader placeholder
        return None
    return raw.split("?")[0]


def _is_last_page(html_bytes: bytes) -> bool:
    """Magento toolbar terminator. "Items X-Y of Z" emits toolbar-number spans;
    the last two values are Y (to) and Z (total). Last page when Y >= Z.
    Single-page categories emit one number (the total) -> treat as last.
    Required because Magento CLAMPS past-the-end pages to page 1 — an empty /
    short-page terminator never fires."""
    soup = BeautifulSoup(html_bytes, "html.parser")
    vals: list[int] = []
    for span in soup.select("p.toolbar-amount span.toolbar-number"):
        try:
            vals.append(int(span.get_text(strip=True).replace(",", "")))
        except ValueError:
            pass
    if len(vals) < 2:
        return True  # single-page (count-only) or toolbar absent
    return vals[-2] >= vals[-1]  # Y >= Z


def _compute_card_skeleton_hash(card_outer_html: str) -> str:
    """Tags + class attrs in document order, per-product numeric class suffixes
    stripped, per arch §2.6 Magento variant. Strips text + non-class attrs so
    the hash flips only on a real theme-engine structural change (WeltPixel /
    Pearl template refresh), not on per-card data or the product id baked into
    the image-container class."""
    soup = BeautifulSoup(card_outer_html, "html.parser")
    parts: list[str] = []
    for tag in soup.find_all(True):
        cls = tag.get("class")
        if cls:
            normed = [_CLASS_NUM_SUFFIX.sub("", c) for c in cls]
            parts.append(f'<{tag.name} class="{" ".join(normed)}">')
        else:
            parts.append(f"<{tag.name}>")
    return hashlib.sha256("".join(parts).encode("utf-8")).hexdigest()
