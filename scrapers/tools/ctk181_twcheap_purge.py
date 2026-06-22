"""CTK-181 Half 3 — one-time purge of the TSA -twcheap test-data cohort.

The cohort: ~202 vendor_listings rows whose variant SKU ends '-twcheap' (cross-
vendor test data — REAL/famous coral titles at $1–$15, so product_type/tag/title
axes are all blind; the SKU suffix is the only discriminator). Half 1 builds the
sku_denylist_suffix forward gate so no NEW -twcheap row ingests; this script
clears the already-persisted backlog the forward gate can't retroactively reach.

Selector: vendor_listings.vendor_sku LIKE '%-twcheap' (TSA only). Case-sensitive
LIKE mirrors the case-sensitive endswith in the parse_shopify axis — same match
semantics on both sides. The id-set is FROZEN at run-time from the live DB (re-
pull the feed for the FP audit + the in_stock count separately; this script
reports both at execution).

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
  python -m scrapers.tools.ctk181_twcheap_purge            # DRY-RUN (default)
  python -m scrapers.tools.ctk181_twcheap_purge --apply    # writes

Run --apply AFTER the Half-1 forward-gate push + AFTER the backfill. Idempotent:
re-running finds 0 rows once clean. Exit 0 on success, 1 on an abort / post-verify
gap. Reads NEON_DATABASE_URL from .env.
"""

from __future__ import annotations

import argparse
import sys

from scrapers.common import db

TSA_VENDOR_ID = 3
# Case-sensitive LIKE — mirrors the case-sensitive endswith in
# parse_shopify._should_keep's sku_denylist_suffix axis. '%-twcheap' = SKU
# ending in the literal suffix (the '-' anchors it to a real suffix, not a
# mid-string coincidence).
SKU_LIKE = "%-twcheap"


def _fetch_cohort(cur) -> list[dict]:
    cur.execute(
        "SELECT id, raw_title, vendor_sku, in_stock, current_price, named_coral_id "
        "FROM vendor_listings "
        "WHERE vendor_id = %s AND vendor_sku LIKE %s "
        "ORDER BY in_stock DESC, id",
        (TSA_VENDOR_ID, SKU_LIKE),
    )
    return cur.fetchall()


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


def run(apply: bool) -> int:
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cohort = _fetch_cohort(cur)
            ids = [r["id"] for r in cohort]
            in_stock_rows = [r for r in cohort if r["in_stock"]]
            matched_rows = [r for r in cohort if r["named_coral_id"] is not None]
            print(f"twcheap cohort (TSA vendor_id={TSA_VENDOR_ID}, "
                  f"vendor_sku LIKE {SKU_LIKE!r}): {len(cohort)} rows")
            print(f"  in_stock: {len(in_stock_rows)}   matched: {len(matched_rows)}")
            for r in in_stock_rows:
                print(f"  [IN_STOCK] id={r['id']:8d}  price={r['current_price']}  "
                      f"sku={r['vendor_sku']!r}  coral={r['named_coral_id']}  "
                      f"{r['raw_title']!r}")
            for r in matched_rows:
                print(f"  [MATCHED]  id={r['id']:8d}  coral={r['named_coral_id']}  "
                      f"sku={r['vendor_sku']!r}  {r['raw_title']!r}")

            if not cohort:
                print("no -twcheap rows remain — nothing to purge. Exiting clean.")
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

            residual = _fetch_cohort(cur)
            if residual:
                print(f"WARN: {len(residual)} -twcheap rows still present post-DELETE",
                      file=sys.stderr)
                return 1
            print("post-DELETE verify: 0 -twcheap rows remain for TSA")
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
