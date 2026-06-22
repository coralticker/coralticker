"""CTK-181 Half 2 — one-time id-scoped DELETE of the 5 stranded matched TSA
intake-junk rows: the live Template leak + 4 stale matched -twcheap test rows.

Why these 5 are stranded (not self-healing): once Half 1's forward gates
(tsa.yaml title_denylist_prefix 'template ' + sku_denylist_suffix '-twcheap')
ship, parse_shopify rejects these rows at intake and adds their URLs to
ParseResult.filtered_urls — and diff.classify EXCLUDES filtered_urls from the
cohort absent-set (CTK-094 fold #4), so the go-forward delisting cycle never
OOS-flips them. 129920 in particular stays in_stock=true @ $99.99 + matched to
named coral 14 forever unless explicitly remediated. This is that remediation.

Mechanism: DELETE (Q-1, ratified /lead-backend 2026-06-21). These are vendor
template/test placeholders — no legitimate listing or price history worth
preserving. DELETE clears every surface in one id-scoped statement (chart per-
listing track, /new, /vendor/tsa, envelope, by-vendor). FK CASCADE handles both
dependents: price_history(listing_id) + ig_spotlight_picks(listing_id), both
ON DELETE CASCADE (0001_init.sql / 0045).

Q-1 FOLD: the pre-flight enumerates BOTH cascade dependents' row-counts per id
(not just price_history) so the full cascade is visible before --apply and a
future re-run can't silently delete an active IG pick. ABORT if any target is
referenced by ig_spotlight_picks (an active IG pick on a delete-target is a
re-audit signal, not a delete-anyway).

Frozen PK rail (CTK-155 shape): the 5 EXPECTED_IDS are fixed DB PKs from the
2026-06-21 audit. The script resolves them, sanity-checks the row shape (TSA
vendor, the Template in_stock + matched, the 4 matched -twcheap), and ABORTS on
any divergence rather than deleting a reused/changed id. No live feed re-pull
needed — a frozen PK set is found DB-only (the FP audit + the twcheap purge-set
freeze are the separate live-re-pull steps).

Run via:
  python -m scrapers.tools.ctk181_template_match_backfill            # DRY-RUN (default)
  python -m scrapers.tools.ctk181_template_match_backfill --apply    # writes

Run --apply AFTER the Half-1 forward-gate push (denylist-first strands 129920 in
filtered intake so it can't restock-flap; backfill-first would flap on the next
fire). Exit 0 on success, 1 on a sanity/abort/post-verify gap. Reads
NEON_DATABASE_URL from .env.
"""

from __future__ import annotations

import argparse
import sys

from scrapers.common import db

TSA_VENDOR_ID = 3

# Frozen DB PKs (2026-06-21 audit). 129920 = the live Template leak (in_stock @
# $99.99, matched coral 14); the other 4 = stale matched -twcheap test rows
# (OOS, last seen ~2026-06-07/08). coral 14 = tsa-garf-bonsai-acropora.
EXPECTED_IDS = [129920, 131712, 131951, 132317, 132475]

# Sanity rail: 129920 must still be the in_stock matched Template. The 4 must be
# matched (named_coral_id NOT NULL). Divergence => ABORT, re-audit.
TEMPLATE_ID = 129920
EXPECTED_TEMPLATE_TITLE_PREFIX = "Template "


def _fetch_targets(cur) -> list[dict]:
    cur.execute(
        "SELECT id, raw_title, in_stock, current_price, named_coral_id "
        "FROM vendor_listings WHERE vendor_id = %s AND id = ANY(%s) ORDER BY id",
        (TSA_VENDOR_ID, EXPECTED_IDS),
    )
    return cur.fetchall()


def _dependent_counts(cur, ids: list[int]) -> dict[int, dict]:
    """Per-id row counts for BOTH cascade dependents (Q-1 fold)."""
    counts = {i: {"price_history": 0, "ig_spotlight_picks": 0} for i in ids}
    cur.execute(
        "SELECT listing_id, COUNT(*) AS c FROM price_history "
        "WHERE listing_id = ANY(%s) GROUP BY listing_id",
        (ids,),
    )
    for r in cur.fetchall():
        counts[r["listing_id"]]["price_history"] = r["c"]
    cur.execute(
        "SELECT listing_id, COUNT(*) AS c FROM ig_spotlight_picks "
        "WHERE listing_id = ANY(%s) GROUP BY listing_id",
        (ids,),
    )
    for r in cur.fetchall():
        counts[r["listing_id"]]["ig_spotlight_picks"] = r["c"]
    return counts


def run(apply: bool) -> int:
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            rows = _fetch_targets(cur)
            print(f"resolved {len(rows)}/{len(EXPECTED_IDS)} EXPECTED_IDS "
                  f"(TSA vendor_id={TSA_VENDOR_ID}):")
            for r in rows:
                print(f"  id={r['id']:8d}  in_stock={str(r['in_stock']):5}  "
                      f"price={r['current_price']}  coral={r['named_coral_id']}  "
                      f"{r['raw_title']!r}")

            # --- Sanity rail: ABORT on any divergence from the audited shape ---
            found_ids = {r["id"] for r in rows}
            missing = set(EXPECTED_IDS) - found_ids
            if missing:
                print(f"ABORT: {len(missing)} EXPECTED_IDS missing from "
                      f"vendor_listings: {sorted(missing)}. Re-audit before delete.",
                      file=sys.stderr)
                return 1
            by_id = {r["id"]: r for r in rows}
            tmpl = by_id[TEMPLATE_ID]
            if not (tmpl["raw_title"] or "").startswith(EXPECTED_TEMPLATE_TITLE_PREFIX):
                print(f"ABORT: id={TEMPLATE_ID} title {tmpl['raw_title']!r} no longer "
                      f"starts {EXPECTED_TEMPLATE_TITLE_PREFIX!r} — id reused/changed. Re-audit.",
                      file=sys.stderr)
                return 1
            unmatched = [r["id"] for r in rows if r["named_coral_id"] is None]
            if unmatched:
                # All 5 were matched at audit (that's WHY they leak onto coral
                # surfaces). An unmatched target = shape drift, not a delete-anyway.
                print(f"ABORT: targets unexpectedly unmatched (named_coral_id NULL): "
                      f"{unmatched}. Re-audit before delete.", file=sys.stderr)
                return 1

            # --- Dual-dependent pre-flight (Q-1 fold) ---
            counts = _dependent_counts(cur, EXPECTED_IDS)
            print("\ncascade pre-flight (both ON DELETE CASCADE dependents):")
            ig_hits = []
            for i in EXPECTED_IDS:
                c = counts[i]
                print(f"  id={i:8d}  price_history={c['price_history']:4d}  "
                      f"ig_spotlight_picks={c['ig_spotlight_picks']}")
                if c["ig_spotlight_picks"]:
                    ig_hits.append(i)
            if ig_hits:
                print(f"\nABORT: {len(ig_hits)} target(s) referenced by "
                      f"ig_spotlight_picks: {ig_hits}. An active IG pick on a "
                      f"delete-target is a re-audit signal, not a delete-anyway "
                      f"(Q-1 fold). Resolve the pick first.", file=sys.stderr)
                return 1

            if not apply:
                print(f"\n[DRY-RUN] would DELETE {len(EXPECTED_IDS)} vendor_listings "
                      f"rows (price_history + ig_spotlight_picks FK CASCADE follow). "
                      f"Re-run with --apply to write.")
                return 0

            cur.execute("DELETE FROM vendor_listings WHERE id = ANY(%s)", (EXPECTED_IDS,))
            print(f"\nDELETE affected: {cur.rowcount} vendor_listings rows "
                  f"(FK CASCADE cleaned dependents).")

            # NOTE (autocommit): db.get_conn() is autocommit=True (db.py:154) — the
            # DELETE above is ALREADY durable here, not pending a block-exit commit.
            # The safety is the PRE-write ABORT rails (sanity + dual-dependent
            # IG-pick check); this post-verify is a confirmation, not a rollback
            # gate (a residual>0 return-1 cannot un-delete). Matches the autocommit
            # convention of the ctk041/ctk155/ctk160 remediation tools.
            # Post-verify.
            cur.execute(
                "SELECT COUNT(*) AS c FROM vendor_listings WHERE id = ANY(%s)",
                (EXPECTED_IDS,),
            )
            residual = cur.fetchone()["c"]
            if residual:
                print(f"WARN: {residual} EXPECTED_IDS still present post-DELETE",
                      file=sys.stderr)
                return 1
            print("post-DELETE verify: 0 EXPECTED_IDS remain in vendor_listings")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true",
                        help="Write the DELETE (default: dry-run, read-only).")
    args = parser.parse_args()
    try:
        return run(args.apply)
    except Exception as e:  # noqa: BLE001 — surface loudly, exit 1
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
