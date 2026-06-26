"""CTK-199 — fleet category coverage backfill, round 2 (live-pull recompute).

Direct successor to ctk194_category_coverage_backfill (which this clones). The
CTK-199 coverage ADD to normalize._CATEGORY_PATTERNS (round-2 genera +
common-names: lithophyllon/litho, hydnophora/hydno, indophyllia, astreopora,
anthelia, trumpet, stag/staghorn, bubble coral, daisy polyps, diaseris, pipe
organ/tubipora; psammocora widened to the psammacora spelling) corrects stored
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

Exit codes: 0 on success (dry run or apply), 1 on any vendor live-pull error
(loud; other vendors still process).
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter

from scrapers.common import db, parse_bigcommerce, parse_shopify
from scrapers.common.run import _load_yaml
from scrapers.vendors import tidal_gardens

# The round-2 anchors this backfill is responsible for, with their FINAL
# category (post majority-vote correction: hydnophora/hydno + astreopora -> lps,
# NOT the directive's sps). A change is "CTK-199-driven" only if the row's title
# carries one of these tokens AND it maps to the recomputed category. This scopes
# --apply to THIS round's corrections and excludes incidental vendor metadata
# drift the live re-pull also surfaces (e.g. a Turbinaria flipping lps->sps, a
# BattleCorals row losing its category) — those are not CTK-199's to write, and
# at least one (Turbinaria is LPS) would be wrong. Frozen here as the one-time
# provenance record of the round-2 token set; mirrors normalize._CATEGORY_PATTERNS.
_ROUND2_TOKENS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("sps",    re.compile(r"\bpsamm[oa]cora\b|\bstag(?:horn)?\b", re.I)),
    ("lps",    re.compile(r"\blithophyllon\b|\blitho\b|\bindophyllia\b|\btrumpet\b"
                          r"|\bbubble\s+coral\b|\bdiaseris\b|\bplate\s+coral\b"
                          r"|\bhydnophora\b|\bhydno\b|\bastreopora\b", re.I)),
    ("softie", re.compile(r"\banthelia\b|\bdaisy\s+polyps?\b|\bpipe\s+organ\b|\btubipora\b", re.I)),
)


def _round2_explains_flip(raw_title: str, new_cat: str | None) -> bool:
    """True iff a round-2 token in the title maps to the recomputed category.
    Gates the coral->coral CORRECTIONS only — so a re-tag CTK-199 is responsible
    for (psammacora lps->sps, pipe organ lps->softie) applies, while an
    incidental live-pull flip with no round-2 token (a Turbinaria mis-tagged
    lps->sps by vendor drift) does NOT."""
    if new_cat is None:
        return False
    title = raw_title or ""
    for cat, pat in _ROUND2_TOKENS:
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
    if _round2_explains_flip(raw_title, new_cat):
        return "corr"                     # round-2-driven correction
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


def main() -> int:
    ap = argparse.ArgumentParser(description="CTK-199 fleet category coverage backfill (dry run unless --apply)")
    ap.add_argument("--apply", action="store_true", help="perform the UPDATEs (default: dry run, no writes)")
    args = ap.parse_args()

    mode = "APPLY" if args.apply else "DRY RUN"
    print(f"=== CTK-199 category coverage backfill (round 2) — {mode} ===\n")

    total_changes = 0
    fills = 0            # NULL -> category (the intended fix)
    corrections = 0      # coral -> coral, CTK-199-driven (Option B: re-tag to correct/consistent)
    drift = 0            # change NOT explained by a round-2 token — excluded from --apply
    fill_by_cat: Counter = Counter()
    drift_rows: list[str] = []
    vendor_errors: list[str] = []

    # Vendor list — short connection, opened and closed immediately.
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            vendors = _vendor_slugs(cur)

    # Per vendor, the DB connection is held ONLY for the quick read + write, never
    # across the slow live HTTP pull. A single connection spanning all 12 pulls
    # sits idle for minutes and Neon drops it mid-run (the 2026-06-26 partial-apply
    # incident died on pacific_east's pull). Fresh short-lived connections per
    # vendor sidestep the idle-timeout entirely; with autocommit each vendor's
    # writes commit independently, and the tool is idempotent, so a mid-fleet
    # failure just re-runs to completion.
    for v in vendors:
        slug, platform = v["slug"], v["platform"]
        # 1. config + live pull — no DB connection open during the HTTP fetch.
        try:
            with db.get_conn() as conn:
                vendor_row = db.fetch_vendor(conn, slug)
            config = {**vendor_row, **_load_yaml(slug)}
            fresh = _live_categories(config, platform)
        except Exception as e:  # noqa: BLE001 — loud per-vendor, continue the fleet
            msg = f"{slug}: live-pull FAILED ({type(e).__name__}: {e})"
            print(f"  {msg}\n", flush=True)
            vendor_errors.append(msg)
            continue

        # 2. read stored + (optionally) write — fresh short-lived connection.
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

            if args.apply and applied:
                with conn.cursor() as cur:
                    cur.executemany(
                        "UPDATE vendor_listings SET category = %s WHERE id = %s",
                        [(new, vid) for vid, _t, _o, new, _d in applied],
                    )
        total_changes += len(changes)
        fills += v_fills
        corrections += v_corr
        drift += len(excluded)

    applied_total = fills + corrections
    print("=== summary ===")
    print(f"{mode}: CTK-199 {'applied' if args.apply else 'would apply'} {applied_total} row(s) "
          f"across {len(vendors) - len(vendor_errors)} vendor(s)")
    print(f"  fills (NULL -> category): {fills}   {dict(fill_by_cat)}")
    print(f"  corrections (coral -> coral, round-2 driven): {corrections}")
    print(f"  drift-EXCLUDED (not a round-2 token; left untouched): {drift}")
    for d in drift_rows:
        print(f"    - {d}")
    if vendor_errors:
        print(f"WARN: {len(vendor_errors)} vendor live-pull error(s):")
        for m in vendor_errors:
            print(f"  - {m}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
