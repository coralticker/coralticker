"""CTK-199/200 — fleet category coverage audit (live-pull recompute), rounds 2+3.

CTK-200 productizes this CTK-199 one-shot backfill into the engine behind a
scheduled weekly self-healing audit (`.github/workflows/category-coverage-audit.yml`).
The CTK-200 additions: a two-pass gated `--apply` (compute the COMPLETE fleet
change-set first, gate on a circuit-breaker, then write) and the `--max-changes`
/ `--max-change-pct` breaker that aborts the apply (exit 2, zero writes) when a
run would change more than expected — a large weekly drift is an anomaly signal
(parser regression / a committed pattern-widening propagating), not normal
rotation, so it surfaces for a human eyeball instead of writing unattended. The
engine keeps its `ctk199_` name (the workflow YAML references it; rename deferred).


Direct successor to ctk194_category_coverage_backfill (which this clones). The
CTK-199 coverage ADD to normalize._CATEGORY_PATTERNS — round 2 (lithophyllon/
litho, hydnophora/hydno, indophyllia, astreopora, anthelia, trumpet, stag/
staghorn, bubble coral, daisy polyps, diaseris, pipe organ/tubipora; psammocora
widened to psammacora) PLUS round 3 (lepto, echinata->lps, tenuis, mille,
galaxia, platygyra, heliofungia, sympodium->softie, scroll coral, turbinaria,
war coral, maze brain, and the loose-plate NULL floor) — corrects stored
`vendor_listings.category` going FORWARD only — rows already NULL keep NULL until
their next scrape touches them, and `decision == 'unchanged'` rows skip the
row-build entirely (feedback_capture_path_unchanged_blind_spot). This tool
reclassifies the standing fleet now.

Why a live re-pull and not a title-only UPDATE: infer_category reads
product_type + tags + title, and vendor_listings persists none of the first two.
So we re-pull each vendor's live catalog and recompute category through the SAME
production parse path the scraper uses (run.py platform dispatch +
fetch_and_parse, verbatim) — the backfill can never diverge from what the next
scrape would write. Identical shape to ctk186/ctk194.

Discipline (unchanged from CTK-194):
  - Fleet-wide per vendor; the _ctk*_test sentinels are skipped.
  - Only rows PRESENT in the live pull are touched. Delisted rows carry no
    recoverable PT/tags and are LEFT UNTOUCHED (off the in-stock feed anyway).
  - Idempotent: a second run finds nothing to change.
  - Run OUTSIDE a scrape window (live HTTP pull races the cron persist otherwise
    — feedback_yaml_state_cron_window_risk.md). The hourly fleet fires at
    :07/:11/:19/:29/:37/:41/:43/:47/:53/:57; the clean window is :12-:18.

Default run is a DRY RUN — prints the full reclassification diff (both
directions) for the pre-apply eyeball and writes nothing. The diff is the
CTK-199 HARD GATE: every change should be NULL -> <category>. Any
<coral-category> -> <other-category> flip is a collision to scrutinize before
--apply (a round-2 token re-tagging an already-categorized coral is exactly the
FP class the dry-run is here to catch — the 0/248 matched-coral pre-check covers
named corals; the collision count covers the rest of the fleet).

Run via:
  python -m scrapers.tools.ctk199_category_coverage_backfill          # dry run
  python -m scrapers.tools.ctk199_category_coverage_backfill --apply  # commit
  python -m scrapers.tools.ctk199_category_coverage_backfill --apply --max-changes 100 --max-change-pct 1.5

Exit codes (the workflow keys its Slack message off these):
  0 — clean (dry run, or apply within the breaker).
  1 — run failure: any vendor live-pull failed, so the fleet total is
      INCOMPLETE; the whole run aborts with ZERO writes and retries next week
      (an under-counted total could defeat the breaker — CTK-200 D3). This is a
      behavior change from the CTK-199 one-shot, which partial-applied survivors.
  2 — breaker tripped: the would-apply count exceeds --max-changes or
      --max-change-pct; the apply aborts with ZERO writes for a human eyeball.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter

from scrapers.common import db, parse_bigcommerce, parse_shopify
from scrapers.common.run import _load_yaml
from scrapers.vendors import tidal_gardens

# The CTK-199 anchors (round 2 + round 3) this backfill is responsible for, with
# their FINAL category (post majority-vote correction: hydnophora/hydno +
# astreopora -> lps, NOT the directive's sps; echinata -> lps NOT chalice;
# sympodium -> softie NOT the fleet's lps). A change is "CTK-199-driven" only if
# the row's title carries one of these tokens AND it maps to the recomputed
# category. This scopes --apply to THIS ticket's corrections and excludes
# incidental vendor metadata drift the live re-pull also surfaces (e.g. a
# BattleCorals row losing its category) — those are not CTK-199's to write.
# Frozen here as the one-time provenance record of the anchor set; mirrors
# normalize._CATEGORY_PATTERNS. NULL->category FILLS apply regardless of this set
# (always safe), so the round-3 NULL-only adds (lepto, galaxia, platygyra,
# heliofungia, war/scroll/maze, the loose-plate floor) need no entry here — they
# only ever fill; the tokens below are the ones that also drive coral->coral
# RE-TAGS (turbinaria fixing the round-2 lps->sps mis-flip; echinata sps->lps;
# sympodium lps->softie; tenuis/mille consistency).
_ANCHOR_TOKENS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("sps",    re.compile(r"\bpsamm[oa]cora\b|\bstag(?:horn)?\b|\btenuis\b|\bmille\b", re.I)),
    ("lps",    re.compile(r"\blithophyllon\b|\blitho\b|\bindophyllia\b|\btrumpet\b"
                          r"|\bbubble\s+coral\b|\bdiaseris\b|\bplate\s+coral\b"
                          r"|\bhydnophora\b|\bhydno\b|\bastreopora\b"
                          r"|\blepto\b|\bechinata\b|\bgalaxia\b|\bplatygyra\b"
                          r"|\bheliofungia\b|\bscroll\s+coral\b|\bturbinaria\b"
                          r"|\bwar\s+coral\b|\bmaze\s+brain\b", re.I)),
    ("softie", re.compile(r"\banthelia\b|\bdaisy\s+polyps?\b|\bpipe\s+organ\b|\btubipora\b|\bsympodium\b", re.I)),
)


def _anchor_explains_flip(raw_title: str, new_cat: str | None) -> bool:
    """True iff a CTK-199 anchor token in the title maps to the recomputed
    category. Gates the coral->coral CORRECTIONS only — so a re-tag CTK-199 is
    responsible for (psammacora lps->sps, pipe organ lps->softie, echinata
    sps->lps, sympodium lps->softie) applies, while an incidental live-pull flip
    with no anchor token (vendor drift) does NOT."""
    if new_cat is None:
        return False
    title = raw_title or ""
    for cat, pat in _ANCHOR_TOKENS:
        if cat == new_cat and pat.search(title):
            return True
    return False


def _decide(old_cat: str | None, new_cat: str | None, raw_title: str) -> str:
    """Per-change disposition for --apply scope:
      'fill'    — NULL -> category: always applied (a fill is always a safe
                  improvement, whatever token drove it — this is the legacy
                  unchanged-blind-spot NULL the backfill exists to clear).
      'corr'    — coral -> coral explained by a round-2 token: applied (Option B
                  re-tag to correct/consistent).
      'drift'   — everything else (category-LOSS, or a coral->coral flip no
                  round-2 token explains): EXCLUDED, left untouched.
    """
    if new_cat is None:
        return "drift"                    # category-loss: tokens only ADD, never remove
    if old_cat is None:
        return "fill"                     # NULL -> category: always safe
    if _anchor_explains_flip(raw_title, new_cat):
        return "corr"                     # CTK-199-anchor-driven correction
    return "drift"                        # unexplained coral->coral: vendor drift


def _live_categories(config: dict, platform: str) -> dict[str, str | None]:
    """Re-pull the vendor's live catalog through the production parser and return
    {product_url: recomputed_category}. Reuses run.py dispatch verbatim — the
    parser yields items whose 'category' is the post-CTK-199 infer_category
    result. Raises on block / schema-change / network error."""
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
    cur.execute("SELECT id, slug, platform FROM vendors WHERE slug NOT LIKE '\\_%' ORDER BY id")
    return cur.fetchall()


def _positive_int(value: str) -> int:
    """argparse type: an int strictly > 0 (CTK-190 positive-param precedent —
    load-bearing once the breaker runs unattended; a 0/negative ceiling would
    abort or never-abort silently)."""
    iv = int(value)
    if iv <= 0:
        raise argparse.ArgumentTypeError(f"must be an integer > 0, got {iv}")
    return iv


def _pct(value: str) -> float:
    """argparse type: a float in (0, 100]. Reject <= 0 (meaningless ceiling) and
    > 100 (a >100%-of-fleet threshold can never trip — a silent footgun)."""
    fv = float(value)
    if not (0 < fv <= 100):
        raise argparse.ArgumentTypeError(f"must be a float in (0, 100], got {fv}")
    return fv


def _breaker_tripped(applied_total: int, fleet_total: int, max_changes: int, max_pct: float) -> bool:
    """OR'd circuit-breaker: abort the apply if the would-write count exceeds the
    absolute ceiling OR the %-of-in-stock-fleet ceiling. A large weekly drift is
    an anomaly signal (parser regression / a committed pattern-widening
    propagating), not normal rotation — surface it for a human eyeball instead of
    writing unattended. Pure (no I/O) so it unit-tests without a live pull."""
    if applied_total <= 0:
        return False                       # nothing to write — never an anomaly
    if applied_total > max_changes:
        return True
    if fleet_total <= 0:
        return True                        # can't compute a ratio — fail safe (abort)
    return (applied_total / fleet_total * 100.0) > max_pct


def main() -> int:
    ap = argparse.ArgumentParser(description="CTK-199/200 fleet category coverage audit (dry run unless --apply)")
    ap.add_argument("--apply", action="store_true", help="perform the UPDATEs (default: dry run, no writes)")
    ap.add_argument("--max-changes", type=_positive_int, default=100,
                    help="circuit-breaker: abort --apply (exit 2, zero writes) if the fleet-wide "
                         "would-apply count exceeds this absolute ceiling (default 100)")
    ap.add_argument("--max-change-pct", type=_pct, default=1.5,
                    help="circuit-breaker: abort --apply (exit 2, zero writes) if would-apply exceeds "
                         "this percent of the in-stock fleet (default 1.5)")
    args = ap.parse_args()

    mode = "APPLY" if args.apply else "DRY RUN"
    print(f"=== CTK-199/200 category coverage audit — {mode} ===\n")

    fills = 0            # NULL -> category (the intended fix)
    corrections = 0      # coral -> coral, CTK-199-anchor-driven (re-tag to correct/consistent)
    drift = 0            # change NOT explained by a CTK-199 token — excluded
    fill_by_cat: Counter = Counter()
    drift_rows: list[str] = []
    vendor_errors: list[str] = []
    pending: list[tuple[str, list]] = []   # [(slug, applied-rows)] — held for pass 2

    # Vendor list — short connection, opened and closed immediately.
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            vendors = _vendor_slugs(cur)

    # ── PASS 1: pull every vendor live + compute the change-set. NO writes. ──────
    # Holding the applied-rows in memory (tens-to-low-hundreds of rows) lets the
    # circuit-breaker gate on the COMPLETE fleet-wide total before any write — the
    # CTK-200 "abort instead of writing" contract; the CTK-199 inline per-vendor
    # write couldn't, since the total wasn't known until vendors were already
    # written. The DB connection is never held across the slow live HTTP pull (the
    # CTK-199 round-2 idle-timeout fix: a single long-held connection sat idle for
    # minutes and Neon dropped it mid-run). Fresh short-lived connections per step.
    for v in vendors:
        slug, platform = v["slug"], v["platform"]
        # 1. config + live pull — no DB connection open during the HTTP fetch.
        try:
            with db.get_conn() as conn:
                vendor_row = db.fetch_vendor(conn, slug)
            config = {**vendor_row, **_load_yaml(slug)}
            fresh = _live_categories(config, platform)
        except Exception as e:  # noqa: BLE001 — loud per-vendor; aborts the run below
            msg = f"{slug}: live-pull FAILED ({type(e).__name__}: {e})"
            print(f"  {msg}\n", flush=True)
            vendor_errors.append(msg)
            continue

        # 2. read stored — fresh short-lived connection, no write here (pass 2).
        with db.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, product_url, raw_title, category FROM vendor_listings "
                    "WHERE vendor_id = %s ORDER BY id",
                    (vendor_row["id"],),
                )
                stored = cur.fetchall()

        changes = []  # (id, raw_title, old, new, disposition)
        for r in stored:
            url = r["product_url"]
            if url not in fresh:
                continue  # delisted / filtered-out — left untouched
            new_cat = fresh[url]
            if new_cat != r["category"]:
                disp = _decide(r["category"], new_cat, r["raw_title"])
                changes.append((r["id"], r["raw_title"], r["category"], new_cat, disp))

        applied = [c for c in changes if c[4] in ("fill", "corr")]
        excluded = [c for c in changes if c[4] == "drift"]
        v_fills = sum(1 for c in changes if c[4] == "fill")
        v_corr = sum(1 for c in changes if c[4] == "corr")
        print(f"--- {slug} ({platform}): {len(stored)} stored, {len(fresh)} live, "
              f"{len(changes)} change ({v_fills} fill, {v_corr} correction, {len(excluded)} drift-excluded) ---",
              flush=True)
        for vid, title, old, new, disp in applied:
            kind = "FILL " if disp == "fill" else "CORR "
            print(f"  {kind} id={vid:>7}  {str(old):<10} -> {str(new):<10}  {title[:56]!r}")
            if disp == "fill":
                fill_by_cat[new] += 1
        for vid, title, old, new, disp in excluded:
            print(f"  DRIFT id={vid:>7}  {str(old):<10} -> {str(new):<10}  {title[:56]!r}  <-- excluded (vendor drift)")
            drift_rows.append(f"{slug} id={vid} {str(old)}->{str(new)} {title[:50]!r}")
        print(flush=True)

        if applied:
            pending.append((slug, applied))
        fills += v_fills
        corrections += v_corr
        drift += len(excluded)

    applied_total = fills + corrections

    # ── Pass-1 partial failure = whole-run abort (CTK-200 D3). ──────────────────
    # An incomplete pull under-counts the fleet total, which could let a real
    # anomaly slip under the breaker — so a single vendor failure aborts the whole
    # run with ZERO writes (pass 2 never runs) and retries next week.
    if vendor_errors:
        print("=== ABORT: incomplete fleet pull — zero writes ===")
        print(f"{len(vendor_errors)} vendor live-pull error(s); not writing a partial-fleet total:")
        for m in vendor_errors:
            print(f"  - {m}")
        return 1

    # ── Breaker %-ceiling denominator: in-stock fleet, test sentinels excluded ──
    # (matches category_coverage_drift.py + _vendor_slugs scope, so the % is over
    # the same population the audit touches).
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS n FROM vendor_listings vl JOIN vendors v ON v.id = vl.vendor_id "
                "WHERE vl.in_stock AND v.slug NOT LIKE '\\_%'"
            )
            fleet_total = cur.fetchone()["n"]

    pct = (applied_total / fleet_total * 100.0) if fleet_total else 0.0
    tripped = _breaker_tripped(applied_total, fleet_total, args.max_changes, args.max_change_pct)

    print("=== summary ===")
    print(f"{mode}: CTK-199/200 — {applied_total} row(s) to apply across {len(vendors)} vendor(s) "
          f"({pct:.2f}% of {fleet_total} in-stock)")
    print(f"  fills (NULL -> category): {fills}   {dict(fill_by_cat)}")
    print(f"  corrections (coral -> coral, anchor-driven): {corrections}")
    print(f"  drift-EXCLUDED (not a CTK-199 token; left untouched): {drift}")
    for d in drift_rows:
        print(f"    - {d}")

    # ── Circuit-breaker gate. The "would-apply <N>" token is the stable line the
    # workflow greps for the Slack BREAKER-TRIPPED count — keep the wording. ─────
    breaker_line = (f"would-apply {applied_total} vs max-changes {args.max_changes}; "
                    f"{pct:.2f}% vs max-change-pct {args.max_change_pct}%")
    if tripped:
        if args.apply:
            print(f"=== BREAKER TRIPPED — ABORT, zero writes ({breaker_line}) ===")
            print("  a large weekly drift is an anomaly signal, not normal rotation — review the diff "
                  "above and land manually (dispatch with a raised --max-changes) if intended.")
            return 2
        print(f"=== BREAKER would-trip (dry run, no writes) — {breaker_line} ===")
    else:
        print(f"=== breaker OK — {breaker_line} ===")

    # ── PASS 2: write. Only reached when the gate passes; dry run skips it. ──────
    # Fresh short-lived connection per vendor (idle-fix preserved). Idempotent — a
    # mid-pass-2 failure re-runs clean next week. TOCTOU pass1->pass2 is benign:
    # id-scoped UPDATE; a row deleted between passes -> 0-row UPDATE; a concurrent
    # scrape that re-touched category used the same patterns, so the value converges.
    if args.apply:
        written = 0
        for slug, applied in pending:
            with db.get_conn() as conn:
                with conn.cursor() as cur:
                    cur.executemany(
                        "UPDATE vendor_listings SET category = %s WHERE id = %s",
                        [(new, vid) for vid, _t, _o, new, _d in applied],
                    )
            written += len(applied)
        print(f"=== wrote {written} row(s) across {len(pending)} vendor(s) ===")

    return 0


if __name__ == "__main__":
    sys.exit(main())
