"""CTK-042 acute auction-leak gate — one-time backfill: set is_auction=true on
the live auction set, identified by a live /products.json x DB join.

Why a live join (mirrors CTK-160's ctk160_auction_price_null_backfill): WWC's
current auctions carry product_type 'WWC Auction' + an 'Auction' tag, handles
ending in a numeric id — NOT the dead CTK-041 -auc slug suffix. vendor_listings
stores no tags/product_type, so auction rows cannot be found DB-only (D-6) — we
re-pull the feed and reuse the real _is_auction predicate (no re-implemented
detection), same reality as CTK-160 Step 2 / CTK-156 Lens B.

Scope: every ACTIVE Shopify vendor whose YAML carries auction_detection (WWC
today; POTO/Vivid inherit free via config). For each, find live _is_auction
product_urls, join to vendor_listings on product_url, and set is_auction=true on
rows still reading is_auction=false. The UPDATE is id-scoped (WHERE id = ANY(...))
and touches ONLY is_auction — no collateral.

C2 Δ-catalog verify (not NEW%-threshold): corrected count == the false->true
delta; post-verify re-runs the join and expects 0 live-auction rows still
reading is_auction=false.

APPLY ORDER: migration 0038 (the column) FIRST, this backfill SECOND, migration
0039 (the reader gate) THIRD. 0039 before this backfill gates on an all-false
column and excludes nothing.

Idempotent: re-running finds 0 un-flagged rows once clean. Run --apply CLEAR of
the WWC/POTO/Vivid scrape crons and not straddling the ~13:00 UTC digest fire
(flap-back race). Forward-write is the CTK-042 parse_shopify is_auction set;
this is the immediate one-time correction so the digest stops leaking before
deploy + the next cron.

Run via:
  python -m scrapers.tools.ctk042_is_auction_backfill            # DRY-RUN (default)
  python -m scrapers.tools.ctk042_is_auction_backfill --apply    # writes

Exit 0 on success, 1 on a post-verify gap / error. Reads NEON_DATABASE_URL from
.env.
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


def _unflagged_rows(conn, vendor_id: int, auction_urls: set[str]) -> list[dict]:
    """Live-auction rows still reading is_auction=false (the backfill set)."""
    if not auction_urls:
        return []
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, product_url, in_stock, current_price FROM vendor_listings "
            "WHERE vendor_id = %s AND product_url = ANY(%s) "
            "AND is_auction = false "
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
            unflagged = _unflagged_rows(conn, vendor_id, auction_urls)
            print(f"[{slug}] live _is_auction urls={len(auction_urls)}, "
                  f"rows still is_auction=false={len(unflagged)}")
            for r in unflagged:
                print(f"    id={r['id']:8d}  in_stock={r['in_stock']}  "
                      f"current_price={r['current_price']}  {r['product_url']}")

            if not unflagged:
                continue
            if not apply:
                print(f"    [DRY-RUN] would set is_auction=true on {len(unflagged)} rows")
                continue

            ids = [r["id"] for r in unflagged]
            with conn.cursor() as cur:
                # id-scoped, single-column UPDATE — no collateral by construction.
                cur.execute(
                    "UPDATE vendor_listings SET is_auction = true WHERE id = ANY(%s)",
                    (ids,),
                )
                affected = cur.rowcount
            print(f"    UPDATE affected: {affected} rows")
            total_corrected += affected

            # C2 post-verify: re-pull the join, expect 0 still-unflagged.
            remaining = _unflagged_rows(conn, vendor_id, auction_urls)
            if remaining:
                print(f"    WARN: {len(remaining)} live-auction rows still is_auction=false post-UPDATE")
                for r in remaining:
                    print(f"      id={r['id']}  {r['product_url']}")
                return 1
            print(f"    post-verify: 0 live-auction rows still reading is_auction=false")
    finally:
        conn.close()

    print(f"\n{'APPLIED' if apply else 'DRY-RUN'} — total corrected (false->true): {total_corrected}")
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
