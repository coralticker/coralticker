"""CTK-107 D-2 — surgical UPDATE on the 130-row PARTITION-B IN-list.

Flips `vendor_listings.in_stock = false` for BC + UC stale rows that the
production parser actively rejects via `_should_keep` (parser-filtered-stuck
class per CTK-094 fold #4 — cohort-OOS absent-pass excludes these URLs, so
no mechanism in CTK-105's opt-in path ever flips them). Audit-trail rows
land in `price_history` per the CTK-104 6-fish bridge precedent
(`scrapers/common/diff.py:431` shape: `(listing_id, price, in_stock,
scraper_run_id)`, last-known `current_price` preserved).

Re-derives the IN-list deterministically each run via the D-1 partition
mechanism (imports `_should_keep` + reuses `_fetch_stale_rows` /
`_fetch_products_json` from ctk107_d1_partition). Re-run-safe: a second
invocation sees a 0-row stale rowset (post-UPDATE all 130 are
in_stock=false) and short-circuits to 0 UPDATEs + 0 INSERTs.

Audit anchors (per-vendor most-recent status='success' scraper_runs id;
verified at script start):
  BC (vendor_id=5) -> run_id 764
  UC (vendor_id=6) -> run_id 781

Two modes:
  --dry-run   : enumerate IN-list + audit anchors + print intent; no writes
  --execute   : single transaction wrapping UPDATE + price_history INSERTs

Post-execute, the same connection re-runs the stale-rowset predicate per
vendor and prints the post-update count (expect 0 for full clean — C2-style
verify-pass per `feedback_verify_pass_c2_over_c1.md`).
"""

from __future__ import annotations

import argparse
import sys

from scripts.ctk107_d1_partition import (
    _fetch_products_json,
    _fetch_stale_rows,
    _load_yaml,
)
from scrapers.common.db import get_conn
from scrapers.common.parse_shopify import _should_keep

# (vendor_id, slug, audit_anchor_run_id) — audit anchors are per-vendor
# most-recent status='success' scraper_runs row, picked at session-open.
# Per-vendor anchors keep the price_history audit semantically correct (a
# UC row's history entry FKs to a UC scraper_run, not BC's). Anchors:
#   BC = 764 (finished 2026-06-01 13:48 UTC)
#   UC = 781 (finished 2026-06-01 16:59 UTC)
#   PE = 782 (finished 2026-06-01 17:04 UTC; D-2-bis addition 2026-06-01)
#   JF = 784 (finished 2026-06-01 19:49 UTC; D-2-bis addition 2026-06-01)
# BC + UC stay in the list — script is idempotent (post-Session-2 stale
# rowsets are 0; PARTITION-B re-derive returns [] for both, no UPDATE
# fires). PE + JF added per /lead-backend Q-NEW-A disposition (a) at
# Session 2 wrap: roll 19 PE + 1 JF PARTITION-B residuals into expanded
# CTK-107 D-2-bis UPDATE scope.
VENDORS_TO_FIX = [
    (5, "battlecorals", 764),
    (6, "unique_corals", 781),
    (1, "pacific_east", 782),
    (4, "jf", 784),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Run the UPDATE + INSERT in a single transaction. Without this flag, dry-run only.",
    )
    args = parser.parse_args()

    mode_label = "EXECUTE" if args.execute else "DRY-RUN"
    print("=" * 78)
    print(f"CTK-107 D-2 — surgical UPDATE (mode: {mode_label})")
    print("=" * 78)

    with get_conn() as conn:
        # Phase 1 — reads under autocommit=True (default).
        pending: list[tuple[int, str, int, list[dict]]] = []  # (vendor_id, slug, anchor_run_id, partition_b_rows)
        for vendor_id, slug, anchor_run_id in VENDORS_TO_FIX:
            print()
            print(f"--- {slug} (vendor_id={vendor_id}, anchor_run_id={anchor_run_id}) ---")
            _verify_audit_anchor(conn, anchor_run_id, vendor_id)
            partition_b_rows, stale_n = _derive_partition_b(conn, vendor_id, slug)
            print(f"  stale rowset: {stale_n} rows")
            print(f"  PARTITION-B (UPDATE scope): {len(partition_b_rows)} rows")
            if partition_b_rows:
                _print_sample(partition_b_rows, k=5)
            pending.append((vendor_id, slug, anchor_run_id, partition_b_rows))

        total_b = sum(len(rows) for _, _, _, rows in pending)
        print()
        print(f"=== IN-list summary: {total_b} rows across {len(pending)} vendor(s) ===")
        for _, slug, anchor, rows in pending:
            print(f"  {slug}: {len(rows)} rows -> scraper_run_id={anchor}")

        if total_b == 0:
            print()
            print("PARTITION-B is empty fleet-wide. No UPDATE needed; exiting clean.")
            return 0

        if not args.execute:
            print()
            print("DRY-RUN complete. Re-run with --execute to fire the UPDATE.")
            return 0

        # Phase 2 — write under explicit transaction (autocommit=False).
        print()
        print("=" * 78)
        print("Firing UPDATE + price_history INSERTs in single transaction")
        print("=" * 78)
        conn.autocommit = False
        try:
            with conn.transaction():
                total_updated = 0
                total_history = 0
                for vendor_id, slug, anchor_run_id, rows in pending:
                    if not rows:
                        continue
                    ids = [r["id"] for r in rows]
                    history_rows = [
                        (r["id"], r["current_price"], False, anchor_run_id) for r in rows
                    ]
                    with conn.cursor() as cur:
                        cur.execute(
                            "UPDATE vendor_listings SET in_stock = false WHERE id = ANY(%s)",
                            (ids,),
                        )
                        updated = cur.rowcount
                        cur.executemany(
                            "INSERT INTO price_history (listing_id, price, in_stock, scraper_run_id) "
                            "VALUES (%s, %s, %s, %s)",
                            history_rows,
                        )
                    total_updated += updated
                    total_history += len(history_rows)
                    print(f"  [{slug}] UPDATE rowcount={updated}; price_history INSERT count={len(history_rows)}")
            print()
            print(f"Transaction COMMITTED. UPDATE total={total_updated}; price_history INSERT total={total_history}")
        finally:
            conn.autocommit = True

        # Phase 3 — post-update verify-pass (autocommit=True).
        print()
        print("=" * 78)
        print("Post-update C2 verify-pass — re-running stale-rowset predicate")
        print("=" * 78)
        all_clean = True
        for vendor_id, slug, _, _ in pending:
            post_stale = _fetch_stale_rows(conn, vendor_id)
            verdict = "CLEAN" if len(post_stale) == 0 else f"RESIDUAL ({len(post_stale)} rows)"
            print(f"  [{slug}] stale_rowset post-update: {len(post_stale)} rows -- {verdict}")
            if post_stale:
                all_clean = False
                _print_sample(post_stale, k=5)
        print()
        if all_clean:
            print("VERIFY-PASS CLEAN — BC + UC stale rowsets are empty post-UPDATE.")
        else:
            print("VERIFY-PASS RESIDUAL — surface to /lead-backend before close-flip.")
        return 0


def _verify_audit_anchor(conn, anchor_run_id: int, expected_vendor_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT status, vendor_id, finished_at, listings_seen, git_sha "
            "FROM scraper_runs WHERE id = %s",
            (anchor_run_id,),
        )
        row = cur.fetchone()
    if row is None:
        raise RuntimeError(f"audit anchor run_id={anchor_run_id} not found")
    if row["status"] != "success":
        raise RuntimeError(
            f"audit anchor run_id={anchor_run_id} status={row['status']!r} != 'success'"
        )
    if row["vendor_id"] != expected_vendor_id:
        raise RuntimeError(
            f"audit anchor run_id={anchor_run_id} vendor_id={row['vendor_id']} "
            f"!= expected {expected_vendor_id}"
        )
    print(
        f"  audit anchor verified: status=success vendor_id={expected_vendor_id} "
        f"finished_at={row['finished_at']} listings_seen={row['listings_seen']} "
        f"git_sha={row['git_sha'][:8]}"
    )


def _derive_partition_b(conn, vendor_id: int, slug: str) -> tuple[list[dict], int]:
    """Re-derive PARTITION-B IDs by running the D-1 mechanism: pull stale
    rowset, fetch /products.json, classify each stale row. PARTITION-B =
    URL in catalog + _should_keep returns False.
    """
    cfg = _load_yaml(slug)
    base_url = cfg["base_url"].rstrip("/")
    request_delay = float(cfg.get("request_delay_sec", 2.0))
    page_size = int(cfg.get("page_size", 250))
    max_pages = int(cfg.get("max_pages", 5))
    category_filter = cfg.get("category_filter") or {}
    in_stock_only = bool(cfg.get("in_stock_only", False))

    stale_rows = _fetch_stale_rows(conn, vendor_id)
    if not stale_rows:
        return [], 0

    products_by_url = _fetch_products_json(base_url, page_size, max_pages, request_delay)
    partition_b: list[dict] = []
    partition_c_count = 0
    for row in stale_rows:
        product = products_by_url.get(row["product_url"])
        if product is None:
            continue  # PARTITION-A — out of CTK-107 scope (CTK-105 territory)
        if _should_keep(product, category_filter, in_stock_only):
            partition_c_count += 1
            continue  # PARTITION-C — would have been re-seen; HOLD (per D-1 rule)
        partition_b.append(row)

    if partition_c_count > 0:
        print(
            f"  WARNING: PARTITION-C count for {slug} = {partition_c_count} (re-derive drift "
            f"vs. D-1 = 0). Surface to /lead-backend before --execute fires."
        )
    return partition_b, len(stale_rows)


def _print_sample(rows: list[dict], k: int = 5) -> None:
    head = rows[: min(k, len(rows))]
    print(f"  sample ({len(head)} of {len(rows)}):")
    for r in head:
        price = f"{r['current_price']}" if r["current_price"] is not None else "(null)"
        title = (r["raw_title"] or "")[:60]
        print(f"    id={r['id']:>6}  price={price:>8}  title={title!r}")


if __name__ == "__main__":
    sys.exit(main())
