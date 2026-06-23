"""CTK-189 — reverse-precision reclassify backfill.

The CTK-189 guard in normalize.infer_category reroutes a coral-tagged non-coral
("Marine Anemone Pellets", "Rio Precision SPS Coral Clipper", "Bejeweled
Favites Sticker") to 'equipment' going FORWARD (next scrape rewrites the row).
This tool reclassifies the standing fleet now.

Unlike the CTK-186 fleet reclassify (ctk186_category_reclassify_backfill.py),
this one needs NO live pull. The CTK-186 boundary fix touched product_type +
tags matching, and vendor_listings stores only raw_title — so CTK-186 had to
re-pull each catalog to recompute. The CTK-189 guard is TITLE-deterministic:
its effect is computable from the stored raw_title + stored category alone
(coral category + title carries a non-coral marker -> equipment). So the
backfill is a pure DB predicate, and it CANNOT diverge from what the next
scrape's infer_category would write (same title-only test).

  UPDATE vendor_listings SET category = 'equipment'
  WHERE category IN (<coral categories>)
    AND <_NONCORAL_TITLE_MARKERS matches raw_title>;

The marker test reuses normalize._NONCORAL_TITLE_MARKERS verbatim — single
source of truth with the production guard, so the backfill and the forward path
can never drift. The match is run row-by-row in Python (the canonical regex is
Python `re`, and PG POSIX `~*` does not share JS/Python boundary semantics —
feedback_pg_posix_vs_python_regex_word_boundary), then applied id-scoped.

Scope / discipline:
  - Reclassify only (category 'equipment'); does NOT touch in_stock — the
    staleness cap owns availability. A frozen mis-tagged row gets BOTH levers
    (category fixed here, in_stock flipped by staleness_cap.py) — belt and
    suspenders.
  - FP-verified at plan time: 0/237 matched corals carry a marker. The run
    re-checks and ABORTS if any named-coral row is in the flip set (a matched
    coral carrying a marker is a re-audit signal, not a flip-anyway).
  - Idempotent: a second run finds nothing (flipped rows are already
    'equipment', out of the coral-category set).

Default run is a DRY RUN — prints the full reclassify diff for the pre-push
eyeball and writes nothing. Pass --apply to commit.

Run via:
  python -m scrapers.tools.ctk189_reverse_precision_reclassify          # dry run
  python -m scrapers.tools.ctk189_reverse_precision_reclassify --apply  # commit

Exit codes: 0 on success; 1 on a matched-coral FP in the flip set (abort) or a
post-verify residual.
"""

from __future__ import annotations

import argparse
import sys

from scrapers.common import db
from scrapers.common.normalize import _CORAL_CATEGORIES, _NONCORAL_TITLE_MARKERS


def main() -> int:
    ap = argparse.ArgumentParser(
        description="CTK-189 reverse-precision reclassify (dry run unless --apply)"
    )
    ap.add_argument("--apply", action="store_true",
                    help="perform the UPDATEs (default: dry run, no writes)")
    args = ap.parse_args()

    mode = "APPLY" if args.apply else "DRY RUN"
    print(f"=== CTK-189 reverse-precision reclassify — {mode} ===\n")

    with db.get_conn() as conn:
        with conn.cursor() as cur:
            # All coral-categoried rows; filter to the marker hits in Python so
            # the regex (and its boundary semantics) is identical to the guard.
            cur.execute(
                "SELECT vl.id, v.slug, vl.category, vl.named_coral_id, vl.raw_title "
                "FROM vendor_listings vl JOIN vendors v ON v.id = vl.vendor_id "
                "WHERE vl.category = ANY(%s) "
                "ORDER BY v.slug, vl.id",
                (list(_CORAL_CATEGORIES),),
            )
            coral_rows = cur.fetchall()

        flips = [r for r in coral_rows if _NONCORAL_TITLE_MARKERS.search(r["raw_title"] or "")]

        if not flips:
            print("no coral-categoried rows carry a non-coral marker — nothing to "
                  "reclassify. Exiting clean.")
            return 0

        # FP abort rail — no matched named coral may be in the flip set.
        fp = [r for r in flips if r["named_coral_id"] is not None]
        print(f"reclassify candidates: {len(flips)} coral-categoried row(s) "
              f"carry a non-coral marker -> equipment")
        for r in flips:
            print(f"  id={r['id']:>7}  {r['slug']:<6} {str(r['category']):<10} -> equipment"
                  f"  {r['raw_title'][:55]!r}")
        print()

        if fp:
            print(f"ABORT: {len(fp)} flip candidate(s) are matched to a named coral "
                  "(named_coral_id NOT NULL) — re-audit before reclassifying:")
            for r in fp:
                print(f"  id={r['id']} coral={r['named_coral_id']} {r['raw_title']!r}")
            return 1

        if args.apply:
            ids = [r["id"] for r in flips]
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE vendor_listings SET category = 'equipment' WHERE id = ANY(%s)",
                    (ids,),
                )
                updated = cur.rowcount
            print(f"APPLY: reclassified {updated} row(s) to category='equipment'")

            # Post-verify: none of the flip ids should still read a coral category.
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT count(*) AS c FROM vendor_listings "
                    "WHERE id = ANY(%s) AND category = ANY(%s)",
                    (ids, list(_CORAL_CATEGORIES)),
                )
                residual = cur.fetchone()["c"]
            if residual:
                print(f"WARN: {residual} flipped id(s) still read a coral category")
                return 1
            print("post-UPDATE verify: 0 flipped rows remain coral-categoried")
        else:
            print(f"DRY RUN: {len(flips)} row(s) would reclassify to equipment. "
                  "Re-run with --apply to commit.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
