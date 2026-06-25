"""Nightly full-catalog reconcile of vendor_listings.bulk_cluster (CTK-198).

The durable half of the self-healing contract. The write-time hook
(diff.persist_phase_a) flips fresh cohorts false->true at scrape time; this tool
reconciles the ENTIRE catalog against the desired value every night, catching
anything the hook missed (a cross-run edge, a hook error, a manual data
correction) and — uniquely — performing any true->false correction (the
write-time hook is monotonic false->true and never reverses).

Desired value per row: bulk_cluster = (its (vendor_id, first_seen_at) cohort has
>= BULK_CLUSTER_MIN rows). Computed with a window COUNT(*) OVER the cohort
partition, compared to the stored column via IS DISTINCT FROM, so the UPDATE
touches ONLY drifted rows.

Properties (mirror staleness_cap.py):
  - Idempotent: a second run finds nothing (post-reconcile every row matches its
    desired value). Reversible by construction — bulk_cluster is derived, never
    authoritative; a wrong flag self-corrects here.
  - Pure function of immutable (vendor_id, first_seen_at): true->false should be
    rare-to-never in practice (cohort keys don't change), so a non-zero
    true->false count is informational, not an abort — it means a prior
    write-side bug or an N change, which is exactly what this reconcile heals.
  - Operational, re-runnable indefinitely (un-prefixed, vs. the one-shot
    ctk198_bulk_cluster_backfill.py).

DRY RUN by default — prints the would-flip breakdown (false->true and
true->false separately) and writes nothing. Pass --apply to reconcile.

Run OUTSIDE a scrape window (cron 14:02 UTC, clear of all scrape windows): a
concurrent persist could write new rows mid-run. The race is benign — the
write-time hook covers fresh cohorts, and the next nightly run reconciles any
straggler — but the slot is chosen clear regardless (feedback_yaml_state_cron_window_risk).

N lives once in scrapers/common/bulk_cluster.BULK_CLUSTER_MIN — imported, never a
literal.

Run via:
  python -m scrapers.tools.bulk_cluster_audit           # dry run
  python -m scrapers.tools.bulk_cluster_audit --apply   # reconcile

Exit codes: 0 on success (dry run or apply), 1 on a post-verify residual.
"""

from __future__ import annotations

import argparse
import sys

from scrapers.common import db
from scrapers.common.bulk_cluster import BULK_CLUSTER_MIN

# Desired-vs-stored per row, shared verbatim between the dry-run preview, the
# UPDATE, and the post-verify so none can diverge. `want` is the cohort-size
# verdict; the IS DISTINCT FROM filter selects only rows whose stored flag drifts.
_DRIFT_CTE = (
    "WITH desired AS ( "
    "  SELECT id, vendor_id, first_seen_at, bulk_cluster AS stored, "
    "         (count(*) OVER (PARTITION BY vendor_id, first_seen_at) >= %(min)s) AS want "
    "  FROM vendor_listings "
    "), drift AS ( "
    "  SELECT * FROM desired WHERE want IS DISTINCT FROM stored "
    ") "
)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Full-catalog bulk_cluster reconcile (dry run unless --apply)"
    )
    ap.add_argument("--apply", action="store_true",
                    help="perform the reconcile (default: dry run, no writes)")
    args = ap.parse_args()

    mode = "APPLY" if args.apply else "DRY RUN"
    params = {"min": BULK_CLUSTER_MIN}
    print(f"=== bulk_cluster audit — {mode}, N={BULK_CLUSTER_MIN} ===\n")

    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                _DRIFT_CTE
                + "SELECT count(*) FILTER (WHERE want AND NOT stored) AS to_true, "
                "       count(*) FILTER (WHERE stored AND NOT want) AS to_false "
                "FROM drift",
                params,
            )
            d = cur.fetchone()
        to_true = d["to_true"] or 0
        to_false = d["to_false"] or 0

        if to_true == 0 and to_false == 0:
            print("0 drifted rows — bulk_cluster is reconciled. Exiting clean.")
            return 0

        print(f"drift: {to_true} row(s) false->true, {to_false} row(s) true->false\n")

        # Per-vendor breakdown of the drift, by direction — the eyeball artifact.
        with conn.cursor() as cur:
            cur.execute(
                _DRIFT_CTE
                + "SELECT v.slug, "
                "       count(*) FILTER (WHERE drift.want) AS to_true, "
                "       count(*) FILTER (WHERE NOT drift.want) AS to_false "
                "FROM drift JOIN vendors v ON v.id = drift.vendor_id "
                "GROUP BY v.slug ORDER BY v.slug",
                params,
            )
            by_vendor = cur.fetchall()
        for r in by_vendor:
            print(f"  {r['slug']:<14} false->true={r['to_true']:<5} true->false={r['to_false']}")
        print()

        if to_false:
            print(f"NOTE: {to_false} true->false correction(s) — bulk_cluster is a pure "
                  "function of immutable (vendor_id, first_seen_at), so this is rare; it "
                  "means a prior write-side flag or an N change, which this reconcile heals.\n")

        if not args.apply:
            print(f"DRY RUN: {to_true + to_false} row(s) would reconcile. "
                  "Re-run with --apply to commit.")
            return 0

        with conn.cursor() as cur:
            cur.execute(
                _DRIFT_CTE
                + "UPDATE vendor_listings vl SET bulk_cluster = drift.want "
                "FROM drift WHERE vl.id = drift.id",
                params,
            )
            flipped = cur.rowcount
        print(f"APPLY: reconciled {flipped} row(s)")

        # Post-verify — the drift set must now be empty (idempotency proof).
        with conn.cursor() as cur:
            cur.execute(
                _DRIFT_CTE + "SELECT count(*) AS residual FROM drift",
                params,
            )
            residual = cur.fetchone()["residual"]
        if residual:
            print(f"WARN: {residual} row(s) still drifted post-UPDATE")
            return 1
        print("post-UPDATE verify: 0 drifted rows remain (idempotent).")

    return 0


if __name__ == "__main__":
    sys.exit(main())
