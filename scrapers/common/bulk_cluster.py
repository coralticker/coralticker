"""Single source of truth for the bulk_cluster disposition (CTK-198).

`bulk_cluster` flags a `vendor_listings` row whose `(vendor_id, first_seen_at)`
cohort has at least `BULK_CLUSTER_MIN` rows — a single-timestamp batch dump (a
vendor re-index or onboarding flood) that the median-relative CTK-191 guard
misses (it catches only the 3 largest per-day cohorts; high-volume same-second
dumps like WWC 175 @ 06-20 15:25:39 or AquaSD 153 slip through as `kept`).

Why a persisted column and not another read-side predicate: `bulk_cluster` is a
pure function of IMMUTABLE `(vendor_id, first_seen_at)`. A row's cohort never
changes after the scrape that wrote it (`first_seen_at` is write-once — DB
DEFAULT now() on INSERT, never touched on UPDATE, plus the
`preserve_first_seen_at` trigger), so the boolean persists cleanly. This is
exactly why it does NOT subsume the existing `cold_start` / `bulk_relist`
dispositions — those are median-relative (a 30-day trailing window that moves
daily), so a fixed row's disposition changes over time and can't be stably
persisted (the `is_auction` trap). `bulk_cluster` is orthogonal and additive.

Maintained by two writers over the ONE threshold defined here:
  - write-time, vendor-scoped, false->true only (diff.persist_phase_a hook) —
    immediacy, so a noon re-index is flagged before the next request;
  - nightly full-catalog `IS DISTINCT FROM` reconcile (bulk_cluster_audit.py) —
    the durable self-heal; the only writer permitted a true->false correction.
Plus the one-shot historical backfill (scripts/ctk198_bulk_cluster_backfill.py).

All three import `BULK_CLUSTER_MIN` from here — N lives in exactly one place, so
the write sites cannot drift against each other. The disposition READ path
(migration 0057 f7_arrivals_dispositioned, and CTK-197-stacked
get_aggregate_activity) reads the persisted boolean and carries no threshold at
all. A drift-guard test (scrapers/tests/test_bulk_cluster_drift_guard.py)
asserts the value here and that the write sites reference this constant rather
than a bare literal. See CTK-198 plan.md.
"""

from __future__ import annotations

import psycopg

# N = 50 (CTK-198, directive-locked). Audit-corrected: on the full catalog there
# is NO clean bimodal gap below 56 — cohort sizes run continuously 8->59. 50 is
# the only clean cut, at the 47->56 break, AFTER the median guard de-noises the
# 8-47 band. N=50 spares JF's 47-row same-second cohort (reads as a genuine drop).
#
# Live N=50 honest floor (2026-06-25, /lead-backend review-results PASS): 162
# just-listed / 190 F7-cover true_count (arrivals + restocks), down from the served
# ~745 — a ~74% correction. An earlier EXPLORATORY >=10 cut suggested ~57, but >=10
# sits inside the organic distribution (no clean gap below 50), so N=50 is the
# ratified threshold and 162/190 the ratified floor. (The 0056 migration header
# still reads the exploratory ~57 — frozen per apply-immutability; the corrected
# number lives here + in CTK-198 plan.md/results.md.)
BULK_CLUSTER_MIN = 50


def flip_new_bulk_clusters(conn: psycopg.Connection, vendor_id: int) -> int:
    """Write-time hook (CTK-198, item 5): after a vendor's scrape persists, flip
    `bulk_cluster` false->true for any `(vendor_id, first_seen_at)` cohort of this
    vendor that has crossed `BULK_CLUSTER_MIN`. Returns the rowcount flipped.

    MONOTONIC false->true only (mirrors the `is_auction` discipline at
    diff.py:357-368): the cohort key is immutable, so a crossed cohort stays
    crossed; the only legitimate true->false is a wrong flag, which the nightly
    audit's full-catalog reconcile owns — never this hook. Vendor-scoped (only
    this run's vendor can have gained rows), so it is cheap and touches no other
    vendor's rows. Best-effort: the caller runs it OUTSIDE the persist
    transaction (autocommit) and swallows exceptions — a missed flip self-heals
    at the nightly audit, so the scrape's success must not depend on it.

    Idempotent within a run: the `AND vl.bulk_cluster = false` guard makes a
    re-run a no-op once the cohort is flagged.
    """
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE vendor_listings vl SET bulk_cluster = true "
            "FROM ( "
            "  SELECT vendor_id, first_seen_at "
            "  FROM vendor_listings "
            "  WHERE vendor_id = %(vendor_id)s "
            "  GROUP BY vendor_id, first_seen_at "
            "  HAVING count(*) >= %(min)s "
            ") big "
            "WHERE vl.vendor_id = big.vendor_id "
            "  AND vl.first_seen_at = big.first_seen_at "
            "  AND vl.bulk_cluster = false",
            {"vendor_id": vendor_id, "min": BULK_CLUSTER_MIN},
        )
        return cur.rowcount
