"""CTK-041 Session 1 — PE invert backfill via live-pull intersection.

Re-fetches PE's live /products.json, builds the set of product_urls where
product_type='Weekly Special' AND tags ∩ <v1 invert-tag set> ≠ ∅, then
DELETEs matching rows from vendor_listings. Mirror script for the
forward-write tag_denylist landed in pacific_east.yaml (CTK-041 D-2 lock).

Match-criteria locked per /lead-backend lean 2026-05-14: live-pull
intersection (Option (a) per plan body §"Match-criteria for PE DB cleanup")
— auditable, uses same logic as the forward gate. Pulled-from-vendor rows
(those in vendor_listings but absent from live /products.json) skipped;
decay handled separately on in_stock flip via the natural diff cycle.

R2-side image purge: SKIPPED per /lead-backend lean (a) 2026-05-18
(extension of project_catalog_rotation_natural_recovery weighting). Plan
body L194 + Scope item 4 specs Supabase Storage purge — that backend is
empty post-CTK-036 cut-7 EXECUTED 2026-05-15. Adding a second
irreversible-op surface (R2 delete_object) alongside the DB DELETE is
build cost without ops benefit; per-WebP storage footprint is fractional
cents/month at R2 pricing; vendor re-listing the same slug overwrites the
same key via mirror, so orphans never surface stale-image bugs. Script
logs orphan R2 key count + byte estimate for results.md provenance only.

Run via:
  python -m scrapers.tools.ctk041_pe_invert_backfill

Exit codes: 0 on success, 1 on DB error or live-pull failure.
"""

from __future__ import annotations

import json
import sys

from scrapers.common import db, http
from scrapers.common.parse_shopify import BlockedError, _to_exception


PE_VENDOR_ID = 1
PE_BASE_URL = "https://pacificeastaquaculture.com"
PRODUCTS_PATH = "/products.json"
PAGE_SIZE = 250
MAX_PAGES = 30
REQUEST_DELAY_SEC = 2.0

# Mirrors pacific_east.yaml category_filter.tag_denylist (CTK-041 D-2 lock).
PE_INVERT_TAG_SET = frozenset({
    "Algae Muncher",
    "Astrea Snails",
    "Crab",
    "Inverts",
    "Snail",
    "Trochus",
})

# R2 public URL prefix from CTK-036 row #64 (cut-7 EXECUTED 2026-05-15).
# Used only to derive orphan-key estimates for logging; no R2 API call fires.
R2_PUBLIC_PREFIX = "https://images.coralticker.com/pacific_east/"
# Empirical mean WebP size from CTK-035 D-2 compression cutover + CTK-036
# cut-7 storage figures (PE 4,713 R2 objects estimated under ~50 MB).
EST_BYTES_PER_WEBP = 10_500


def _fetch_live_pe_products() -> list[dict]:
    """Paginate PE /products.json. Returns the concatenated products list.
    Raises on schema-change / block / network error."""
    products: list[dict] = []
    for page in range(1, MAX_PAGES + 1):
        url = f"{PE_BASE_URL}{PRODUCTS_PATH}?limit={PAGE_SIZE}&page={page}"
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


def _matches_invert_leak(product: dict) -> bool:
    """Live-pull intersection predicate — product_type='Weekly Special'
    AND tags intersect the v1 invert-tag set."""
    if (product.get("product_type") or "") != "Weekly Special":
        return False
    tags = product.get("tags") or []
    return bool(PE_INVERT_TAG_SET & set(tags))


def main() -> int:
    print(f"fetching live PE /products.json (max {MAX_PAGES} pages at "
          f"{REQUEST_DELAY_SEC}s/page)...")
    live_products = _fetch_live_pe_products()
    print(f"  fetched {len(live_products)} products")

    leak_handles = [
        p.get("handle") for p in live_products if _matches_invert_leak(p) and p.get("handle")
    ]
    leak_urls = {f"{PE_BASE_URL}/products/{h}" for h in leak_handles}
    print(f"live-pull intersection match (Weekly Special + invert tags): {len(leak_urls)} listings")
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
                (PE_VENDOR_ID, list(leak_urls)),
            )
            rows = cur.fetchall()
            print(f"\nresolved {len(rows)} vendor_listings rows to delete:")
            for r in rows:
                print(f"  id={r['id']:6d}  image_url={r['image_url']}  url={r['product_url']}")

            if not rows:
                print("no vendor_listings rows match (live-pull intersection had hits but DB has none). "
                      "Exiting clean.")
                return 0

            # Image-purge: SKIPPED per /lead-backend lean (a) 2026-05-18.
            # Compute orphan R2 key count + byte estimate for logging only.
            r2_orphans = [r["image_url"] for r in rows
                          if r["image_url"] and r["image_url"].startswith(R2_PUBLIC_PREFIX)]
            null_image_rows = [r for r in rows if not r["image_url"]]
            non_r2_image_rows = [r for r in rows
                                 if r["image_url"] and not r["image_url"].startswith(R2_PUBLIC_PREFIX)]
            est_bytes = len(r2_orphans) * EST_BYTES_PER_WEBP
            est_kb = est_bytes / 1024
            print(f"\nR2 orphan summary (purge skipped per /lead-backend lean (a) 2026-05-18):")
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
                (PE_VENDOR_ID, list(leak_urls)),
            )
            residual = cur.fetchone()["c"]
            if residual:
                print(f"WARN: {residual} matched rows still present post-DELETE")
                return 1
            print(f"post-DELETE verify: 0 matched rows remain in vendor_listings")
    return 0


if __name__ == "__main__":
    sys.exit(main())
