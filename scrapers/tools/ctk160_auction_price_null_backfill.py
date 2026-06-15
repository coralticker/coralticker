"""CTK-160 Step 2 — one-time backfill: null current_price on stranded in_stock
auction rows, identified by a live /products.json x DB join.

Why a live join (not the CTK-041 `product_url ILIKE '%-auc'` shape): WWC's
current auctions DON'T use the -auc slug suffix — they carry product_type
'WWC Auction' + an 'Auction' tag, handles ending in a numeric id
(e.g. fire-nova-acanthophyllia-7234). The -auc pattern misses every current
stranded row. vendor_listings stores no tags/product_type, so auction rows
cannot be found DB-only (D-6) — we re-pull the feed and reuse the real
_is_auction predicate (no re-implemented detection), same reality as CTK-156
Lens B / audit_axis2_leaks.

Scope: every ACTIVE Shopify vendor whose YAML carries auction_detection (WWC
today). For each, find live _is_auction product_urls, join to vendor_listings
on product_url, and null current_price on rows that are in_stock=true AND
current_price IS NOT NULL (the stranded deceptive-buy-price set). The UPDATE is
id-scoped (WHERE id = ANY(...)) and touches ONLY current_price — no collateral.

Idempotent: re-running finds 0 stranded rows once clean. Reuses the CTK-041
null-out shape (pre-flight print -> UPDATE -> post-verify). Forward-write is
the CTK-160 Option B auction-keep override in parse_shopify — this script is the
immediate one-time correction so the 1B bug clears without waiting for deploy +
the next cron.

Run via:
  python -m scrapers.tools.ctk160_auction_price_null_backfill            # DRY-RUN (default)
  python -m scrapers.tools.ctk160_auction_price_null_backfill --apply    # writes

Run --apply CLEAR of the WWC/POTO/Vivid scrape crons (flap-back race). Exit 0 on
success, 1 on a post-verify gap / error. Reads NEON_DATABASE_URL from .env.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from scrapers.common import db, http
from scrapers.common.parse_shopify import _is_auction

VENDORS_DIR = Path(__file__).resolve().parent.parent / "vendors"


def _shopify_auction_vendors() -> list[dict]:
    """Active-Shopify-with-auction_detection vendor configs (slug filled)."""
    configs = []
    for yaml_path in sorted(VENDORS_DIR.glob("*.yaml")):
        cfg = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
        if cfg.get("platform") == "shopify" and cfg.get("auction_detection"):
            cfg.setdefault("slug", yaml_path.stem)
            configs.append(cfg)
    return configs


def _live_auction_urls(cfg: dict) -> set[str]:
    """Product_urls of live /products.json rows matching _is_auction (real
    predicate). Paginated polite fetch (UA + backoff via http.fetch)."""
    base = cfg["base_url"].rstrip("/")
    ad = cfg["auction_detection"]
    page_size = int(cfg.get("page_size", 250))
    urls: set[str] = set()
    for page in range(1, int(cfg.get("max_pages", 30)) + 1):
        url = f"{base}{cfg.get('products_path', '/products.json')}?limit={page_size}&page={page}"
        r = http.fetch(url, request_delay_sec=float(cfg.get("request_delay_sec", 2.0)))
        if r.error_class is not None:
            raise RuntimeError(f"{cfg['slug']} page {page}: {r.error_class}: {r.error_message}")
        batch = json.loads(r.body).get("products") or []
        if not batch:
            break
        for p in batch:
            handle = p.get("handle", "")
            if handle and _is_auction(p, ad):
                urls.add(f"{base}/products/{handle}")
        if len(batch) < page_size:
            break
    return urls


def _stranded_rows(conn, vendor_id: int, auction_urls: set[str]) -> list[dict]:
    """in_stock auction rows still carrying a non-null current_price."""
    if not auction_urls:
        return []
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, product_url, current_price FROM vendor_listings "
            "WHERE vendor_id = %s AND product_url = ANY(%s) "
            "AND in_stock = true AND current_price IS NOT NULL "
            "ORDER BY id",
            (vendor_id, list(auction_urls)),
        )
        return cur.fetchall()


def run(apply: bool) -> int:
    configs = _shopify_auction_vendors()
    print(f"auction-bearing Shopify vendors: {[c['slug'] for c in configs]}\n")

    total_corrected = 0
    conn = db.get_conn()
    try:
        for cfg in configs:
            slug = cfg["slug"]
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM vendors WHERE slug = %s AND active = true", (slug,))
                vrow = cur.fetchone()
            if vrow is None:
                print(f"[{slug}] not active / not seeded — skip")
                continue
            vendor_id = vrow["id"]

            auction_urls = _live_auction_urls(cfg)
            stranded = _stranded_rows(conn, vendor_id, auction_urls)
            print(f"[{slug}] live _is_auction urls={len(auction_urls)}, "
                  f"stranded in_stock+priced rows={len(stranded)}")
            for r in stranded:
                print(f"    id={r['id']:8d}  current_price={r['current_price']}  {r['product_url']}")

            if not stranded:
                continue
            if not apply:
                print(f"    [DRY-RUN] would null current_price on {len(stranded)} rows")
                continue

            ids = [r["id"] for r in stranded]
            with conn.cursor() as cur:
                # id-scoped, single-column UPDATE — no collateral by construction.
                cur.execute(
                    "UPDATE vendor_listings SET current_price = NULL WHERE id = ANY(%s)",
                    (ids,),
                )
                affected = cur.rowcount
            print(f"    UPDATE affected: {affected} rows")
            total_corrected += affected

            # Post-verify: re-pull the stranded set, expect 0.
            remaining = _stranded_rows(conn, vendor_id, auction_urls)
            if remaining:
                print(f"    WARN: {len(remaining)} rows still non-NULL post-UPDATE")
                for r in remaining:
                    print(f"      id={r['id']}  current_price={r['current_price']}")
                return 1
            print(f"    post-verify: 0 in_stock auction rows carry a non-null price")
    finally:
        conn.close()

    print(f"\n{'APPLIED' if apply else 'DRY-RUN'} — total corrected: {total_corrected}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true",
                        help="Write the UPDATE (default: dry-run, read-only).")
    args = parser.parse_args()
    try:
        return run(args.apply)
    except Exception as e:  # noqa: BLE001 — surface loudly, exit 1
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
