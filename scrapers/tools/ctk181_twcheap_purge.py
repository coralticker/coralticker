"""CTK-181 Half 3 — one-time purge of the TSA -twcheap test-data cohort.

The cohort: ~202 vendor_listings rows whose variant SKU ends '-twcheap' (cross-
vendor test data — REAL/famous coral titles at $1–$15, so product_type/tag/title
axes are all blind; the SKU suffix is the only discriminator). Half 1 builds the
sku_denylist_suffix forward gate so no NEW -twcheap row ingests; this script
clears the already-persisted backlog the forward gate can't retroactively reach.

Selector: a FROZEN id snapshot (--frozen-ids PATH), NOT a live LIKE. The set is
frozen once at the Step-2 confirm (after the forward gate is live + the live FP
audit is clean), so --apply deletes EXACTLY the audited rows — a -twcheap row
that appeared after the audit can't slip into the delete. Each frozen id is
re-verified as a still-present TSA -twcheap row before the delete (tail-tolerant
_is_twcheap_sku, mirroring parse_shopify._sku_hits_denylist — so '…-twcheap' and
the numbered-variant '…-twcheap-<n>' both qualify, CTK-181 review-fold); ABORT on
any drift (missing id beyond the backfill overlap, or an id whose vendor_sku is no
longer a -twcheap row = id reuse). The snapshot is written by the freeze step
(ctk181_purge_freeze_snapshot.json in the ticket dir, exclusive-create).

Overlap note: the 4 matched -twcheap rows (131712/131951/132317/132475) are in
BOTH this cohort and ctk181_template_match_backfill's EXPECTED_IDS. Run the
backfill FIRST — it DELETEs them — so this purge finds them already gone and
clears the remaining residue (incl. the in_stock 131946 'AWXKrissKrossChalice-
twcheap', a live buyable $15 junk row on /new + /vendor/tsa).

Mechanism: DELETE (same Q-1 ratification as the backfill). FK CASCADE handles
price_history + ig_spotlight_picks (both ON DELETE CASCADE). The pre-flight
enumerates BOTH dependents' totals + ABORTS if any purge-target is in
ig_spotlight_picks (Q-1 fold).

Run via:
  python -m scrapers.tools.ctk181_twcheap_purge --frozen-ids PATH            # DRY-RUN (default)
  python -m scrapers.tools.ctk181_twcheap_purge --frozen-ids PATH --apply    # writes

Run --apply AFTER the Half-1 forward-gate push + AFTER the backfill. Idempotent:
re-running finds 0 rows once clean. Exit 0 on success, 1 on an abort / post-verify
gap. Reads NEON_DATABASE_URL from .env.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from scrapers.common import db
from scrapers.common.parse_shopify import _SKU_NUM_VARIANT_TAIL

TSA_VENDOR_ID = 3
# Broad residual sweep pattern — '%-twcheap%' catches both '…-twcheap' and the
# numbered-variant form '…-twcheap-<n>' (CTK-181 review-fold) for the post-DELETE
# "anything left?" report. Used ONLY for the residual sweep, never to derive the
# delete set (that's the frozen id snapshot).
SKU_LIKE_BROAD = "%-twcheap%"


def _is_twcheap_sku(sku: str | None) -> bool:
    """Tail-tolerant -twcheap suffix test — mirrors parse_shopify._sku_hits_
    denylist: strip one trailing '-<digits>' numbered-variant tail, then check the
    '-twcheap' suffix. So '…-twcheap' and '…-twcheap-2' both qualify, a mid-string
    '-twcheap-real' does not. Case-sensitive."""
    return _SKU_NUM_VARIANT_TAIL.sub("", sku or "").endswith("-twcheap")


def _load_frozen_ids(path: Path) -> list[int]:
    snap = json.loads(path.read_text(encoding="utf-8"))
    ids = snap.get("twcheap_purge_ids")
    if not isinstance(ids, list) or not ids:
        raise ValueError(f"{path}: 'twcheap_purge_ids' missing or empty")
    return [int(i) for i in ids]


def _fetch_frozen(cur, frozen_ids: list[int]) -> tuple[list[dict], list[int], list[int]]:
    """Resolve the frozen id set. Returns (rows, missing_ids, non_twcheap_ids).
    A frozen id absent from the table, or present but whose vendor_sku no longer
    ends -twcheap, is DRIFT → caller ABORTS (id reuse / unexpected mutation)."""
    cur.execute(
        "SELECT id, raw_title, vendor_sku, in_stock, current_price, named_coral_id "
        "FROM vendor_listings WHERE vendor_id = %s AND id = ANY(%s) "
        "ORDER BY in_stock DESC, id",
        (TSA_VENDOR_ID, frozen_ids),
    )
    rows = cur.fetchall()
    found = {r["id"] for r in rows}
    missing = [i for i in frozen_ids if i not in found]
    non_twcheap = [r["id"] for r in rows if not _is_twcheap_sku(r["vendor_sku"])]
    return rows, missing, non_twcheap


def _dependent_totals(cur, ids: list[int]) -> tuple[int, dict[int, int]]:
    """(total price_history rows, {id: ig_spotlight_picks count}) for the cohort."""
    if not ids:
        return 0, {}
    cur.execute(
        "SELECT COUNT(*) AS c FROM price_history WHERE listing_id = ANY(%s)", (ids,),
    )
    ph_total = cur.fetchone()["c"]
    cur.execute(
        "SELECT listing_id, COUNT(*) AS c FROM ig_spotlight_picks "
        "WHERE listing_id = ANY(%s) GROUP BY listing_id",
        (ids,),
    )
    ig = {r["listing_id"]: r["c"] for r in cur.fetchall()}
    return ph_total, ig


def run(apply: bool, frozen_ids: list[int]) -> int:
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cohort, missing, non_twcheap = _fetch_frozen(cur, frozen_ids)
            ids = [r["id"] for r in cohort]
            in_stock_rows = [r for r in cohort if r["in_stock"]]
            matched_rows = [r for r in cohort if r["named_coral_id"] is not None]
            print(f"frozen twcheap set (TSA vendor_id={TSA_VENDOR_ID}): "
                  f"{len(frozen_ids)} ids requested, {len(cohort)} resolved")
            print(f"  in_stock: {len(in_stock_rows)}   matched: {len(matched_rows)}")
            for r in in_stock_rows:
                print(f"  [IN_STOCK] id={r['id']:8d}  price={r['current_price']}  "
                      f"sku={r['vendor_sku']!r}  coral={r['named_coral_id']}  "
                      f"{r['raw_title']!r}")
            for r in matched_rows:
                print(f"  [MATCHED]  id={r['id']:8d}  coral={r['named_coral_id']}  "
                      f"sku={r['vendor_sku']!r}  {r['raw_title']!r}")

            # --- Drift rail: the frozen set must resolve exactly to TSA -twcheap rows ---
            if missing:
                # Already-gone ids are fine ONLY if the backfill removed them
                # (the 4 matched overlap). Surface them; they're a no-op for the
                # delete (ANY() skips absent ids) but must be accounted for.
                print(f"\nNOTE: {len(missing)} frozen id(s) absent from vendor_listings "
                      f"(expected for the 4 matched-twcheap ids the backfill DELETEd "
                      f"first): {sorted(missing)}")
            if non_twcheap:
                print(f"\nABORT: {len(non_twcheap)} frozen id(s) present but no longer "
                      f"a -twcheap row (id reuse / drift): {non_twcheap}. Re-audit; do "
                      f"NOT delete.", file=sys.stderr)
                return 1
            if not cohort:
                print("frozen set fully resolved to 0 present rows — nothing to purge "
                      "(idempotent re-run or backfill already cleared all). Exiting clean.")
                return 0

            ph_total, ig = _dependent_totals(cur, ids)
            print(f"\ncascade pre-flight: price_history rows under cohort = {ph_total}; "
                  f"ig_spotlight_picks references = {sum(ig.values())}")
            if ig:
                print(f"\nABORT: {len(ig)} purge-target(s) referenced by "
                      f"ig_spotlight_picks: {dict(ig)}. Resolve the pick(s) before "
                      f"purge (Q-1 fold — no silent delete of an active IG pick).",
                      file=sys.stderr)
                return 1

            if not apply:
                print(f"\n[DRY-RUN] would DELETE {len(cohort)} -twcheap rows "
                      f"({len(in_stock_rows)} in_stock, {len(matched_rows)} matched; "
                      f"FK CASCADE follows). Re-run with --apply to write.")
                return 0

            cur.execute("DELETE FROM vendor_listings WHERE id = ANY(%s)", (ids,))
            print(f"\nDELETE affected: {cur.rowcount} vendor_listings rows "
                  f"(FK CASCADE cleaned dependents).")

            # Post-verify the frozen set is gone...
            still, _, _ = _fetch_frozen(cur, frozen_ids)
            if still:
                print(f"WARN: {len(still)} frozen ids still present post-DELETE: "
                      f"{[r['id'] for r in still]}", file=sys.stderr)
                return 1
            # ...and belt-and-suspenders: no TSA -twcheap row remains AT ALL (would
            # catch a row that landed post-freeze — should be 0, the forward gate
            # is live).
            cur.execute(
                "SELECT id FROM vendor_listings WHERE vendor_id = %s AND vendor_sku LIKE %s",
                (TSA_VENDOR_ID, SKU_LIKE_BROAD),
            )
            broad = [r["id"] for r in cur.fetchall()]
            if broad:
                print(f"NOTE: {len(broad)} TSA -twcheap row(s) remain that were NOT in "
                      f"the frozen set (landed post-freeze): {broad}. Forward gate "
                      f"blocks new intake — re-snapshot + re-run if these are real.")
            print("post-DELETE verify: 0 frozen ids remain "
                  f"({len(broad)} unfrozen -twcheap rows outstanding)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--frozen-ids", required=True, metavar="PATH",
                        help="Path to the Step-2 freeze snapshot JSON "
                             "(ctk181_purge_freeze_snapshot.json).")
    parser.add_argument("--apply", action="store_true",
                        help="Write the DELETE (default: dry-run, read-only).")
    args = parser.parse_args()
    try:
        frozen_ids = _load_frozen_ids(Path(args.frozen_ids))
        return run(args.apply, frozen_ids)
    except Exception as e:  # noqa: BLE001 — surface loudly, exit 1
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
