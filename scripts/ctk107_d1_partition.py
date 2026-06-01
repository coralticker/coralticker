"""CTK-107 D-1 — partition mechanism for BC + UC stale rowset.

Classifies each row in the CTK-105 D-3 stale rowset for BC + UC into one
of three structural partitions keyed on CTK-094 §3 cohort-OOS-at-persist
semantics:

  PARTITION-A — cohort-OOS absent-pass class.
    row.product_url NOT in current /products.json url-set.
    Parser doesn't see the row at intake -> URL lands in
    `existing_by_url - seen_urls - filtered_urls` -> cohort-OOS absent-pass
    fires -> CTK-105 BC/UC opt-in flips in_stock=false. **CTK-105 territory;
    EXCLUDE from CTK-107 IN-list.**

  PARTITION-B — parser-filtered-stuck class.
    row.product_url IN /products.json AND parser's _should_keep returns
    False (allowlist/denylist rejects). URL lands in `filtered_urls` ->
    CTK-094 fold #4 excludes from cohort-OOS -> CTK-105 opt-in does NOT
    flip. **CTK-107 territory; INCLUDE in CTK-107 IN-list.**

  PARTITION-C — anomaly: seen-but-stale.
    row.product_url IN /products.json AND _should_keep returns True. Parser
    accepts the row but DB.last_seen_at is stale. Indicates a scraper
    correctness bug (last_seen_at write-path miss, parser variant-extract
    edge case, or Shopify endpoint divergence). **SURFACE to /lead-backend
    for diagnosis BEFORE CTK-107 fires.** Disposition rule per plan §D-1
    closure-gate caveat: <=3 rows -> hand-disposition in-session; >3 ->
    sibling Tier-1A investigation CTK opens BEFORE CTK-107 fires.

Mechanism:
  1. Pull the BC + UC stale rowset from DB via the CTK-105 D-3 predicate
     verbatim (vendor_id IN (5, 6), in_stock=true, last_seen_at <
     last_success.finished_at - 5min).
  2. Polite-fetch the full /products.json catalog per vendor (limit=250 +
     page=N until empty response; paced by per-vendor request_delay_sec).
  3. Build canonical URL set per vendor: {f"{base_url}/products/{handle}"
     for each product}.
  4. For each stale row, classify against the URL set + _should_keep
     (shared with the production scraper at parse_shopify.py:283).
  5. Emit per-vendor classification block + roll-up + disposition verdict.

WRITE-ZERO. No DB writes, no YAML edits, no commits. /lead-backend
reviews the three lists before authorizing the Session 2 surgical UPDATE.

Reads NEON_DATABASE_URL via scrapers.common.db's load_dotenv side effect.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import yaml

from scrapers.common.db import get_conn
from scrapers.common.http import fetch
from scrapers.common.parse_shopify import _should_keep

STALENESS_JITTER_MIN = 5  # matches CTK-105 D-3 + plan §D-1 step 1
PARTITION_C_HAND_DISPOSITION_THRESHOLD = 3  # <=3 hand-dispose; >3 sibling CTK
VENDOR_YAML_DIR = Path(__file__).parent.parent / "scrapers" / "vendors"

# (vendor_id, slug, expected_per_hypothesis_dict)
# Hypothesis per plan §D-1: BC ~34 A / 0 B / 0 C; UC ~96 B / 0 A / 0 C.
VENDORS = [
    (5, "battlecorals", {"A": 34, "B": 0, "C": 0}),
    (6, "unique_corals", {"A": 0, "B": 96, "C": 0}),
]


def main() -> None:
    print("=" * 78)
    print("CTK-107 D-1 — BC + UC stale-rowset partition (write-zero)")
    print(f"staleness jitter: {STALENESS_JITTER_MIN} min vs. last_success.finished_at")
    print(f"PARTITION-C disposition: <={PARTITION_C_HAND_DISPOSITION_THRESHOLD} "
          f"hand-dispose; >{PARTITION_C_HAND_DISPOSITION_THRESHOLD} sibling Tier-1A CTK")
    print("=" * 78)

    overall: dict[str, list[tuple[str, str]]] = {"A": [], "B": [], "C": []}  # (slug, summary) tuples

    with get_conn() as conn:
        for vendor_id, slug, hypothesis in VENDORS:
            counts = _process_vendor(conn, vendor_id, slug, hypothesis)
            for klass, n in counts.items():
                overall[klass].append((slug, f"{n} rows"))

    print()
    print("=" * 78)
    print("Fleet roll-up")
    print("=" * 78)
    for klass in ("A", "B", "C"):
        per_vendor = "; ".join(f"{slug}={n}" for slug, n in overall[klass])
        print(f"  PARTITION-{klass}: {per_vendor}")

    total_c = sum(int(s.split()[0]) for _, s in overall["C"])
    print()
    if total_c == 0:
        print("PARTITION-C: empty fleet-wide. No scraper correctness anomaly surfaced.")
    elif total_c <= PARTITION_C_HAND_DISPOSITION_THRESHOLD:
        print(f"PARTITION-C: {total_c} row(s) fleet-wide (<= {PARTITION_C_HAND_DISPOSITION_THRESHOLD}). "
              "Surface for /lead-backend hand-disposition.")
    else:
        print(f"PARTITION-C: {total_c} row(s) fleet-wide (> {PARTITION_C_HAND_DISPOSITION_THRESHOLD}). "
              "HOLD CTK-107 pending sibling Tier-1A scraper-correctness CTK.")


def _process_vendor(conn, vendor_id: int, slug: str, hypothesis: dict[str, int]) -> dict[str, int]:
    print()
    print("=" * 78)
    print(f"=== vendor_id={vendor_id} slug={slug} ===")
    print(f"hypothesis: A={hypothesis['A']}  B={hypothesis['B']}  C={hypothesis['C']}")
    print("=" * 78)

    cfg = _load_yaml(slug)
    base_url = cfg["base_url"].rstrip("/")
    request_delay = float(cfg.get("request_delay_sec", 2.0))
    page_size = int(cfg.get("page_size", 250))
    max_pages = int(cfg.get("max_pages", 5))
    category_filter = cfg.get("category_filter") or {}
    in_stock_only = bool(cfg.get("in_stock_only", False))

    print(f"  YAML: base_url={base_url} request_delay_sec={request_delay} "
          f"page_size={page_size} max_pages={max_pages} in_stock_only={in_stock_only}")
    print(f"  category_filter axes: "
          f"product_type_allowlist={'yes' if 'product_type_allowlist' in category_filter else 'no'}  "
          f"tag_allowlist={'yes' if 'tag_allowlist' in category_filter else 'no'}  "
          f"tag_denylist_n={len(category_filter.get('tag_denylist') or [])}  "
          f"title_denylist_n={len(category_filter.get('title_denylist') or [])}")

    stale_rows = _fetch_stale_rows(conn, vendor_id)
    print(f"  stale rowset: {len(stale_rows)} rows")
    if not stale_rows:
        print("  (no rows — nothing to classify)")
        return {"A": 0, "B": 0, "C": 0}

    products_by_url = _fetch_products_json(base_url, page_size, max_pages, request_delay)
    print(f"  /products.json catalog: {len(products_by_url)} unique products fetched")

    partitions: dict[str, list[tuple[dict, dict | None, bool]]] = {"A": [], "B": [], "C": []}
    for row in stale_rows:
        url = row["product_url"]
        product = products_by_url.get(url)
        if product is None:
            partitions["A"].append((row, None, False))
            continue
        keeps = _should_keep(product, category_filter, in_stock_only)
        if keeps:
            partitions["C"].append((row, product, True))
        else:
            partitions["B"].append((row, product, False))

    for klass in ("A", "B", "C"):
        print()
        print(f"  --- PARTITION-{klass} ({len(partitions[klass])} rows) ---")
        _print_partition(klass, partitions[klass])

    counts = {k: len(v) for k, v in partitions.items()}
    print()
    print(f"  Roll-up: A={counts['A']}  B={counts['B']}  C={counts['C']}  "
          f"(total={sum(counts.values())} / stale_rowset={len(stale_rows)})")
    for klass in ("A", "B", "C"):
        exp = hypothesis[klass]
        got = counts[klass]
        flag = "OK" if exp == got else f"DRIFT vs. hypothesis (expected {exp})"
        print(f"    PARTITION-{klass}: got={got:>3}  expected={exp:>3}  {flag}")

    return counts


def _print_partition(klass: str, items: list[tuple[dict, dict | None, bool]]) -> None:
    if not items:
        print("  (empty)")
        return
    if klass == "A":
        print(f"  {'id':>6}  {'current_price':>13}  {'last_seen_at':<26}  raw_title / product_url")
        print(f"  {'-'*6}  {'-'*13}  {'-'*26}  -----")
        for row, _, _ in items:
            price = f"{row['current_price']:>13}" if row['current_price'] is not None else f"{'(null)':>13}"
            last_seen = row["last_seen_at"].isoformat() if row["last_seen_at"] else "(none)"
            title = (row["raw_title"] or "")[:60]
            print(f"  {row['id']:>6}  {price}  {last_seen:<26}  {title!r}")
            print(f"          {row['product_url']}")
    else:
        # B / C carry live /products.json metadata
        print(f"  {'id':>6}  {'current_price':>13}  {'product_type':<24}  raw_title / tags / url")
        print(f"  {'-'*6}  {'-'*13}  {'-'*24}  -----")
        for row, product, _ in items:
            price = f"{row['current_price']:>13}" if row['current_price'] is not None else f"{'(null)':>13}"
            pt = (product.get("product_type") or "")[:24] if product else "(none)"
            tags = product.get("tags") or [] if product else []
            tags_str = ", ".join(tags[:5]) + ("..." if len(tags) > 5 else "")
            title = (row["raw_title"] or "")[:60]
            print(f"  {row['id']:>6}  {price}  {pt:<24}  {title!r}")
            print(f"          tags=[{tags_str}]")
            print(f"          {row['product_url']}")


def _load_yaml(slug: str) -> dict:
    path = VENDOR_YAML_DIR / f"{slug}.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _fetch_stale_rows(conn, vendor_id: int) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT MAX(finished_at) AS last_success "
            "FROM scraper_runs "
            "WHERE vendor_id = %s AND status = 'success' AND finished_at IS NOT NULL",
            (vendor_id,),
        )
        last_success_row = cur.fetchone()
    last_success = last_success_row["last_success"]
    if last_success is None:
        print(f"  ERROR: no successful scraper run for vendor_id={vendor_id}; cannot define stale predicate.")
        return []

    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, product_url, raw_title, current_price, last_seen_at "
            "FROM vendor_listings "
            "WHERE vendor_id = %s "
            "  AND in_stock = true "
            "  AND last_seen_at < %s - INTERVAL '%s minutes' "
            "ORDER BY current_price DESC NULLS LAST, id",
            (vendor_id, last_success, STALENESS_JITTER_MIN),
        )
        return cur.fetchall()


def _fetch_products_json(base_url: str, page_size: int, max_pages: int, request_delay: float) -> dict[str, dict]:
    """Polite-fetch /products.json paginated; build {canonical_url: product}
    dict. Canonical URL shape matches parse_shopify._normalize_product
    (base_url + /products/<handle>) so DB.product_url matches by exact key.

    Terminates on first under-full page OR max_pages ceiling. Mirrors the
    production scraper's pagination shape at parse_shopify.py L114-L160.
    """
    products: dict[str, dict] = {}
    products_path = "/products.json"
    for page in range(1, max_pages + 1):
        url = f"{base_url}{products_path}?limit={page_size}&page={page}"
        print(f"  polite-fetch page {page}: GET {url} (delay={request_delay}s)")
        result = fetch(url, request_delay_sec=request_delay)
        if result.body is None or result.status_code != 200:
            print(f"    ERROR: HTTP {result.status_code} error_class={result.error_class}; "
                  f"halting pagination at page {page}")
            break
        try:
            import json as _json
            data = _json.loads(result.body)
        except Exception as exc:  # noqa: BLE001
            print(f"    ERROR: non-JSON body: {type(exc).__name__}: {exc}; halting at page {page}")
            break
        page_products = data.get("products") or []
        if not page_products:
            print(f"    page {page} empty -> terminating pagination")
            break
        for p in page_products:
            handle = p.get("handle", "")
            if not handle:
                continue
            canonical_url = f"{base_url}/products/{handle}"
            products[canonical_url] = p
        print(f"    page {page} returned {len(page_products)} products (cumulative unique: {len(products)})")
        if len(page_products) < page_size:
            print(f"    page {page} under-full ({len(page_products)} < {page_size}) -> terminating pagination")
            break
    else:
        print(f"    WARNING: hit max_pages={max_pages} ceiling without empty page; "
              "catalog may exceed scraper YAML ceiling.")
    return products


if __name__ == "__main__":
    main()
