"""CTK-186 — fleet category reclassify via live-pull recompute.

The CTK-186 boundary fix to normalize._CATEGORY_PATTERNS corrects the stored
`vendor_listings.category` going FORWARD (next scrape rewrites each row), but
rows already in the table keep their pre-fix (substring-mis-tagged) category
until their next scrape touches them. This tool reclassifies the standing
fleet now.

It is NOT a title-only UPDATE: infer_category reads product_type + tags, and
vendor_listings persists only raw_title (not PT/tags). So we re-pull each
vendor's live catalog and recompute category against the live product JSON via
the SAME production parse path the scraper uses — mirroring
ctk041_tsa_non_coral_backfill.py's live-pull pattern, and reusing
run.py's platform dispatch (parse_shopify / parse_bigcommerce /
tidal_gardens.fetch_and_parse) verbatim so the backfill result can never
diverge from what the next scrape would write.

Scope / discipline:
  - Recompute is fleet-wide per vendor (the alternation-boundary bug was
    fleet-wide), not id-targeted. The _ctk*_test sentinel vendors are skipped.
  - Only rows PRESENT in the live pull are touched. Delisted rows (in DB,
    absent from the live catalog) carry no recoverable PT/tags and are LEFT
    UNTOUCHED — same as ctk041's "pulled-from-vendor rows skipped." They are
    off the in-stock feed, so a stale category there never shows; active-NULL
    would wipe correct historical category on thousands of sold-out rows for
    zero feed benefit (Jon-locked 2026-06-23).
  - Idempotent: a second run finds nothing to change.
  - Run OUTSIDE a scrape window (live HTTP pull races the cron persist
    otherwise — feedback_yaml_state_cron_window_risk.md).

Default run is a DRY RUN — it prints the full reclassification diff (both
directions) for the pre-push eyeball and writes nothing. Pass --apply to
perform the UPDATEs.

Run via:
  python -m scrapers.tools.ctk186_category_reclassify_backfill          # dry run
  python -m scrapers.tools.ctk186_category_reclassify_backfill --apply  # commit

Exit codes: 0 on success (dry run or apply), 1 on any vendor live-pull error
(the error is loud; other vendors still process).
"""

from __future__ import annotations

import argparse
import sys

from scrapers.common import db, parse_bigcommerce, parse_shopify
from scrapers.common.run import _load_yaml
from scrapers.vendors import tidal_gardens


# Verify IDs from CTK-186 plan.md — printed at the end with their landed
# category so the eyeball can confirm the named cases in one glance.
VERIFY_IDS = {
    67977: "Pumpkin Pie -> coral/NULL (was equipment)",
    170478: "Cornbred Tangerine Dreams Acro -> coral/NULL (was fish)",
    170693: "Cornbred Mango Tango Echinata -> coral/NULL (was fish)",
    167253: "JF Tangerine Twisters Cloves -> coral/NULL (was fish)",
    73876: "WWC Mango Tango Echinata -> coral/NULL (was fish)",
    173963: "TSA adapter -> stays equipment (control)",
    39192: "TSA (SPS) kit -> may stay sps (deferred CTK-188)",
}


def _live_categories(config: dict, platform: str) -> dict[str, str | None]:
    """Re-pull the vendor's live catalog through the production parser and
    return {product_url: recomputed_category}. Reuses run.py:518-535 dispatch
    verbatim — the parser yields items whose 'category' is already the post-fix
    infer_category result. Raises on block / schema-change / network error
    (same shapes run.py handles)."""
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
    """Real vendors only — the _ctk*_test sentinels are skipped (slug prefix '_')."""
    cur.execute("SELECT id, slug, platform FROM vendors WHERE slug NOT LIKE '\\_%' ORDER BY id")
    return cur.fetchall()


def main() -> int:
    ap = argparse.ArgumentParser(description="CTK-186 fleet category reclassify (dry run unless --apply)")
    ap.add_argument("--apply", action="store_true", help="perform the UPDATEs (default: dry run, no writes)")
    args = ap.parse_args()

    mode = "APPLY" if args.apply else "DRY RUN"
    print(f"=== CTK-186 category reclassify — {mode} ===\n")

    total_changes = 0
    vendor_errors: list[str] = []
    verify_landed: dict[int, tuple[str, str | None]] = {}  # id -> (raw_title, category)

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
                    continue  # delisted / filtered-out — left untouched (Jon-locked)
                new_cat = fresh[url]
                if new_cat != r["category"]:
                    changes.append((r["id"], r["raw_title"], r["category"], new_cat))

            print(f"--- {slug} ({platform}): {len(stored)} stored, {len(fresh)} live, "
                  f"{len(changes)} reclassify ---")
            for vid, title, old, new in changes:
                print(f"  id={vid:>7}  {str(old):<10} -> {str(new):<10}  {title[:60]!r}")
            print()

            if args.apply and changes:
                with conn.cursor() as cur:
                    cur.executemany(
                        "UPDATE vendor_listings SET category = %s WHERE id = %s",
                        [(new, vid) for vid, _t, _o, new in changes],
                    )
            total_changes += len(changes)

        # Verify-id readout — current landed state after this run.
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, raw_title, category FROM vendor_listings WHERE id = ANY(%s)",
                (list(VERIFY_IDS),),
            )
            for r in cur.fetchall():
                verify_landed[r["id"]] = (r["raw_title"], r["category"])

    print("=== verify ids ===")
    for vid, expectation in VERIFY_IDS.items():
        if vid in verify_landed:
            title, cat = verify_landed[vid]
            print(f"  id={vid:>7}  category={str(cat):<10}  [{expectation}]")
        else:
            print(f"  id={vid:>7}  NOT PRESENT (sold out / off live feed — not chased)  [{expectation}]")

    print(f"\n{mode}: {total_changes} row(s) "
          f"{'updated' if args.apply else 'would change'} across "
          f"{len(vendors) - len(vendor_errors)} vendor(s)")
    if vendor_errors:
        print(f"WARN: {len(vendor_errors)} vendor live-pull error(s):")
        for m in vendor_errors:
            print(f"  - {m}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
