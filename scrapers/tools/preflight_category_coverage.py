"""Vendor pre-flight: classifier-coverage check (CTK-194 prevention half).

The new-vendor prevention for the POTO/Cornbred coverage gap. Before a vendor
goes live, run its catalog through the production parse path and report the
NULL-category ratio over the items the scraper would keep (parser output is the
available/in-stock set). If the ratio exceeds the threshold, the vendor's
genera/common-names are missing from normalize._CATEGORY_PATTERNS and should be
added BEFORE the first live scrape — otherwise its corals land NULL-category and
silently drop from the shipped 8-type category INCLUDE filter (the exact
Cornbred-shape CTK-194 fixed retroactively).

This is the sixth signal in the vendor pre-flight sequence
(feedback_five_signal_vendor_preflight: meta + JS global + CDN + robots.txt +
/products.json status, now + classifier coverage). Its durable process home is
the vendor-onboarding pre-flight doc (proposed to /reef-lead), not a CTK.

BROWSE-ELIGIBLE GATE (CTK-143): the ratio that gates PASS/FAIL is measured over
the BROWSE-ELIGIBLE population — items with is_auction=false — not the full
catalog. Rationale: auction rows are CTK-042-gated out of every browse/type
surface (is_auction=true excludes them), so their NULL category can never make a
coral vanish from a filtered surface. On an auction house (Cherry, ~75% auction)
the full-catalog NULL ratio is dominated by fanciful auction morph-names with no
genus/tag/product_type signal anywhere in the feed — absence-of-signal, NOT the
missing-genera miss this gate exists to catch (the CTK-194 add-terms remedy does
not apply to them). Measuring over browse-eligible rows targets exactly the rows
whose NULL category is a real coverage loss. `--include-auctions` gates on the
full catalog for diagnostics.

ORDERING DEPENDENCY (load-bearing): auction_detection must be configured AND
confirmed in the vendor YAML BEFORE this pre-flight runs. is_auction is set by
_normalize_product off auction_detection — if the block is missing or its tag-set
is wrong, true-auction rows carry is_auction=false, fall into the browse-eligible
set, and inflate the counted NULL ratio (or, worse, mask a real miss). The
printed "browse-eligible: N (excluded M auctions)" line makes a mis/unconfigured
auction_detection visible as M=0.

SCOPE — Shopify-effective only. is_auction is a Shopify (parse_shopify) concept;
parse_bigcommerce does not emit it and magento has no auction path, so on those
platforms the exclusion no-ops and the gate falls back to the full catalog. This
tool does NOT claim cross-platform auction exclusion; generalizing it to
BigCommerce is a separate trigger-gated follow-up (it also touches the DB
read-gate).

Usage — the vendor's YAML config must already exist in scrapers/vendors/ (the
pre-flight runs against the live catalog through the same parser the scraper
will use):

  python -m scrapers.tools.preflight_category_coverage <slug>
  python -m scrapers.tools.preflight_category_coverage <slug> --threshold 10
  python -m scrapers.tools.preflight_category_coverage <slug> --list-null
  python -m scrapers.tools.preflight_category_coverage <slug> --include-auctions

Exit codes: 0 = ratio at/under threshold (coverage OK to go live) OR no
browse-eligible rows (pure-auction vendor, N/A); 1 = ratio over threshold (add
terms first); 2 = pull/config error.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter

from scrapers.common import db, parse_bigcommerce, parse_shopify
from scrapers.common.run import _load_yaml
from scrapers.vendors import tidal_gardens

DEFAULT_THRESHOLD_PCT = 10.0  # CTK-194 pre-flight gate (tighter than the 15% running tripwire)


def _parse_catalog(config: dict, platform: str):
    if platform == "shopify":
        return parse_shopify.fetch_and_parse(config)
    if platform == "bigcommerce":
        return parse_bigcommerce.fetch_and_parse(config)
    if platform == "magento":
        return tidal_gardens.fetch_and_parse(config)
    raise RuntimeError(f"platform {platform!r} not implemented (v1 = shopify + bigcommerce + magento)")


def main() -> int:
    ap = argparse.ArgumentParser(description="CTK-194 vendor pre-flight classifier-coverage check")
    ap.add_argument("slug", help="vendor slug (YAML config must exist in scrapers/vendors/)")
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD_PCT,
                    help=f"max acceptable NULL-category %% (default {DEFAULT_THRESHOLD_PCT})")
    ap.add_argument("--list-null", action="store_true",
                    help="print the NULL-category titles (the terms to add)")
    ap.add_argument("--include-auctions", action="store_true",
                    help="gate on the FULL catalog incl. auctions (diagnostics); default "
                         "gates on the browse-eligible is_auction=false set")
    args = ap.parse_args()

    if args.threshold <= 0:
        print(f"ERROR: --threshold must be positive, got {args.threshold}", file=sys.stderr)
        return 2

    try:
        # vendor row is optional at pre-flight (vendor may not be in `vendors`
        # yet) — fall back to a bare config from YAML alone.
        try:
            with db.get_conn() as conn:
                vendor_row = db.fetch_vendor(conn, args.slug)
        except Exception:  # noqa: BLE001 — vendor not yet onboarded; YAML-only path
            vendor_row = {}
        config = {**vendor_row, **_load_yaml(args.slug)}
        platform = config.get("platform")
        if not platform:
            print(f"ERROR: no platform in config for {args.slug!r}", file=sys.stderr)
            return 2
        result = _parse_catalog(config, platform)
    except Exception as e:  # noqa: BLE001 — loud
        print(f"ERROR: {args.slug} catalog pull failed ({type(e).__name__}: {e})", file=sys.stderr)
        return 2

    items = result.items
    total = len(items)
    if total == 0:
        print(f"{args.slug}: 0 items parsed — nothing to check (verify the config/selectors)")
        return 2

    # Browse-eligible = is_auction=false (CTK-143). Auctions are CTK-042-gated out
    # of every browse/type surface, so their NULL category can't vanish a coral
    # from a filtered surface — they're excluded from the gated set. NB: is_auction
    # is a Shopify (parse_shopify) concept; on parse_bigcommerce/magento items carry
    # no is_auction key, so .get() is falsy for all and browse_eligible == items
    # (the exclusion no-ops, gate falls back to full-catalog — Shopify-effective).
    auction_items = [it for it in items if it.get("is_auction")]
    browse_eligible = [it for it in items if not it.get("is_auction")]
    m_auctions = len(auction_items)

    full_null = [it for it in items if it.get("category") is None]
    full_ratio = len(full_null) / total * 100

    print(f"=== pre-flight classifier coverage: {args.slug} ({platform}) ===")
    print(f"  parsed items: {total}")
    print(f"  full-catalog NULL-category: {len(full_null)}  ({full_ratio:.1f}%)")
    print(f"  browse-eligible: {len(browse_eligible)}  (excluded {m_auctions} auctions)")

    # Gate population: browse-eligible by default; full catalog with --include-auctions.
    if args.include_auctions:
        gated, gate_label = items, "full-catalog (--include-auctions)"
    else:
        gated, gate_label = browse_eligible, "browse-eligible (is_auction=false)"

    # Pure-auction vendor: no browse rows to vanish — coverage is N/A, not a FAIL.
    if not args.include_auctions and len(browse_eligible) == 0:
        print(f"\n0 browse-eligible — coverage N/A ({total} items parsed, all auctions).")
        return 0

    gated_total = len(gated)
    null_items = [it for it in gated if it.get("category") is None]
    null_n = len(null_items)
    ratio = null_n / gated_total * 100
    by_cat = Counter(it.get("category") for it in gated)

    print(f"  gate population: {gate_label} — {gated_total}")
    print(f"  gated NULL-category: {null_n}  ({ratio:.1f}%)   threshold: {args.threshold:.1f}%")
    print(f"  category breakdown: {dict(sorted((str(k), v) for k, v in by_cat.items()))}")

    if args.list_null:
        print("  -- NULL-category titles in the gated set (add the genera/common-names below) --")
        for it in null_items:
            print(f"    {(it.get('raw_title') or it.get('title') or '')[:72]!r}")

    if ratio > args.threshold:
        print(f"\nFAIL: {ratio:.1f}% > {args.threshold:.1f}% over {gate_label} — add this "
              f"vendor's terms to normalize._CATEGORY_PATTERNS before first live scrape "
              f"(re-run with --list-null to see the misses).")
        return 1
    print(f"\nPASS: {ratio:.1f}% <= {args.threshold:.1f}% over {gate_label} — coverage OK to go live.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
