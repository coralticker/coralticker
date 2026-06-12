"""CTK-141 — bridge UPDATE for the BC equipment + WWC service leak rows.

Flips the four leaked non-coral rows to in_stock=false AFTER the CTK-141
denylist entries are live on origin/main (ordering locked per CTK-132:
denylist-first strands the rows in filtered intake where the cohort
absent-pass can't flip them, so this script IS the flip; bridge-first
restock-flaps on the next fire).

IN-lists are re-derived at execution time via vendor-scoped ILIKE — a
HAND-MAINTAINED mirror of the YAML title_denylist semantics, not derived
from the YAML; keep in step on any entry change (CTK-119 /code-review
fold #1 precedent):
  BC  (vendor_id=5): raw_title ILIKE '%cleaning head%' OR '%replacement roll%'
  WWC (vendor_id=2): raw_title ILIKE '%shipping%'

Shape divergence from scripts/ctk119_d3_bridge.py: NO dead-route HEAD rail.
The CTK-119 class was available-with-dead-link (routes had to be non-200);
the CTK-141 rows are live vendor products being delisted from OUR catalog
as wrong-category — their routes are expected 200, and a liveness probe
proves nothing here. The replacement rail is the expected-ID-set check:
the derived IN-list must equal the plan-time sets (BC {67701, 67719,
67720}, WWC {16300}) or the script aborts — catalog churn between plan and
execution means re-audit, not bridge-anyway.

Safety rails, in order:
  1. Expected-ID-set check per vendor (abort on drift).
  2. Audit anchor per vendor = most-recent status='success' run, printed
     with git_sha so the operator can confirm it is a post-denylist run.
  3. Pre-bridge snapshot: both vendors' executed IN-lists + prior state
     written to --snapshot-out BEFORE any write.
  4. Single transaction PER VENDOR: UPDATE + price_history audit INSERTs
     (CTK-104/107/119/132 bridge shape — last-known price preserved).
  5. Post-verify: re-fetch, all rows in_stock=false.

Two modes:
  --dry-run (default): derive + rail-check + print intent; no writes.
  --execute --snapshot-out PATH: full run.

Run via:
  python -m scripts.ctk141_bridge [--execute --snapshot-out PATH]
"""

from __future__ import annotations

import argparse
import json
import sys

from scrapers.common.db import get_conn

VENDORS = [
    {
        "slug": "battlecorals",
        "vendor_id": 5,
        "ilike_entries": ["cleaning head", "replacement roll"],
        "expected_ids": {67701, 67719, 67720},
    },
    {
        "slug": "wwc",
        "vendor_id": 2,
        "ilike_entries": ["shipping"],
        "expected_ids": {16300},
    },
]


def derive_in_list(conn, vendor: dict) -> list[dict]:
    clauses = " OR ".join(["raw_title ILIKE %s"] * len(vendor["ilike_entries"]))
    params = [vendor["vendor_id"]] + [f"%{e}%" for e in vendor["ilike_entries"]]
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, raw_title, current_price, in_stock, product_url "
            "FROM vendor_listings "
            f"WHERE vendor_id = %s AND in_stock = true AND ({clauses}) "
            "ORDER BY id",
            params,
        )
        return cur.fetchall()


def latest_success_anchor(conn, vendor: dict) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, status, finished_at, listings_seen, git_sha "
            "FROM scraper_runs WHERE vendor_id = %s AND status = 'success' "
            "ORDER BY id DESC LIMIT 1",
            (vendor["vendor_id"],),
        )
        row = cur.fetchone()
    if row is None:
        raise RuntimeError(f"no success run found for {vendor['slug']} — no valid anchor")
    print(
        f"  audit anchor: run_id={row['id']} finished_at={row['finished_at']} "
        f"listings_seen={row['listings_seen']} git_sha={(row['git_sha'] or '')[:8]}"
    )
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--execute", action="store_true",
                        help="Fire UPDATE + INSERTs in a single transaction per vendor (default: dry-run).")
    parser.add_argument("--snapshot-out",
                        help="Path for the pre-bridge snapshot artifact (required with --execute).")
    args = parser.parse_args()
    if args.execute and not args.snapshot_out:
        parser.error("--execute requires --snapshot-out (pre-bridge snapshot artifact)")
    mode = "EXECUTE" if args.execute else "DRY-RUN"

    print("=" * 78)
    print(f"CTK-141 — bridge UPDATE, BC equipment + WWC service rows (mode: {mode})")
    print("=" * 78)

    with get_conn() as conn:
        # Rail 1+2: derive + check every vendor BEFORE any write.
        staged = []
        for vendor in VENDORS:
            print(f"{vendor['slug']} (vendor_id={vendor['vendor_id']}):")
            rows = derive_in_list(conn, vendor)
            ids = {r["id"] for r in rows}
            for r in rows:
                print(f"  id={r['id']:>6} price={r['current_price']} {(r['raw_title'] or '')[:56]!r}")
            if ids != vendor["expected_ids"]:
                print(f"ABORT: derived IN-list {sorted(ids)} != expected "
                      f"{sorted(vendor['expected_ids'])} — catalog churned since "
                      f"plan-time audit; re-run the two-lens FP audit before bridging.")
                return 1
            anchor = latest_success_anchor(conn, vendor)
            staged.append((vendor, rows, anchor))

        if not args.execute:
            print()
            print("DRY-RUN complete. Anchors are the latest success runs — pre-push "
                  "git_sha is EXPECTED (plan ordering: bridge immediately after the "
                  "denylist push, before any post-push fire; the anchor is an audit "
                  "pointer, not a gate). Re-run with --execute --snapshot-out <path>.")
            return 0

        # Rail 3: snapshot BEFORE any write.
        snapshot = {
            "ticket": "CTK-141",
            "vendors": {
                vendor["slug"]: {
                    "anchor_run_id": anchor["id"],
                    "anchor_git_sha": anchor["git_sha"],
                    "rows": [
                        {
                            "id": r["id"],
                            "in_stock": r["in_stock"],
                            "current_price": str(r["current_price"]) if r["current_price"] is not None else None,
                            "raw_title": r["raw_title"],
                            "product_url": r["product_url"],
                        }
                        for r in rows
                    ],
                }
                for vendor, rows, anchor in staged
            },
        }
        with open(args.snapshot_out, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, indent=2)
        n_rows = sum(len(rows) for _, rows, _ in staged)
        print(f"pre-bridge snapshot written: {args.snapshot_out} ({n_rows} rows, {len(staged)} vendors)")

        # Rail 4: single transaction per vendor.
        conn.autocommit = False
        try:
            for vendor, rows, anchor in staged:
                print(f"{vendor['slug']}: firing UPDATE + price_history INSERTs in single transaction")
                with conn.transaction():
                    ids = [r["id"] for r in rows]
                    history_rows = [
                        (r["id"], r["current_price"], False, anchor["id"]) for r in rows
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
                print(f"  COMMITTED. UPDATE={updated}; price_history INSERTs={len(history_rows)}")
        finally:
            conn.autocommit = True

        # Rail 5: post-verify across all bridged ids.
        all_ids = [r["id"] for _, rows, _ in staged for r in rows]
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, in_stock FROM vendor_listings WHERE id = ANY(%s)",
                (all_ids,),
            )
            post = cur.fetchall()
        residual = [r for r in post if r["in_stock"]]
        if residual:
            print(f"RESIDUAL: {len(residual)} row(s) still in_stock=true: "
                  f"{[r['id'] for r in residual]}")
            return 1
        print(f"VERIFY-PASS CLEAN — all {len(post)} rows in_stock=false.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
