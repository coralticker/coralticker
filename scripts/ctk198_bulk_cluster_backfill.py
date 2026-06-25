"""One-shot historical backfill of vendor_listings.bulk_cluster (CTK-198).

Migration 0056 adds the column NOT NULL DEFAULT false (every existing row reads
false). This flips the historical true population: every row whose
(vendor_id, first_seen_at) cohort has >= BULK_CLUSTER_MIN rows. ~15,779 / 25,010
catalog rows (63%) sit in >=50 cohorts.

One-shot (the ctk198_ prefix vs. the un-prefixed operational tools per the
staleness_cap.py convention): run once after 0056, then the nightly audit
(scrapers/tools/bulk_cluster_audit.py) owns the durable reconcile and the
write-time hook (diff.persist_phase_a) owns fresh cohorts.

DRY RUN by default — prints the per-vendor cohort breakdown + the load-bearing
eyeball cohorts (WWC 175 @ 06-20 15:25:39, AquaSD 153) so an operator confirms
the dumps flag AND size-1-3 organic cohorts stay unflagged, BEFORE any write.
Pass --apply to flip.

Idempotent: the `AND vl.bulk_cluster = false` guard makes a re-run a no-op. After
--apply, the nightly audit's dry-run should report 0 flips (backfill + audit
agree).

N lives once in scrapers/common/bulk_cluster.BULK_CLUSTER_MIN — this script
imports it, never a literal.

Run via:
  python -m scripts.ctk198_bulk_cluster_backfill           # dry run
  python -m scripts.ctk198_bulk_cluster_backfill --apply   # flip

Exit codes: 0 on success (dry run or apply), 1 on a post-verify residual.
"""

from __future__ import annotations

import argparse
import sys

from scrapers.common import db
from scrapers.common.bulk_cluster import BULK_CLUSTER_MIN

# The cohort set to flip true, shared verbatim between the dry-run preview and the
# --apply UPDATE so the preview can never diverge from what is written. false->true
# only (the column starts all-false post-0056); the bidirectional reconcile is the
# audit tool's job.
_COHORT_CTE = (
    "WITH big AS ( "
    "  SELECT vendor_id, first_seen_at, count(*) AS n "
    "  FROM vendor_listings "
    "  GROUP BY vendor_id, first_seen_at "
    "  HAVING count(*) >= %(min)s "
    ") "
)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="CTK-198 bulk_cluster historical backfill (dry run unless --apply)"
    )
    ap.add_argument("--apply", action="store_true",
                    help="perform the flip (default: dry run, no writes)")
    args = ap.parse_args()

    mode = "APPLY" if args.apply else "DRY RUN"
    params = {"min": BULK_CLUSTER_MIN}
    print(f"=== bulk_cluster backfill — {mode}, N={BULK_CLUSTER_MIN} ===\n")

    with db.get_conn() as conn:
        # How many rows would flip, and across how many cohorts / vendors.
        with conn.cursor() as cur:
            cur.execute(
                _COHORT_CTE
                + "SELECT count(*) AS cohorts, sum(n) AS rows, "
                "       count(DISTINCT vendor_id) AS vendors "
                "FROM big",
                params,
            )
            summary = cur.fetchone()
        cohorts = summary["cohorts"] or 0
        rows = summary["rows"] or 0
        if cohorts == 0:
            print("no cohort >= N — nothing to backfill. Exiting clean.")
            return 0
        print(f"would flip {rows} row(s) across {cohorts} cohort(s) / "
              f"{summary['vendors']} vendor(s) to bulk_cluster=true\n")

        # Per-vendor cohort breakdown — the eyeball artifact. Each line is one
        # (vendor, first_seen_at) dump with its size.
        with conn.cursor() as cur:
            cur.execute(
                _COHORT_CTE
                + "SELECT v.slug, big.first_seen_at, big.n "
                "FROM big JOIN vendors v ON v.id = big.vendor_id "
                "ORDER BY big.n DESC, v.slug, big.first_seen_at",
                params,
            )
            dumps = cur.fetchall()
        print(f"--- cohorts >= {BULK_CLUSTER_MIN} (largest first) ---")
        for r in dumps:
            print(f"  {r['slug']:<14} {str(r['first_seen_at'])}  n={r['n']}")
        print()

        # Counter-check the organic floor: how many rows sit in size 1-3 cohorts
        # (must STAY false). Reported so the operator confirms the cut is clean.
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) AS small_rows FROM ( "
                "  SELECT vendor_id, first_seen_at, count(*) AS n "
                "  FROM vendor_listings GROUP BY vendor_id, first_seen_at "
                "  HAVING count(*) BETWEEN 1 AND 3 "
                ") s"
            )
            small = cur.fetchone()["small_rows"]
        print(f"size-1-3 organic cohorts: {small} cohort(s) stay bulk_cluster=false "
              f"(unaffected by the >= {BULK_CLUSTER_MIN} cut)\n")

        if not args.apply:
            print(f"DRY RUN: {rows} row(s) would flip. Eyeball the cohorts above "
                  "(WWC 175 @ 06-20 15:25:39 + AquaSD 153 should appear), then "
                  "re-run with --apply.")
            return 0

        with conn.cursor() as cur:
            # Reuse _COHORT_CTE verbatim (NOT a re-inlined HAVING) so the rows
            # flipped here are exactly the cohort the dry-run preview counted —
            # the "can never diverge" guarantee in the module docstring.
            cur.execute(
                _COHORT_CTE
                + "UPDATE vendor_listings vl SET bulk_cluster = true "
                "FROM big "
                "WHERE vl.vendor_id = big.vendor_id "
                "  AND vl.first_seen_at = big.first_seen_at "
                "  AND vl.bulk_cluster = false",
                params,
            )
            flipped = cur.rowcount
        print(f"APPLY: flipped {flipped} row(s) to bulk_cluster=true")

        # Post-verify — re-run the candidate count; the false->true backfill must
        # leave 0 cohort>=N rows still at false (idempotency proof).
        with conn.cursor() as cur:
            cur.execute(
                _COHORT_CTE
                + "SELECT count(*) AS residual "
                "FROM vendor_listings vl JOIN big "
                "  ON big.vendor_id = vl.vendor_id AND big.first_seen_at = vl.first_seen_at "
                "WHERE vl.bulk_cluster = false",
                params,
            )
            residual = cur.fetchone()["residual"]
        if residual:
            print(f"WARN: {residual} cohort-member row(s) still bulk_cluster=false post-UPDATE")
            return 1
        print("post-UPDATE verify: 0 cohort-member rows remain false (idempotent).")

    return 0


if __name__ == "__main__":
    sys.exit(main())
