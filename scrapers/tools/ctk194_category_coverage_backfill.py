"""CTK-194 — fleet category coverage backfill via live-pull recompute.

The CTK-194 coverage ADD to normalize._CATEGORY_PATTERNS (new genera +
common-name abbreviations for the POTO/Cornbred NULL population) corrects stored
`vendor_listings.category` going FORWARD only — rows already NULL keep NULL until
their next scrape touches them, and `decision == 'unchanged'` rows skip the
row-build entirely (feedback_capture_path_unchanged_blind_spot). This tool
reclassifies the standing fleet now.

Identical shape to ctk186_category_reclassify_backfill (which this clones): not a
title-only UPDATE — infer_category reads product_type + tags, which
vendor_listings does not persist, so we re-pull each vendor's live catalog and
recompute category through the SAME production parse path the scraper uses
(run.py platform dispatch + fetch_and_parse, verbatim) so the backfill can never
diverge from what the next scrape would write.

Discipline (unchanged from CTK-186):
  - Fleet-wide per vendor; the _ctk*_test sentinels are skipped.
  - Only rows PRESENT in the live pull are touched. Delisted rows carry no
    recoverable PT/tags and are LEFT UNTOUCHED (off the in-stock feed anyway).
  - Idempotent: a second run finds nothing to change.
  - Run OUTSIDE a scrape window (live HTTP pull races the cron persist otherwise
    — feedback_yaml_state_cron_window_risk.md).

Default run is a DRY RUN — prints the full reclassification diff (both
directions) for the pre-apply eyeball and writes nothing. The diff is the
CTK-194 HARD GATE: every change should be NULL -> <category>. Any
<coral-category> -> <other-category> flip is a collision to scrutinize before
--apply.

Run via:
  python -m scrapers.tools.ctk194_category_coverage_backfill          # dry run
  python -m scrapers.tools.ctk194_category_coverage_backfill --apply  # commit

Exit codes: 0 on success (dry run or apply), 1 on any vendor live-pull error
(loud; other vendors still process).
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter

from scrapers.common import db, parse_bigcommerce, parse_shopify
from scrapers.common.run import _load_yaml
from scrapers.vendors import tidal_gardens


def _live_categories(config: dict, platform: str) -> dict[str, str | None]:
    """Re-pull the vendor's live catalog through the production parser and return
    {product_url: recomputed_category}. Reuses run.py dispatch verbatim — the
    parser yields items whose 'category' is the post-CTK-194 infer_category
    result. Raises on block / schema-change / network error."""
    if platform == "shopify":
        result = parse_shopify.fetch_and_parse(config)
    elif platform == "bigcommerce":
        result = parse_bigcommerce.fetch_and_parse(config)
    elif platform == "magento":
        result = tidal_gardens.fetch_and_parse(config)
    else:
        raise RuntimeError(f"platform {platform!r} not implemented (v1 = shopify + bigcommerce + magento)")
    return {item["product_url"]: item["category"] for item in result.items}


def _vendor_slugs(cur) -> list[dict]:
    cur.execute("SELECT id, slug, platform FROM vendors WHERE slug NOT LIKE '\\_%' ORDER BY id")
    return cur.fetchall()


def main() -> int:
    ap = argparse.ArgumentParser(description="CTK-194 fleet category coverage backfill (dry run unless --apply)")
    ap.add_argument("--apply", action="store_true", help="perform the UPDATEs (default: dry run, no writes)")
    args = ap.parse_args()

    mode = "APPLY" if args.apply else "DRY RUN"
    print(f"=== CTK-194 category coverage backfill — {mode} ===\n")

    total_changes = 0
    fills = 0            # NULL -> category (the intended fix)
    collisions = 0       # non-NULL -> different non-NULL (must be eyeballed)
    fill_by_cat: Counter = Counter()
    vendor_errors: list[str] = []

    with db.get_conn() as conn:
        with conn.cursor() as cur:
            vendors = _vendor_slugs(cur)

        for v in vendors:
            slug, platform = v["slug"], v["platform"]
            try:
                vendor_row = db.fetch_vendor(conn, slug)
                config = {**vendor_row, **_load_yaml(slug)}
                fresh = _live_categories(config, platform)
            except Exception as e:  # noqa: BLE001 — loud per-vendor, continue the fleet
                msg = f"{slug}: live-pull FAILED ({type(e).__name__}: {e})"
                print(f"  {msg}\n")
                vendor_errors.append(msg)
                continue

            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, product_url, raw_title, category FROM vendor_listings "
                    "WHERE vendor_id = %s ORDER BY id",
                    (vendor_row["id"],),
                )
                stored = cur.fetchall()

            changes = []  # (id, raw_title, old, new)
            for r in stored:
                url = r["product_url"]
                if url not in fresh:
                    continue  # delisted / filtered-out — left untouched
                new_cat = fresh[url]
                if new_cat != r["category"]:
                    changes.append((r["id"], r["raw_title"], r["category"], new_cat))

            v_fills = sum(1 for _i, _t, old, new in changes if old is None and new is not None)
            v_coll = sum(1 for _i, _t, old, new in changes if old is not None and new is not None)
            print(f"--- {slug} ({platform}): {len(stored)} stored, {len(fresh)} live, "
                  f"{len(changes)} change ({v_fills} fill, {v_coll} collision) ---")
            for vid, title, old, new in changes:
                marker = "  <-- COLLISION" if (old is not None and new is not None) else ""
                print(f"  id={vid:>7}  {str(old):<10} -> {str(new):<10}  {title[:58]!r}{marker}")
                if old is None and new is not None:
                    fill_by_cat[new] += 1
            print()

            if args.apply and changes:
                with conn.cursor() as cur:
                    cur.executemany(
                        "UPDATE vendor_listings SET category = %s WHERE id = %s",
                        [(new, vid) for vid, _t, _o, new in changes],
                    )
            total_changes += len(changes)
            fills += v_fills
            collisions += v_coll

    print("=== summary ===")
    print(f"{mode}: {total_changes} row(s) {'updated' if args.apply else 'would change'} "
          f"across {len(vendors) - len(vendor_errors)} vendor(s)")
    print(f"  fills (NULL -> category): {fills}   {dict(fill_by_cat)}")
    print(f"  collisions (recat non-NULL): {collisions}  <-- inspect each before --apply")
    if vendor_errors:
        print(f"WARN: {len(vendor_errors)} vendor live-pull error(s):")
        for m in vendor_errors:
            print(f"  - {m}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
