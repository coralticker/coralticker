"""Fleet-wide staleness cap — flip in_stock=false on listings a vendor stopped
serving but never OOS-flipped (CTK-189).

The problem (cohort-exclusion freeze): a row that leaves a vendor's admitted
set is added to ParseResult.filtered_urls and excluded from the cohort
absent-set (DR #83 / CTK-094 fold #4), so the go-forward delisting cycle never
OOS-flips it. It sits in_stock=true forever, showing wrong availability — an
aggregator trust-floor issue (feedback_aggregator_staleness_tier_floor). Same
"filter doesn't self-clean" mechanism CTK-181 hit.

This tool caps that staleness: any in_stock row last seen more than N days ago
whose vendor HAS scraped successfully since (so the row genuinely left the
catalog, not "we haven't looked") is flipped to in_stock=false.

  UPDATE vendor_listings vl SET in_stock = false
  WHERE vl.in_stock
    AND vl.last_seen_at < now() - make_interval(days => :N)
    AND EXISTS (SELECT 1 FROM scraper_runs sr
                WHERE sr.vendor_id = vl.vendor_id AND sr.status = 'success'
                  AND sr.started_at > vl.last_seen_at);

The EXISTS clause is the safety core — do NOT weaken it to "vendor scraped in
the last 3 days." It encodes "the vendor scraped successfully AFTER this row
was last seen, yet didn't re-see it." Without it, a vendor outage (no
successful run for N days) would mass-flip the entire catalog OOS — a Tier-1A
wrong-availability event. With it, an outage flips nothing.

Properties:
  - Reversible / self-healing: a wrong flip auto-corrects on the next scrape —
    when the vendor re-lists the slug, the diff cycle's restock UPSERT sets
    in_stock=true again. No DELETE; a flippable boolean. This is why a cap (not
    a delete) is correct for the stale-availability class.
  - Idempotent: a second run finds nothing (flipped rows are no longer
    in_stock).
  - Operational, re-runnable indefinitely (hence the un-prefixed name, vs. the
    one-shot ctkNNN_*.py backfills). Built scheduler-ready (clean exit codes,
    --apply flag) so a future GH Action cron (off the scrape windows per
    feedback_yaml_state_cron_window_risk) is pure wiring — NOT in CTK-189
    scope.

Default run is a DRY RUN — prints the per-vendor before-count + the candidate
rows for the pre-push eyeball and writes nothing. Pass --apply to flip.

Run OUTSIDE a scrape window: a concurrent persist could re-touch last_seen_at
mid-run (feedback_yaml_state_cron_window_risk).

Run via:
  python -m scrapers.tools.staleness_cap            # dry run, N=21
  python -m scrapers.tools.staleness_cap --apply    # flip
  python -m scrapers.tools.staleness_cap --days 30  # different threshold

Exit codes: 0 on success (dry run or apply), 1 on a post-verify residual.
"""

from __future__ import annotations

import argparse
import sys

from scrapers.common import db

DEFAULT_DAYS = 21


def _positive_int(raw: str) -> int:
    """argparse type for --days: reject non-positive input.

    A zero or negative N inverts make_interval(days => N), so the cap
    predicate's `last_seen_at < now() - interval` flips to matching present /
    future rows and mass-flips in_stock=false fleet-wide. Harmless under the
    dry-run default, but load-bearing once this runs --apply UNATTENDED on cron
    (CTK-190) — that is exactly where a fat-fingered or env-injected --days
    bites with no eyeball to catch it. argparse turns the ArgumentTypeError
    into a parser.error() exit(2) during parse_args(), before any DB
    connection opens, so a bad value can never reach the UPDATE.
    """
    try:
        n = int(raw)
    except ValueError:
        raise argparse.ArgumentTypeError(f"--days must be an integer, got {raw!r}")
    if n < 1:
        raise argparse.ArgumentTypeError(
            f"--days must be a positive integer (>= 1), got {n}"
        )
    return n

# The cap predicate, shared verbatim between the candidate SELECT and the
# UPDATE so the dry-run preview can never diverge from what --apply flips.
_PREDICATE = (
    "vl.in_stock "
    "AND vl.last_seen_at < now() - make_interval(days => %(days)s) "
    "AND EXISTS (SELECT 1 FROM scraper_runs sr "
    "            WHERE sr.vendor_id = vl.vendor_id AND sr.status = 'success' "
    "              AND sr.started_at > vl.last_seen_at)"
)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Fleet-wide staleness cap (dry run unless --apply)"
    )
    ap.add_argument("--apply", action="store_true",
                    help="perform the flip (default: dry run, no writes)")
    ap.add_argument("--days", type=_positive_int, default=DEFAULT_DAYS,
                    help=f"staleness threshold in days, positive int "
                         f"(default: {DEFAULT_DAYS})")
    args = ap.parse_args()

    mode = "APPLY" if args.apply else "DRY RUN"
    print(f"=== staleness cap — {mode}, N={args.days} days ===\n")

    params = {"days": args.days}

    with db.get_conn() as conn:
        with conn.cursor() as cur:
            # Candidate rows (the eyeball artifact). matched flag surfaces any
            # real named coral in the set — today 0, but the tool runs forever:
            # a future real coral that genuinely left a catalog SHOULD flip OOS,
            # so a non-zero matched count is informational, not an abort.
            cur.execute(
                "SELECT vl.id, v.slug, vl.category, vl.named_coral_id, "
                "       vl.last_seen_at::date AS last_seen, vl.raw_title "
                "FROM vendor_listings vl JOIN vendors v ON v.id = vl.vendor_id "
                f"WHERE {_PREDICATE} "
                "ORDER BY v.slug, vl.id",
                params,
            )
            candidates = cur.fetchall()

        if not candidates:
            print("no stale in_stock rows match — nothing to cap. Exiting clean.")
            return 0

        # Per-vendor before-count summary.
        by_vendor: dict[str, list] = {}
        for r in candidates:
            by_vendor.setdefault(r["slug"], []).append(r)
        matched = sum(1 for r in candidates if r["named_coral_id"] is not None)
        print(f"candidates: {len(candidates)} stale in_stock row(s) across "
              f"{len(by_vendor)} vendor(s); {matched} matched to a named coral")
        for slug in sorted(by_vendor):
            print(f"  {slug}: {len(by_vendor[slug])}")
        print()

        for slug in sorted(by_vendor):
            print(f"--- {slug} ---")
            for r in by_vendor[slug]:
                tag = f" coral={r['named_coral_id']}" if r["named_coral_id"] else ""
                print(f"  id={r['id']:>7}  last_seen={r['last_seen']}  "
                      f"cat={str(r['category']):<10}{tag}  {r['raw_title'][:55]!r}")
        print()

        if args.apply:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE vendor_listings vl SET in_stock = false WHERE {_PREDICATE}",
                    params,
                )
                flipped = cur.rowcount
            print(f"APPLY: flipped {flipped} row(s) to in_stock=false")

            # Post-verify — the predicate must now match 0 (idempotency proof).
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT count(*) AS c FROM vendor_listings vl WHERE {_PREDICATE}",
                    params,
                )
                residual = cur.fetchone()["c"]
            if residual:
                print(f"WARN: {residual} candidate row(s) still match post-UPDATE")
                return 1
            print("post-UPDATE verify: 0 candidates remain (idempotent)")
        else:
            print(f"DRY RUN: {len(candidates)} row(s) would flip to in_stock=false. "
                  "Re-run with --apply to commit.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
