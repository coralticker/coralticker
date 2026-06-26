"""Fleet category-coverage drift watch (CTK-199 measurement half).

The recurring fleet-level counterpart to preflight_category_coverage.py. Where
the pre-flight runs ONE vendor's live catalog before it goes live (the 6th
new-vendor signal), this reports the STANDING fleet's coverage from the DB so
drift surfaces without a manual pull. Three signals, per the CTK-199 plan
§Measurement:

  1. Fleet NULL-category in-stock ratio = count(category IS NULL AND in_stock)
     / count(in_stock). Intake-normalized — the headline trend line (absolute
     count drifts up with intake and is the wrong metric).

  2. Classifier-gap residual = in_stock NULL rows whose raw_title ALREADY
     matches a production _CATEGORY_PATTERNS anchor. This is what Lever A drives
     toward ~0: it isolates the RECOVERABLE population (a known anchor the
     stored row missed — scraped before the anchor existed, or a PT/tags-only
     miss the next live re-pull would fix) from the irreducible genus-less
     floor (POTO-style trade-names with no anchor at all). A non-zero residual
     means either a new anchor to add or a backfill that has not been re-run —
     NOT "we have not fixed the floor", which the raw NULL ratio confuses.

  3. Per-vendor in_stock NULL ratio — POTO dominating the floor is the signal a
     single vendor's naming convention drives it; re-surfaces if a new
     POTO-shaped vendor onboards.

DB-only (stored state), no live pull — safe to run any time, including inside a
scrape window. The classifier-gap test runs infer_category against the stored
raw_title alone (product_type/tags are not persisted), so it is a LOWER bound on
true recoverability — the live re-pull in ctk199_category_coverage_backfill sees
the full haystack. Boundary semantics match production by reusing infer_category.

Usage:
  python -m scrapers.tools.category_coverage_drift
  python -m scrapers.tools.category_coverage_drift --ratio-threshold 6 --gap-threshold 10
  python -m scrapers.tools.category_coverage_drift --list-gap   # print recoverable residual titles

Exit codes: 0 = both signals at/under threshold; 1 = fleet ratio over threshold
OR classifier-gap residual over threshold (actionable drift); 2 = query error.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter

from scrapers.common import db
from scrapers.common.normalize import infer_category

DEFAULT_RATIO_THRESHOLD_PCT = 6.0   # fleet in_stock NULL ratio tripwire (today ~4.3%)
DEFAULT_GAP_THRESHOLD = 10          # recoverable-but-NULL rows tolerated before WARN


def _title_classifies(raw_title: str) -> str | None:
    """infer_category against the stored raw_title alone — the classifier-gap
    probe. product_type/tags are not persisted, so this is title-only and a
    lower bound on recoverability; it reuses the production matcher so boundary
    semantics never drift from a hand-rolled regex."""
    return infer_category({"title": raw_title or "", "product_type": "", "tags": []})


def main() -> int:
    ap = argparse.ArgumentParser(description="CTK-199 fleet category-coverage drift watch")
    ap.add_argument("--ratio-threshold", type=float, default=DEFAULT_RATIO_THRESHOLD_PCT,
                    help=f"max fleet in_stock NULL %% (default {DEFAULT_RATIO_THRESHOLD_PCT})")
    ap.add_argument("--gap-threshold", type=int, default=DEFAULT_GAP_THRESHOLD,
                    help=f"max recoverable-but-NULL rows (default {DEFAULT_GAP_THRESHOLD})")
    ap.add_argument("--list-gap", action="store_true",
                    help="print the classifier-gap residual titles (the anchors to add / re-backfill)")
    args = ap.parse_args()

    try:
        with db.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT v.slug, vl.raw_title, vl.category "
                    "FROM vendor_listings vl JOIN vendors v ON v.id = vl.vendor_id "
                    "WHERE vl.in_stock AND v.slug NOT LIKE '\\_%'"
                )
                rows = cur.fetchall()
    except Exception as e:  # noqa: BLE001 — loud
        print(f"ERROR: drift query failed ({type(e).__name__}: {e})", file=sys.stderr)
        return 2

    total = len(rows)
    if total == 0:
        print("0 in_stock rows — nothing to measure (check the DB connection).")
        return 2

    null_rows = [r for r in rows if r["category"] is None]
    null_n = len(null_rows)
    ratio = null_n / total * 100

    # Classifier-gap residual: NULL rows whose title alone a production pattern
    # would classify — the recoverable population Lever A drives toward ~0.
    gap = [r for r in null_rows if _title_classifies(r["raw_title"]) is not None]
    gap_n = len(gap)

    # Per-vendor NULL ratio.
    by_vendor_total: Counter = Counter(r["slug"] for r in rows)
    by_vendor_null: Counter = Counter(r["slug"] for r in null_rows)

    print("=== fleet category-coverage drift ===")
    print(f"  in_stock total:        {total}")
    print(f"  NULL-category:         {null_n}  ({ratio:.1f}%)   threshold {args.ratio_threshold:.1f}%")
    print(f"  classifier-gap residual (recoverable, title-only): {gap_n}   threshold {args.gap_threshold}")
    print("  per-vendor in_stock NULL ratio:")
    for slug, vtotal in by_vendor_total.most_common():
        vnull = by_vendor_null.get(slug, 0)
        if vnull:
            print(f"    {slug:<16} {vnull:>4}/{vtotal:<5} ({vnull / vtotal * 100:.1f}%)")

    if args.list_gap and gap:
        print("  -- classifier-gap residual titles (anchor missing, or re-run the backfill) --")
        for r in gap:
            print(f"    [{r['slug']}] {(r['raw_title'] or '')[:66]!r} -> would be {_title_classifies(r['raw_title'])}")

    fail = False
    if ratio > args.ratio_threshold:
        print(f"\nFAIL: fleet NULL ratio {ratio:.1f}% > {args.ratio_threshold:.1f}%.")
        fail = True
    if gap_n > args.gap_threshold:
        print(f"\nFAIL: classifier-gap residual {gap_n} > {args.gap_threshold} — recoverable rows "
              f"sit NULL. Add the missing anchor(s) to normalize._CATEGORY_PATTERNS and re-run "
              f"ctk199_category_coverage_backfill (re-run with --list-gap to see them).")
        fail = True
    if not fail:
        print(f"\nPASS: fleet ratio {ratio:.1f}% and classifier-gap residual {gap_n} both within threshold.")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
