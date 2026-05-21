"""CTK-041 Session 2 — TSA non-coral backfill via live-pull intersection.

Re-fetches TSA's live /products.json, builds the set of product_urls where
product_type='Livestock' AND tags ∩ <CTK-041 Session 2 non-coral tag set>
≠ ∅, then DELETEs matching rows from vendor_listings. Mirror script for the
forward-write tag_denylist landed in tsa.yaml (CTK-041 Session 2 6-tag
extension).

Match-criteria locked per /lead-backend Session 2 pre-engineer audit
2026-05-21: live-pull intersection (same pattern as
ctk041_pe_invert_backfill.py — auditable, uses same logic as the forward
gate). Pulled-from-vendor rows (those in vendor_listings but absent from
live /products.json) skipped; decay handled separately on in_stock flip
via the natural diff cycle.

Livestock-only filter — the other allowlist entries ("" empty bucket +
Coral-POS) are structural-taxonomy clean per CTK-037 Session 4.5 + Session
5 disposition; no scope creep.

R2-side image purge: SKIPPED per ctk041_pe_invert_backfill.py lean (a)
extension. Script logs orphan R2 key count + byte estimate for results.md
provenance only — per-WebP storage footprint is fractional cents/month at
R2 pricing; vendor re-listing the same slug overwrites the same key via
mirror, so orphans never surface stale-image bugs (extension of memory
project_catalog_rotation_natural_recovery).

Run via:
  python -m scrapers.tools.ctk041_tsa_non_coral_backfill

Exit codes: 0 on success, 1 on DB error or live-pull failure.
"""

from __future__ import annotations

import json
import sys

from scrapers.common import db, http
from scrapers.common.parse_shopify import BlockedError, _to_exception


TSA_VENDOR_ID = 3
TSA_BASE_URL = "https://topshelfaquatics.com"
PRODUCTS_PATH = "/products.json"
PAGE_SIZE = 250
MAX_PAGES = 30
REQUEST_DELAY_SEC = 2.0

# Mirrors tsa.yaml category_filter.tag_denylist Session 2 additions
# (CTK-041 2026-05-21). Fish-tag entries from CTK-037 2026-05-10 are NOT
# included here — CTK-037 forward-write already shipped before any fish
# row landed in vendor_listings at TSA, so the historical fish residue
# count is zero. This script targets the Session 2 non-coral additions
# only (algae-utility inverts + bio media).
TSA_NON_CORAL_TAG_SET = frozenset({
    "Algae Eater",
    "Invert",
    "Live Rock",
    "Macroalgae",
    "Mangrove",
    "Refugiums",
})

# R2 public URL prefix from CTK-036 row #64 (cut-7 EXECUTED 2026-05-15).
# Used only to derive orphan-key estimates for logging; no R2 API call fires.
R2_PUBLIC_PREFIX = "https://images.coralticker.com/tsa/"
# Empirical mean WebP size from CTK-035 D-2 compression cutover + CTK-036
# cut-7 storage figures (TSA ~123 MB total across ~12,000 R2 objects per
# CTK-035 close 3-vendor empirical — order ~10 KB/WebP).
EST_BYTES_PER_WEBP = 10_500


def _fetch_live_tsa_products() -> list[dict]:
    """Paginate TSA /products.json. Returns the concatenated products list.
    Raises on schema-change / block / network error."""
    products: list[dict] = []
    for page in range(1, MAX_PAGES + 1):
        url = f"{TSA_BASE_URL}{PRODUCTS_PATH}?limit={PAGE_SIZE}&page={page}"
        result = http.fetch(url, request_delay_sec=REQUEST_DELAY_SEC)
        if result.error_class == "block":
            raise BlockedError(result.error_message or "block detected")
        if result.error_class is not None:
            raise _to_exception(result)
        payload = json.loads(result.body)
        page_products = payload.get("products") or []
        if not page_products:
            break
        products.extend(page_products)
        if len(page_products) < PAGE_SIZE:
            break
    return products


def _matches_non_coral_leak(product: dict) -> bool:
    """Live-pull intersection predicate — product_type='Livestock'
    AND tags intersect the Session 2 non-coral tag set."""
    if (product.get("product_type") or "") != "Livestock":
        return False
    tags = product.get("tags") or []
    return bool(TSA_NON_CORAL_TAG_SET & set(tags))


def main() -> int:
    print(f"fetching live TSA /products.json (max {MAX_PAGES} pages at "
          f"{REQUEST_DELAY_SEC}s/page)...")
    live_products = _fetch_live_tsa_products()
    print(f"  fetched {len(live_products)} products")

    leak_handles = [
        p.get("handle") for p in live_products if _matches_non_coral_leak(p) and p.get("handle")
    ]
    leak_urls = {f"{TSA_BASE_URL}/products/{h}" for h in leak_handles}
    print(f"live-pull intersection match (Livestock + non-coral tags): {len(leak_urls)} listings")
    for h in sorted(leak_handles):
        print(f"  - {h}")

    if not leak_urls:
        print("no rows match — nothing to delete. Exiting clean.")
        return 0

    with db.get_conn() as conn:
        with conn.cursor() as cur:
            # Resolve vendor_listings rows for the intersection — id + image_url.
            cur.execute(
                "SELECT id, product_url, image_url FROM vendor_listings "
                "WHERE vendor_id = %s AND product_url = ANY(%s) "
                "ORDER BY id",
                (TSA_VENDOR_ID, list(leak_urls)),
            )
            rows = cur.fetchall()
            print(f"\nresolved {len(rows)} vendor_listings rows to delete:")
            for r in rows:
                print(f"  id={r['id']:6d}  image_url={r['image_url']}  url={r['product_url']}")

            if not rows:
                print("no vendor_listings rows match (live-pull intersection had hits but DB has none). "
                      "Exiting clean.")
                return 0

            # Image-purge: SKIPPED per ctk041_pe_invert_backfill.py lean (a)
            # extension. Compute orphan R2 key count + byte estimate for
            # logging only.
            r2_orphans = [r["image_url"] for r in rows
                          if r["image_url"] and r["image_url"].startswith(R2_PUBLIC_PREFIX)]
            null_image_rows = [r for r in rows if not r["image_url"]]
            non_r2_image_rows = [r for r in rows
                                 if r["image_url"] and not r["image_url"].startswith(R2_PUBLIC_PREFIX)]
            est_bytes = len(r2_orphans) * EST_BYTES_PER_WEBP
            est_kb = est_bytes / 1024
            print(f"\nR2 orphan summary (purge skipped per lean (a) extension 2026-05-21):")
            print(f"  R2-hosted image_urls: {len(r2_orphans)} (~{est_kb:.1f} KB orphan footprint)")
            print(f"  NULL image_url rows:  {len(null_image_rows)}")
            print(f"  non-R2 image_urls:    {len(non_r2_image_rows)}")
            if non_r2_image_rows:
                print(f"  WARN: non-R2 image_urls present — investigate (Supabase residue?):")
                for r in non_r2_image_rows:
                    print(f"    id={r['id']}  image_url={r['image_url']}")

            # One-shot DELETE. FK CASCADE on price_history_listing_id_fkey
            # cleans dependent rows automatically (CTK-036 Session 9
            # precedent).
            ids = [r["id"] for r in rows]
            cur.execute(
                "DELETE FROM vendor_listings WHERE id = ANY(%s)",
                (ids,),
            )
            print(f"\nDELETE affected: {cur.rowcount} vendor_listings rows "
                  f"(price_history FK CASCADE follows automatically)")

            # Post-verify.
            cur.execute(
                "SELECT COUNT(*) AS c FROM vendor_listings "
                "WHERE vendor_id = %s AND product_url = ANY(%s)",
                (TSA_VENDOR_ID, list(leak_urls)),
            )
            residual = cur.fetchone()["c"]
            if residual:
                print(f"WARN: {residual} matched rows still present post-DELETE")
                return 1
            print(f"post-DELETE verify: 0 matched rows remain in vendor_listings")
    return 0


if __name__ == "__main__":
    sys.exit(main())
