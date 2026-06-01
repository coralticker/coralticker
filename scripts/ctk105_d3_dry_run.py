"""CTK-105 D-3 — per-vendor cohort-OOS dry-run (write-zero).

Enumerates the absent-set per CTK-094 §3 cohort-OOS semantics for each of
the 8 in-scope vendors (the non-opted-in fleet). The absent-set is the
proxy for "URLs the next cohort-OOS-at-persist scrape would flip to
in_stock=false."

Mechanism (matches pre-flight probe predicate at plan.md §Pre-flight DB
probe so D-3 counts reconcile with the 1,170/202/96/89/69/34/4/1 table):

  ABSENT_SET(vendor) = { vendor_listings.id
                        WHERE vendor_id = V
                          AND in_stock = true
                          AND last_seen_at < last_success.finished_at - 5min }

where `last_success` is the most recent scraper_runs row for that vendor
with status='success' AND finished_at IS NOT NULL.

Per-vendor stdout block emits count + each row's (id, product_url,
raw_title, last_seen_at, current_price). /lead-backend then samples 10
URLs per vendor (5 random + 5 highest current_price) for sign-off review
BEFORE the YAML `cohort_oos_at_persist: true` edit lands.

WRITE-ZERO. No DB writes, no YAML edits, no scraper firing. Polite-fetch
side: NONE. This script is DB-only.

Sequencing per plan §Fix shape D-4 — TSA first (24h canary), then BC, PE,
JF, UC; Vivid + RC fold; WWC last conditional on D-2 clearance. This
script enumerates all 8 in one pass for reconciliation against the
pre-flight probe; the per-vendor flip sequence happens downstream of
/lead-backend sign-off.

Reads NEON_DATABASE_URL via scrapers.common.db's load_dotenv side effect
(CLAUDE.md canonical path).
"""

from __future__ import annotations

import argparse
import math
import random
import sys
from collections import Counter
from pathlib import Path

import yaml

from scrapers.common.db import get_conn

# --classify mode reuses the D-2 classifier so the per-URL polite-fetch
# shape stays identical across D-2 (WWC, 20-URL sweep) and D-3 (7 vendors,
# 10-URL / all-rows sample-check). Single source of truth for the
# (product_type_allowlist | tag_allowlist | tag_denylist) shape.
from scripts.ctk105_d2_wwc_diagnostic import classify_url

STALENESS_JITTER_MIN = 5  # tolerance against last_success.finished_at; matches pre-flight probe
RNG_SEED = 42  # deterministic random_5 sample per /lead-backend disposition 2026-06-01
SAMPLE_TOP_N = 5
SAMPLE_RANDOM_N = 5
DRIFT_PCT_THRESHOLD = 0.10  # >10% drift surfaces; ±5% is the acceptable band
DRIFT_ROW_FLOOR = 2  # tiny-count vendors (RC=1, Vivid=4) don't flap on 1-row noise

# --classify mode disposition thresholds per plan §Fix shape D-3:
#   TIER-A: >=9/10 delisted = PROCEED (strict; <9 = STOP, surface for re-classification)
#   TIER-B: >=75% delisted = PROCEED (rounded up — 3/4 for Vivid, 1/1 for RC)
TIER_A_DELISTED_THRESHOLD = 9
TIER_B_DELISTED_FRACTION = 0.75
VENDOR_YAML_DIR = Path(__file__).parent.parent / "scrapers" / "vendors"
SKIP_CLASSIFY_VENDORS = {"wwc"}  # D-2's 20-URL sweep subsumes the 10-URL D-3 sample-check

# (vendor_id, slug, tier, expected_stale_pre_flight)
# Sequenced per plan §Fix shape D-4 — TSA canary first, then TIER-A batch,
# TIER-B fold, WWC last conditional on D-2. Order here is reporting/output
# only; the YAML flip cadence is set by /lead-backend sign-off per vendor.
VENDORS = [
    (3,  "tsa",            "TIER-A canary",        202),
    (5,  "battlecorals",   "TIER-A",                34),
    (1,  "pacific_east",   "TIER-A",                69),
    (4,  "jf",             "TIER-A",                89),
    (6,  "unique_corals",  "TIER-A",                96),
    (8,  "vivid_aquariums","TIER-B fold",            4),
    (9,  "reef_chasers",   "TIER-B fold",            1),
    (2,  "wwc",            "TIER-C (D-2-gated)", 1170),
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--classify",
        action="store_true",
        help="Per-vendor live polite-fetch + classifier (D-3 sample-check mode). "
             "Polite-fetches 10 URLs per TIER-A vendor (top-5 by price + random-5 "
             "seed=42, deduplicated) and all rows per TIER-B vendor. WWC skipped "
             "(D-2 subsumed). Emits per-vendor classification table + disposition "
             "verdict per plan §Fix shape D-3 sign-off rule.",
    )
    args = parser.parse_args()

    if args.classify:
        _main_classify_mode()
        return

    print("=" * 78)
    print("CTK-105 D-3 — per-vendor cohort-OOS dry-run (write-zero)")
    print(f"staleness jitter: {STALENESS_JITTER_MIN} min vs. last_success.finished_at")
    print("=" * 78)

    grand_total = 0
    drift_flags: list[str] = []
    rng = random.Random(RNG_SEED)

    with get_conn() as conn:
        for vendor_id, slug, tier, expected in VENDORS:
            count, last_success_run = _report_vendor(conn, vendor_id, slug, tier, expected, rng)
            grand_total += count
            drift = abs(count - expected)
            drift_threshold = max(DRIFT_ROW_FLOOR, int(DRIFT_PCT_THRESHOLD * expected))
            if drift > drift_threshold:
                drift_flags.append(
                    f"  {slug:<18}  expected={expected:>5}  got={count:>5}  "
                    f"drift={drift:>5}  (>10% AND >{DRIFT_ROW_FLOOR} rows; "
                    f"surface to /lead-backend before YAML flip)"
                )

    print()
    print("=" * 78)
    print(f"GRAND TOTAL would-flip rows across 8 vendors: {grand_total}")
    print(f"  Pre-flight probe expected total: 1,665")
    print("=" * 78)
    if drift_flags:
        print()
        print("DRIFT FLAGS (count drift vs. 2026-06-01 17:35 UTC pre-flight probe):")
        for line in drift_flags:
            print(line)
        print()
        print("Drift is expected within the cron-window since the pre-flight "
              "probe — newly-stale rows accumulate, newly-restocked rows drop "
              "out. Flag for /lead-backend if drift is large or directional.")


def _report_vendor(conn, vendor_id: int, slug: str, tier: str, expected: int, rng: random.Random) -> tuple[int, int | None]:
    print()
    print("=" * 78)
    print(f"=== vendor_id={vendor_id} slug={slug} tier={tier} ===")
    print("=" * 78)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, finished_at "
            "FROM scraper_runs "
            "WHERE vendor_id = %s AND status = 'success' AND finished_at IS NOT NULL "
            "ORDER BY id DESC "
            "LIMIT 1",
            (vendor_id,),
        )
        last = cur.fetchone()

    if last is None:
        print(f"  ERROR: no successful scraper run for vendor {slug!r}; cannot "
              "define stale predicate. Skipping.")
        return (0, None)

    last_success_id = last["id"]
    last_success_finished = last["finished_at"]
    print(f"  last_success: run_id={last_success_id}  "
          f"finished_at={last_success_finished.isoformat()}")
    print(f"  predicate: in_stock=true AND last_seen_at < "
          f"({last_success_finished.isoformat()}) - {STALENESS_JITTER_MIN}min")
    print(f"  pre-flight expected count: {expected}")

    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, product_url, raw_title, current_price, last_seen_at "
            "FROM vendor_listings "
            "WHERE vendor_id = %s "
            "  AND in_stock = true "
            "  AND last_seen_at < %s - INTERVAL '%s minutes' "
            "ORDER BY current_price DESC NULLS LAST, id",
            (vendor_id, last_success_finished, STALENESS_JITTER_MIN),
        )
        rows = cur.fetchall()

    print(f"  WOULD-FLIP COUNT: {len(rows)}")
    if not rows:
        print("  (no rows — vendor already clean against the last successful scrape)")
        return (0, last_success_id)

    # /lead-backend sample-check shape per plan §Fix shape D-3: 5 highest
    # current_price (blast-radius if misflipped) + 5 random (representative
    # of the bulk). Pre-formatted both blocks here so /lead-backend pastes
    # 10 URLs per vendor directly into the polite-fetch step.
    top_5 = rows[:SAMPLE_TOP_N]
    random_pool = list(rows)
    if len(random_pool) <= SAMPLE_RANDOM_N:
        random_5 = random_pool
    else:
        random_5 = rng.sample(random_pool, SAMPLE_RANDOM_N)

    print()
    print(f"  --- SAMPLE-CHECK BLOCK A: top {SAMPLE_TOP_N} by current_price ---")
    _print_rows(top_5)
    print()
    print(f"  --- SAMPLE-CHECK BLOCK B: random {SAMPLE_RANDOM_N} "
          f"(seed={RNG_SEED}, deterministic across reruns) ---")
    _print_rows(random_5)

    print()
    print(f"  --- FULL would-flip rowset ({len(rows)} rows, sorted "
          f"current_price DESC NULLS LAST, id ASC) ---")
    _print_rows(rows)

    return (len(rows), last_success_id)


def _print_rows(rows: list[dict]) -> None:
    print(f"  {'id':>6}  {'current_price':>13}  {'last_seen_at':<26}  "
          f"raw_title / product_url")
    print(f"  {'-'*6}  {'-'*13}  {'-'*26}  -----")
    for r in rows:
        price = f"{r['current_price']:>13}" if r['current_price'] is not None else f"{'(null)':>13}"
        last_seen = r["last_seen_at"].isoformat() if r["last_seen_at"] else "(none)"
        title = (r["raw_title"] or "")[:60]
        print(f"  {r['id']:>6}  {price}  {last_seen:<26}  {title!r}")
        print(f"                                                       "
              f"{r['product_url']}")


def _main_classify_mode() -> None:
    """--classify mode: per-vendor live polite-fetch + classifier across
    the 7 sample-check vendors (WWC skipped per D-2 subsumption). Polite-
    fetch budget ~55 URLs × per-vendor request_delay_sec ≈ ~2 minutes.

    Plan §Fix shape D-3 disposition rule per vendor:
      TIER-A: >=9/10 classified `delisted` -> PROCEED to D-4 YAML flip;
              <9/10 -> STOP, surface to /lead-backend for re-classification.
      TIER-B: >=75% (rounded up) classified `delisted` -> PROCEED;
              <75% -> STOP, surface to /lead-backend.

    Per memory `feedback_aggregator_staleness_tier_floor.md`: an `oos_at_
    vendor` row (200 + would-pass filter + no variants available) is ALSO
    a correct cohort-OOS flip target. Report it separately so /lead-backend
    can judge breakdowns; verdict uses STRICT `delisted` count per directive.
    """
    print("=" * 78)
    print("CTK-105 D-3 --classify — per-vendor sample-check polite-fetch")
    print(f"  classifier: shared with D-2 (Shopify .json GET, "
          f"per-vendor request_delay_sec, YAML category_filter)")
    print(f"  RNG seed: {RNG_SEED} (deterministic across reruns)")
    print(f"  TIER-A disposition: >={TIER_A_DELISTED_THRESHOLD}/10 delisted = PROCEED")
    print(f"  TIER-B disposition: >={TIER_B_DELISTED_FRACTION:.0%} delisted = PROCEED")
    print(f"  SKIP: {sorted(SKIP_CLASSIFY_VENDORS)} (D-2 subsumed)")
    print("=" * 78)

    rng = random.Random(RNG_SEED)
    verdicts: list[tuple[str, str, str]] = []  # (slug, verdict, summary)

    with get_conn() as conn:
        for vendor_id, slug, tier, expected in VENDORS:
            if slug in SKIP_CLASSIFY_VENDORS:
                print()
                print(f"=== {slug} ({tier}) — SKIPPED (D-2 subsumed) ===")
                verdicts.append((slug, "N/A", "D-2 subsumed (20/20 delisted, PROCEED)"))
                continue
            verdict, summary = _classify_vendor(conn, vendor_id, slug, tier, rng)
            verdicts.append((slug, verdict, summary))

    print()
    print("=" * 78)
    print("Per-vendor disposition roll-up")
    print("=" * 78)
    print(f"  {'slug':<18}  {'verdict':<10}  summary")
    print(f"  {'-'*18}  {'-'*10}  -----")
    for slug, verdict, summary in verdicts:
        print(f"  {slug:<18}  {verdict:<10}  {summary}")

    stops = [s for s, v, _ in verdicts if v == "STOP"]
    if stops:
        print()
        print(f"STOP-vendors: {stops} — surface to /lead-backend for re-classification "
              "BEFORE YAML flip.")
    else:
        print()
        print("All non-skipped vendors PROCEED-cleared. HOLD on YAML flips pending "
              "/lead-backend explicit per-vendor sign-off.")


def _classify_vendor(
    conn,
    vendor_id: int,
    slug: str,
    tier: str,
    rng: random.Random,
) -> tuple[str, str]:
    print()
    print("=" * 78)
    print(f"=== vendor_id={vendor_id} slug={slug} tier={tier} ===")
    print("=" * 78)

    yaml_path = VENDOR_YAML_DIR / f"{slug}.yaml"
    cfg = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    request_delay = float(cfg.get("request_delay_sec", 2.0))
    cf = cfg.get("category_filter") or {}
    print(f"  YAML: {yaml_path.name}  request_delay_sec={request_delay}")
    print(f"  category_filter shape: "
          f"product_type_allowlist={'yes' if 'product_type_allowlist' in cf else 'no'}  "
          f"tag_allowlist={'yes' if 'tag_allowlist' in cf else 'no'}  "
          f"tag_denylist_n={len(cf.get('tag_denylist') or [])}")

    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, finished_at "
            "FROM scraper_runs "
            "WHERE vendor_id = %s AND status = 'success' AND finished_at IS NOT NULL "
            "ORDER BY id DESC LIMIT 1",
            (vendor_id,),
        )
        last = cur.fetchone()
    if last is None:
        print(f"  ERROR: no successful scraper run for vendor {slug!r}; cannot define stale predicate.")
        return ("STOP", "no successful scraper run; cannot sample")
    last_success_finished = last["finished_at"]

    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, product_url, raw_title, current_price, last_seen_at "
            "FROM vendor_listings "
            "WHERE vendor_id = %s "
            "  AND in_stock = true "
            "  AND last_seen_at < %s - INTERVAL '%s minutes' "
            "ORDER BY current_price DESC NULLS LAST, id",
            (vendor_id, last_success_finished, STALENESS_JITTER_MIN),
        )
        rows = cur.fetchall()

    if not rows:
        print(f"  no would-flip rows; nothing to classify")
        return ("N/A", "0 stale rows; clean against last successful scrape")

    sample = _pick_classify_sample(rows, tier, rng)
    print(f"  absent-set: {len(rows)} rows; classify-sample: {len(sample)} URLs "
          f"({'top-5 + random-5 deduped, capped 10' if tier.startswith('TIER-A') else 'ALL rows per tier-B'})")
    print()

    counts: Counter[str] = Counter()
    rows_with_class: list[tuple[dict, str, str]] = []
    print(f"  Polite-fetch loop (request_delay_sec={request_delay}; total ~{len(sample) * request_delay:.0f}s + RTT):")
    for idx, row in enumerate(sample, start=1):
        klass, detail = classify_url(row["product_url"], request_delay, cf)
        counts[klass] += 1
        rows_with_class.append((row, klass, detail))
        price_str = f"${row['current_price']}" if row['current_price'] is not None else "(null)"
        print(f"  [{idx:>2}/{len(sample)}] {klass:<20}  id={row['id']:>6}  "
              f"price={price_str:<10}  url={row['product_url']}")
        print(f"           title:  {(row.get('raw_title') or '')[:70]!r}")
        print(f"           detail: {detail}")

    delisted = counts.get("delisted", 0)
    oos = counts.get("oos_at_vendor", 0)
    filter_edge = counts.get("parser_filter_edge", 0)
    under = counts.get("under_intake", 0)
    errors = counts.get("error", 0)
    print()
    print(f"  Classification roll-up:")
    print(f"    delisted             {delisted:>3} / {len(sample)}")
    print(f"    oos_at_vendor        {oos:>3} / {len(sample)}   (200 + would-pass filter + no variant)")
    print(f"    parser_filter_edge   {filter_edge:>3} / {len(sample)}   (200 + filtered by YAML category_filter)")
    print(f"    under_intake         {under:>3} / {len(sample)}   (200 + would-pass + buyable; opt-in risk)")
    print(f"    error                {errors:>3} / {len(sample)}")
    safe_to_flip = delisted + oos
    print(f"    [delisted + oos_at_vendor combined safe-to-flip count: {safe_to_flip} / {len(sample)}]")

    if tier.startswith("TIER-A"):
        verdict = "PROCEED" if delisted >= TIER_A_DELISTED_THRESHOLD else "STOP"
        summary = (f"TIER-A: {delisted}/10 delisted vs. >={TIER_A_DELISTED_THRESHOLD} required; "
                   f"safe-to-flip combined={safe_to_flip}/10; under_intake={under}")
    elif tier.startswith("TIER-B"):
        threshold = max(1, math.ceil(TIER_B_DELISTED_FRACTION * len(sample)))
        verdict = "PROCEED" if delisted >= threshold else "STOP"
        summary = (f"TIER-B: {delisted}/{len(sample)} delisted vs. >={threshold} required "
                   f"({TIER_B_DELISTED_FRACTION:.0%} rounded up); safe-to-flip combined={safe_to_flip}/{len(sample)}; "
                   f"under_intake={under}")
    else:
        verdict = "N/A"
        summary = f"tier {tier} not gated by --classify"

    print()
    print(f"  DISPOSITION: {verdict} — {summary}")
    if under > 0:
        print(f"  WARNING: under_intake count > 0 — this is the catastrophic-misflip "
              f"class; STOP-class regardless of delisted count.")
        verdict = "STOP"
        summary = "under_intake > 0; cohort-OOS opt-in would mass-misflip; " + summary
    if errors > 0:
        print(f"  WARNING: error count > 0 — review per-URL detail above; "
              f"re-run may resolve transient network errors.")

    return (verdict, summary)


def _pick_classify_sample(rows: list[dict], tier: str, rng: random.Random) -> list[dict]:
    """Per-vendor classify sample:
      TIER-A: top-5 by current_price (already sorted DESC) + random-5 from
              the full rowset, deduplicated on id, capped at 10.
      TIER-B: all rows (4 for Vivid, 1 for RC).
    """
    if tier.startswith("TIER-B"):
        return list(rows)
    top_5 = rows[:SAMPLE_TOP_N]
    if len(rows) <= SAMPLE_RANDOM_N:
        random_5 = list(rows)
    else:
        random_5 = rng.sample(rows, SAMPLE_RANDOM_N)
    seen_ids: set[int] = set()
    combined: list[dict] = []
    for r in top_5 + random_5:
        if r["id"] in seen_ids:
            continue
        seen_ids.add(r["id"])
        combined.append(r)
    return combined


if __name__ == "__main__":
    main()
