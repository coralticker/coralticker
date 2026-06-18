"""Read-only prod characterization — CTK-161 velocity Gate 2 premise check.

Question: is sub-24h disappearance on the 8 fast-cadence vendors mostly TERMINAL
SALE-shaped, or fast NON-SALE churn / pull? price_history has no sale-vs-pull
discriminator column (and we deliberately do NOT build one here), so we bound the
answer with three proxies. The proxies CANNOT separate isolated-terminal sale from
isolated-terminal pull (the deferred discriminator); they bound the residual
mis-signal risk, they do not eliminate it.

Read-only: SELECTs only, no writes, no DDL. Canonical scrapers.common.db.get_conn
(NEON_DATABASE_URL via .env, architecture-v1.md decision #65). Run:
  PYTHONPATH=. .venv/bin/python scripts/diag_velocity_fast_oos.py

Vendor-set note: the directive calls these "the 8 hourly vendors," but in prod only
6 are cadence_label='hourly' (pacific_east, wwc, poto, reef_chasers, vivid_aquariums,
unique_corals); jf is 'drop-day-aware' and tsa is 'event-aware'. They are the 8
fast-cadence (sub-daily) vendors — the complement of the 3 daily vendors (aquasd,
battlecorals, tidal_gardens). Cadence matters for the ship call: "sub-24h" resolves
differently against an hourly cadence than a drop-day / event cadence.

Proxies (all over price_history, change-only — decision #7):
  1. Relist rate — of listings that went OOS within 24h of first_seen_at (the
     price_history first in-stock observation), what fraction later flipped back to
     in_stock (same listing_id)? Plus the named-coral variant: the same named_coral_id
     reappearing in-stock as a NEW listing_id at the same vendor within 7 days.
  2. Per-vendor flip churn — distribution of in_stock<->OOS transition counts per
     listing (median / p90 / max), over ALL listings with history.
  3. Bulk-simultaneous-OOS — for each fast-OOS event, how many OOS transitions hit
     the same vendor in the same scrape pass (scraper_run_id cluster)? Isolated
     (cluster size 1) vs bulk.

Decision rule (pre-stated, /lead-backend): low relist + low churn + rare-bulk ->
that vendor's fast-OOS is terminal-isolated -> velocity ships <=1-day for it;
high relist/churn/bulk -> hold. Per-vendor split is fine. This script SURFACES the
numbers + a PROPOSED (non-binding) classification; /lead-backend + /brand-manager
make the ship/hold call.
"""

from __future__ import annotations

import sys

from scrapers.common.db import get_conn

# Directive slug -> actual prod slug (hyphen vs underscore; vivid / unique full names).
WANTED = ["pacific_east", "wwc", "poto", "reef_chasers", "jf", "tsa",
          "vivid_aquariums", "unique_corals"]

# Proposed (non-binding) classification thresholds — surfaced for /lead-backend +
# /brand-manager to confirm or move. Chosen to read "mostly terminal-isolated."
RELIST_MAX = 0.10        # same-listing relist rate below this = "low relist"
CORAL_REAPPEAR_MAX = 0.20  # named-coral reappear-as-new rate below this = "low relist"
CHURN_MEDIAN_MAX = 2     # median per-listing in_stock transitions at/below this = "low churn"
CHURN_P90_MAX = 4        # p90 transitions at/below this = "low churn"
ISOLATED_MIN = 0.50      # >= this fraction of fast-OOS events isolated (pass cluster 1) = "rare bulk"
BULK_SIZE = 10           # a pass with >= this many OOS transitions is a "bulk" pass

WINDOW_CENSOR_DAYS = 7   # relist/reappear needs >= this much trailing observation to be fair


def _pct(xs, p):
    """Nearest-rank percentile (p in 0..100) over a list of numbers; 0 if empty."""
    if not xs:
        return 0
    s = sorted(xs)
    k = max(0, min(len(s) - 1, round((p / 100.0) * (len(s) - 1))))
    return s[k]


def _median(xs):
    return _pct(xs, 50)


def main() -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, slug, cadence_label FROM vendors WHERE slug = ANY(%s)", (WANTED,))
            vrows = cur.fetchall()
        vmap = {r["slug"]: r["id"] for r in vrows}
        cadence = {r["slug"]: r["cadence_label"] for r in vrows}
        inv = {i: s for s, i in vmap.items()}
        vids = list(vmap.values())
        missing = [s for s in WANTED if s not in vmap]
        if missing:
            print(f"WARN: unresolved slugs (skipped): {missing}")
        if not vids:
            print("ERROR: no vendors resolved")
            return 1

        with conn.cursor() as cur:
            cur.execute("SELECT MAX(observed_at) AS m FROM price_history")
            max_obs = cur.fetchone()["m"]
        print(f"price_history max observed_at: {max_obs}")
        print(f"censor cutoff for relist/reappear fairness: "
              f"events with first_oos_at <= max - {WINDOW_CENSOR_DAYS}d\n")

        # --- Query A: fast-OOS events, with relist / reappear / scrape-pass id -----
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH lfs AS (   -- first in-stock observation per listing (velocity first_seen)
                  SELECT ph.listing_id, vl.vendor_id, vl.named_coral_id,
                         MIN(ph.observed_at) FILTER (WHERE ph.in_stock) AS fs
                  FROM price_history ph JOIN vendor_listings vl ON vl.id = ph.listing_id
                  WHERE vl.vendor_id = ANY(%(vids)s)
                  GROUP BY ph.listing_id, vl.vendor_id, vl.named_coral_id
                ),
                fo AS (
                  SELECT lfs.listing_id AS lid, lfs.vendor_id, lfs.named_coral_id, lfs.fs,
                    (SELECT MIN(p.observed_at) FROM price_history p
                     WHERE p.listing_id = lfs.listing_id AND NOT p.in_stock AND p.observed_at > lfs.fs) AS foa
                  FROM lfs WHERE lfs.fs IS NOT NULL
                ),
                fast AS (
                  SELECT * FROM fo
                  WHERE foa IS NOT NULL AND foa - fs <= interval '24 hours'
                )
                SELECT f.lid, f.vendor_id, f.named_coral_id, f.fs, f.foa,
                  EXISTS (SELECT 1 FROM price_history p
                          WHERE p.listing_id = f.lid AND p.in_stock AND p.observed_at > f.foa) AS relisted,
                  (SELECT p.scraper_run_id FROM price_history p
                   WHERE p.listing_id = f.lid AND NOT p.in_stock AND p.observed_at = f.foa
                   ORDER BY p.id LIMIT 1) AS oos_run_id,
                  CASE WHEN f.named_coral_id IS NOT NULL THEN EXISTS (
                    SELECT 1 FROM lfs l2
                    WHERE l2.vendor_id = f.vendor_id AND l2.named_coral_id = f.named_coral_id
                      AND l2.listing_id <> f.lid
                      AND l2.fs > f.foa AND l2.fs <= f.foa + make_interval(days => %(cen)s)
                  ) ELSE NULL END AS coral_reappeared
                FROM fast f
                """,
                {"vids": vids, "cen": WINDOW_CENSOR_DAYS},
            )
            fast_rows = cur.fetchall()

        # --- Query B: per-listing in_stock transition counts (ALL listings) --------
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH seq AS (
                  SELECT ph.listing_id, vl.vendor_id, ph.in_stock,
                         lag(ph.in_stock) OVER (PARTITION BY ph.listing_id
                                                ORDER BY ph.observed_at, ph.id) AS prev
                  FROM price_history ph JOIN vendor_listings vl ON vl.id = ph.listing_id
                  WHERE vl.vendor_id = ANY(%s)
                )
                SELECT vendor_id, listing_id,
                       COUNT(*) FILTER (WHERE prev IS NOT NULL AND in_stock <> prev) AS transitions
                FROM seq GROUP BY vendor_id, listing_id
                """,
                (vids,),
            )
            churn_rows = cur.fetchall()

        # --- Query C: OOS-transition cluster size per (vendor, scrape pass) --------
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH seq AS (
                  SELECT ph.listing_id, vl.vendor_id, ph.in_stock, ph.scraper_run_id,
                         lag(ph.in_stock) OVER (PARTITION BY ph.listing_id
                                                ORDER BY ph.observed_at, ph.id) AS prev
                  FROM price_history ph JOIN vendor_listings vl ON vl.id = ph.listing_id
                  WHERE vl.vendor_id = ANY(%s)
                ),
                oos AS (
                  SELECT vendor_id, scraper_run_id FROM seq
                  WHERE prev IS TRUE AND in_stock = FALSE
                )
                SELECT vendor_id, scraper_run_id, COUNT(*) AS cluster_size
                FROM oos GROUP BY vendor_id, scraper_run_id
                """,
                (vids,),
            )
            cluster_rows = cur.fetchall()

    # cluster lookup: (vendor_id, run_id) -> OOS-transition count in that pass
    cluster = {(r["vendor_id"], r["scraper_run_id"]): r["cluster_size"] for r in cluster_rows}

    churn_by_vendor: dict[int, list[int]] = {}
    for r in churn_rows:
        churn_by_vendor.setdefault(r["vendor_id"], []).append(r["transitions"])

    fast_by_vendor: dict[int, list[dict]] = {}
    for r in fast_rows:
        fast_by_vendor.setdefault(r["vendor_id"], []).append(r)

    censor_cut = max_obs - __import__("datetime").timedelta(days=WINDOW_CENSOR_DAYS)

    def vendor_block(vid):
        slug = inv[vid]
        fast = fast_by_vendor.get(vid, [])
        n_fast = len(fast)
        # proxy 1 — same-listing relist
        relisted = sum(1 for r in fast if r["relisted"])
        eligible = [r for r in fast if r["foa"] <= censor_cut]
        relisted_elig = sum(1 for r in eligible if r["relisted"])
        # named-coral reappearance (over named fast events; censored subset)
        named = [r for r in fast if r["coral_reappeared"] is not None]
        named_elig = [r for r in named if r["foa"] <= censor_cut]
        reappeared_elig = sum(1 for r in named_elig if r["coral_reappeared"])
        # proxy 2 — churn
        ch = churn_by_vendor.get(vid, [])
        ch_med, ch_p90, ch_max = _median(ch), _pct(ch, 90), (max(ch) if ch else 0)
        churny = sum(1 for x in ch if x >= 3)
        churny_pct = churny / len(ch) if ch else 0.0
        # proxy 3 — bulk
        sizes = [cluster.get((vid, r["oos_run_id"]), None) for r in fast]
        sizes = [s for s in sizes if s is not None]
        isolated = sum(1 for s in sizes if s == 1)
        bulk = sum(1 for s in sizes if s >= BULK_SIZE)
        iso_frac = isolated / len(sizes) if sizes else 0.0
        bulk_frac = bulk / len(sizes) if sizes else 0.0
        cl_med = _median(sizes)
        # pass concentration: how many DISTINCT scrape passes hold the fast-OOS
        # events, and what share sits in the single largest pass. 1-2 mega-passes =
        # artifact-like (one mass event); many moderate passes = recurring drops.
        passes = [r["oos_run_id"] for r in fast if r["oos_run_id"] is not None]
        n_passes = len(set(passes))
        from collections import Counter as _C
        biggest = max(_C(passes).values()) if passes else 0
        biggest_frac = biggest / n_fast if n_fast else 0.0

        relist_rate = relisted_elig / len(eligible) if eligible else 0.0
        reappear_rate = reappeared_elig / len(named_elig) if named_elig else 0.0

        # proposed (non-binding) classification
        low_relist = relist_rate < RELIST_MAX and reappear_rate < CORAL_REAPPEAR_MAX
        low_churn = ch_med <= CHURN_MEDIAN_MAX and ch_p90 <= CHURN_P90_MAX
        rare_bulk = iso_frac >= ISOLATED_MIN
        ship = low_relist and low_churn and rare_bulk
        verdict = "SHIP <=1d" if ship else "HOLD"
        if n_fast == 0:
            verdict = "n/a (0 fast-OOS)"

        print(f"=== {slug}  ({cadence.get(slug,'?')})  vid={vid} ===")
        print(f"  fast-OOS events (<=24h): {n_fast}  | listings-with-history: {len(ch)}")
        if n_fast:
            print(f"      pass concentration: {n_passes} distinct scrape pass(es); "
                  f"largest holds {biggest}/{n_fast} = {biggest_frac:.0%} of fast events")
        print(f"  [1] relist same-listing: {relisted}/{n_fast} raw"
              f"  | censored(>= {WINDOW_CENSOR_DAYS}d trailing): {relisted_elig}/{len(eligible)} "
              f"= {relist_rate:.0%}")
        print(f"      named-coral reappear-as-new (7d, censored): {reappeared_elig}/{len(named_elig)} "
              f"= {reappear_rate:.0%}  (named fast events: {len(named)})")
        print(f"  [2] churn transitions/listing: median={ch_med} p90={ch_p90} max={ch_max} "
              f"| churny(>=3 flips)={churny_pct:.0%}")
        print(f"  [3] same-pass OOS cluster: median={cl_med}  isolated(size1)={isolated} "
              f"({iso_frac:.0%})  bulk(>={BULK_SIZE})={bulk} ({bulk_frac:.0%})")
        print(f"      de-bulk residual (isolated fast events over ~45d): {isolated}")
        print(f"  -> proposed: low_relist={low_relist} low_churn={low_churn} rare_bulk={rare_bulk}"
              f"  =>  {verdict}\n")

        return dict(slug=slug, n_fast=n_fast, relist_rate=relist_rate, reappear_rate=reappear_rate,
                    ch_med=ch_med, ch_p90=ch_p90, iso_frac=iso_frac, bulk_frac=bulk_frac, verdict=verdict)

    print("=" * 72)
    print("PER-VENDOR")
    print("=" * 72)
    results = [vendor_block(vid) for vid in sorted(vids, key=lambda i: inv[i])]

    # aggregate
    all_fast = [r for rows in fast_by_vendor.values() for r in rows]
    all_ch = [x for xs in churn_by_vendor.values() for x in xs]
    n = len(all_fast)
    elig = [r for r in all_fast if r["foa"] <= censor_cut]
    rel = sum(1 for r in elig if r["relisted"])
    named = [r for r in all_fast if r["coral_reappeared"] is not None and r["foa"] <= censor_cut]
    rea = sum(1 for r in named if r["coral_reappeared"])
    sizes = [cluster.get((r["vendor_id"], r["oos_run_id"])) for r in all_fast]
    sizes = [s for s in sizes if s is not None]
    iso = sum(1 for s in sizes if s == 1)
    blk = sum(1 for s in sizes if s >= BULK_SIZE)
    print("=" * 72)
    print("AGGREGATE (all 8)")
    print("=" * 72)
    print(f"  fast-OOS events: {n}")
    print(f"  [1] relist same-listing (censored): {rel}/{len(elig)} = "
          f"{(rel/len(elig) if elig else 0):.0%}")
    print(f"      named-coral reappear (censored): {rea}/{len(named)} = "
          f"{(rea/len(named) if named else 0):.0%}")
    print(f"  [2] churn median={_median(all_ch)} p90={_pct(all_ch,90)} max={max(all_ch) if all_ch else 0}")
    print(f"  [3] same-pass OOS cluster: median={_median(sizes)} "
          f"isolated={ (iso/len(sizes) if sizes else 0):.0%} "
          f"bulk(>={BULK_SIZE})={ (blk/len(sizes) if sizes else 0):.0%}")
    print()
    print("PROPOSED (non-binding) ship/hold — /lead-backend + /brand-manager decide:")
    for r in results:
        print(f"  {r['slug']:>16}: {r['verdict']}")
    print("\nHONEST LIMIT: these proxies cannot separate isolated-terminal SALE from")
    print("isolated-terminal PULL. A vendor that pulls unsold pieces fast (relists rare,")
    print("low churn, isolated) reads SHIP here but the 'didn't last' claim would be")
    print("wrong for it. The analysis bounds residual mis-signal risk; the discriminator")
    print("(sale vs pull) stays deferred. Numbers only — the call is editorial.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
