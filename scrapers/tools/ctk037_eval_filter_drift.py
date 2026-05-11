"""CTK-037 Session 4 — retroactive filter-drift eval.

Re-fetch each Phase 1 vendor's /products.json, intersect against rows already
in vendor_listings on the canonical absolute product_url, and exercise
parse_shopify._should_keep on the fresh inputs. Buckets per vendor:

  - In-catalog + filter-keep  — coral row, filter would keep (clean precision)
  - In-catalog + filter-reject — false-reject candidate; rows worth a manual
                                  sample-inspect against real-coral vs. legacy
  - Drift                      — stored row not in current /products.json; no
                                  fresh inputs to apply filter against; excluded
                                  from precision denominator

Read-only: no DB writes, no schema changes, no backfill. JF excluded — no
rows in vendor_listings yet (CTK-027 not started); eval re-runs at CTK-027
Session 1 close if needed.

Run via:
  python -m scrapers.tools.ctk037_eval_filter_drift
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from scrapers.common import db, http
from scrapers.common.parse_shopify import _should_keep, SchemaChangeError


VENDOR_SLUGS = ("pacific_east", "wwc", "tsa")
SAMPLE_LIMIT = 20

# CTK-037 Session 4.5 — suspect product_type buckets per vendor surfaced by
# Session 4 reject-distribution histogram. "" matches both None and empty-string
# product_type rows (bucketed as "(empty)" in the histogram).
SUSPECT_BUCKETS: dict[str, dict[str, int]] = {
    "pacific_east": {
        "Reef Stuff": 10,
        "Weekly Special": 6,
        "Premium Member Deal": 3,
    },
    "wwc": {
        "": 10,
        "Doorbuster": 6,
        "Custom Bundle": 3,
        "CTO Corals": 1,
        "auction": 1,
        "Auction": 1,
    },
    "tsa": {
        "": 10,
        "Drop shipped": 10,
        "Coral-POS": 1,
    },
}


def _load_yaml(slug: str) -> dict:
    path = Path(__file__).parent.parent / "vendors" / f"{slug}.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _fetch_fresh_catalog(config: dict) -> dict[str, dict]:
    """Re-fetch /products.json pages and return {product_url: {product_type, tags}}.
    Uses scrapers.common.http.fetch so UA + retry + 429 backoff stay consistent
    with production scrapers per arch §2.4/§2.5. Pagination mirrors
    parse_shopify.fetch_and_parse — short page terminates, max_pages ceiling."""
    base_url = config["base_url"].rstrip("/")
    products_path = config.get("products_path", "/products.json")
    page_size = int(config.get("page_size", 250))
    max_pages = int(config.get("max_pages", 30))
    delay = float(config.get("request_delay_sec", 2.0))

    fresh: dict[str, dict] = {}
    for page in range(1, max_pages + 1):
        url = f"{base_url}{products_path}?limit={page_size}&page={page}"
        result = http.fetch(url, request_delay_sec=delay)
        if result.error_class is not None:
            raise RuntimeError(f"fetch {url}: {result.error_class}: {result.error_message}")
        try:
            payload = json.loads(result.body)
        except json.JSONDecodeError as e:
            raise SchemaChangeError(f"page {page}: JSON decode failed: {e}") from e
        products = payload.get("products")
        if products is None:
            raise SchemaChangeError(f"page {page}: response missing 'products' key")
        if not products:
            break
        for p in products:
            handle = p.get("handle", "")
            if not handle:
                continue
            product_url = f"{base_url}/products/{handle}"
            fresh[product_url] = {
                "product_type": p.get("product_type"),
                "tags": p.get("tags") or [],
            }
        if len(products) < page_size:
            break
    return fresh


def _fetch_stored_listings(client, vendor_id: int) -> list[dict]:
    """SELECT id, raw_title, product_url FROM vendor_listings WHERE vendor_id=<vid>.
    Inlines CTK-033/034 chunk-ordering pattern (`.order("id") + .range()` loop
    + count-mismatch sanity-check) because db.fetch_existing_listings doesn't
    project raw_title."""
    page_size = 1000
    iteration_ceiling = 50
    rows: list[dict] = []
    iteration = 0
    while iteration < iteration_ceiling:
        start = iteration * page_size
        end = start + page_size - 1
        chunk = (
            client.table("vendor_listings")
            .select("id,raw_title,product_url")
            .eq("vendor_id", vendor_id)
            .order("id")
            .range(start, end)
            .execute()
            .data
            or []
        )
        rows.extend(chunk)
        iteration += 1
        if len(chunk) < page_size:
            break
    expected = (
        client.table("vendor_listings")
        .select("id", count="exact")
        .eq("vendor_id", vendor_id)
        .execute()
        .count
    )
    if len(rows) != expected:
        raise RuntimeError(
            f"_fetch_stored_listings coverage gap for vendor_id={vendor_id}: "
            f"chunked SELECT returned {len(rows)} but catalog count={expected}"
        )
    return rows


def _classify_reject(fresh_entry: dict, category_filter: dict) -> str:
    """Mirror _should_keep's decision tree to label WHY a row was rejected.
    Predicate stays canonical (imported above); this helper only narrates."""
    allowlist = category_filter.get("product_type_allowlist") or []
    tag_denylist = category_filter.get("tag_denylist") or []
    pt = fresh_entry.get("product_type")
    tags = fresh_entry.get("tags") or []
    if allowlist and pt not in allowlist:
        return f"allowlist-miss(product_type={pt!r})"
    if tag_denylist:
        hits = [t for t in tags if t in tag_denylist]
        if hits:
            return f"tag-denylist-hit(tags={hits!r})"
    return "unknown"  # _should_keep returned False but neither rule fires — shouldn't happen


def _eval_vendor(client, slug: str) -> dict:
    config = _load_yaml(slug)
    vendor_row = db.fetch_vendor(client, slug)
    vendor_id = vendor_row["id"]
    base_url = config["base_url"].rstrip("/")

    fresh_by_url = _fetch_fresh_catalog(config)
    stored = _fetch_stored_listings(client, vendor_id)
    category_filter = config.get("category_filter") or {}

    keep_count = 0
    reject_rows: list[dict] = []
    drift_count = 0
    in_catalog_count = 0

    for row in stored:
        product_url = row["product_url"]
        fresh_entry = fresh_by_url.get(product_url)
        if fresh_entry is None:
            drift_count += 1
            continue
        in_catalog_count += 1
        # Build a synthetic product dict matching _should_keep's contract.
        synthetic = {
            "product_type": fresh_entry["product_type"],
            "tags": fresh_entry["tags"],
        }
        if _should_keep(synthetic, category_filter):
            keep_count += 1
        else:
            reject_rows.append({
                "id": row["id"],
                "raw_title": row["raw_title"],
                "product_type": fresh_entry["product_type"],
                "tags": fresh_entry["tags"],
                "reject_reason": _classify_reject(fresh_entry, category_filter),
            })

    # Annotate reject_rows with product_url for sample-suspect-buckets fresh-catalog
    # check (Session 4.5 extension).
    annotated_rejects: list[dict] = []
    for row in stored:
        product_url = row["product_url"]
        fresh_entry = fresh_by_url.get(product_url)
        if fresh_entry is None:
            continue
        synthetic = {
            "product_type": fresh_entry["product_type"],
            "tags": fresh_entry["tags"],
        }
        if not _should_keep(synthetic, category_filter):
            annotated_rejects.append({
                "id": row["id"],
                "raw_title": row["raw_title"],
                "product_url": product_url,
                "product_type": fresh_entry["product_type"],
                "tags": fresh_entry["tags"],
                "reject_reason": _classify_reject(fresh_entry, category_filter),
            })

    return {
        "slug": slug,
        "vendor_id": vendor_id,
        "base_url": base_url,
        "stored": len(stored),
        "in_catalog": in_catalog_count,
        "filter_keep": keep_count,
        "filter_reject": len(reject_rows),
        "drift": drift_count,
        "reject_rows": annotated_rejects,
        "fresh_by_url": fresh_by_url,
    }


def _sample_suspect_buckets(result: dict, buckets: dict[str, int]) -> None:
    """Print sampled rows per suspect product_type bucket per Session 4.5 directive.
    All sampled rows are in-fresh-catalog by construction (the filter_reject set
    is the intersection of stored × fresh × reject); fresh-catalog-still-listed=Y
    is constant for every sample and noted in the section header rather than
    repeated per row."""
    slug = result["slug"]
    reject_rows = result["reject_rows"]
    print(f"\n--- {slug}: sample-inspect suspect product_type buckets "
          f"(all rows in-fresh-catalog by construction) ---")
    # Group reject_rows by normalized product_type key — "" matches None or "".
    grouped: dict[str, list[dict]] = {}
    for row in reject_rows:
        pt = row["product_type"]
        key = pt if pt not in (None, "") else ""
        grouped.setdefault(key, []).append(row)
    for pt_key, max_n in buckets.items():
        rows = grouped.get(pt_key, [])
        label = pt_key if pt_key != "" else "(empty)"
        sampled = rows[:max_n]
        print(f"\n  bucket={label!r}  bucket_size={len(rows)}  sample={len(sampled)}")
        for row in sampled:
            print(
                f"    id={row['id']} product_type={row['product_type']!r} "
                f"tags={row['tags']!r}\n"
                f"      raw_title={row['raw_title']!r}"
            )


def _pe_weekly_special_tag_distribution(result: dict) -> None:
    """Per Session 4.5 directive — for PE Weekly Special, dump the tag histogram
    across ALL fresh /products.json rows with product_type='Weekly Special' (not
    just the 6 stored rows). Tests whether PE Weekly Special is predominantly
    coral (full-allow safe) or mixed (deny stays + accept 1 SPS false-reject)."""
    if result["slug"] != "pacific_east":
        return
    fresh_by_url = result["fresh_by_url"]
    tag_counts: dict[str, int] = {}
    rows_in_bucket = 0
    sample_titles: list[str] = []
    for product_url, entry in fresh_by_url.items():
        if entry["product_type"] != "Weekly Special":
            continue
        rows_in_bucket += 1
        for t in entry["tags"]:
            tag_counts[t] = tag_counts.get(t, 0) + 1
        if len(sample_titles) < 10:
            sample_titles.append(product_url.rsplit("/", 1)[-1])
    print(f"\n--- pacific_east: Weekly Special tag distribution across fresh catalog ---")
    print(f"  rows in bucket: {rows_in_bucket}")
    if rows_in_bucket == 0:
        print("  no rows — skip")
        return
    for t, n in sorted(tag_counts.items(), key=lambda kv: -kv[1]):
        print(f"    {t!r:<30} {n}")
    print(f"\n  first {len(sample_titles)} handles in bucket (for spot-inspect):")
    for h in sample_titles:
        print(f"    {h}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sample-suspect-buckets",
        action="store_true",
        help="CTK-037 Session 4.5 — print per-suspect-product_type sample (5-10 rows per "
             "bucket) + PE Weekly Special tag distribution across fresh catalog.",
    )
    args = parser.parse_args()

    client = db.get_client()
    results = []
    for slug in VENDOR_SLUGS:
        print(f"[eval] {slug} ...", file=sys.stderr)
        result = _eval_vendor(client, slug)
        results.append(result)
        print(
            f"[eval] {slug}: stored={result['stored']} in_catalog={result['in_catalog']} "
            f"keep={result['filter_keep']} reject={result['filter_reject']} drift={result['drift']}",
            file=sys.stderr,
        )

    print()
    print("CTK-037 Session 4 — retroactive filter-drift eval")
    print(f"{'Vendor':<16}{'Stored':>10}{'In-catalog':>14}{'Filter-keep':>14}{'Filter-reject':>16}{'Drift':>10}")
    for r in results:
        print(
            f"{r['slug']:<16}{r['stored']:>10}{r['in_catalog']:>14}"
            f"{r['filter_keep']:>14}{r['filter_reject']:>16}{r['drift']:>10}"
        )

    any_rejects = False
    for r in results:
        if r["filter_reject"] >= 1:
            any_rejects = True
            print()
            print(f"--- {r['slug']}: filter-reject distribution by product_type ---")
            pt_counts: dict[str, int] = {}
            for row in r["reject_rows"]:
                pt = row["product_type"] or "(empty)"
                pt_counts[pt] = pt_counts.get(pt, 0) + 1
            for pt, n in sorted(pt_counts.items(), key=lambda kv: -kv[1]):
                print(f"  {pt!r:<30} {n}")
            print()
            print(f"--- {r['slug']}: first {min(SAMPLE_LIMIT, r['filter_reject'])} filter-reject rows ---")
            for row in r["reject_rows"][:SAMPLE_LIMIT]:
                print(
                    f"  id={row['id']} "
                    f"product_type={row['product_type']!r} "
                    f"tags={row['tags']!r} "
                    f"reject={row['reject_reason']}\n"
                    f"    raw_title={row['raw_title']!r}"
                )

    if not any_rejects:
        print()
        print("0 filter-reject rows across all vendors — precision clean retroactively.")

    if args.sample_suspect_buckets:
        print()
        print("=" * 70)
        print("CTK-037 Session 4.5 — per-suspect-bucket sample-inspect")
        print("=" * 70)
        for r in results:
            buckets = SUSPECT_BUCKETS.get(r["slug"], {})
            if not buckets:
                continue
            _sample_suspect_buckets(r, buckets)
            _pe_weekly_special_tag_distribution(r)

    return 0


if __name__ == "__main__":
    sys.exit(main())
