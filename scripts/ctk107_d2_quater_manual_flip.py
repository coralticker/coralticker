"""CTK-107 D-2-quater — hand-coded surgical UPDATE on 6 close-gate
eyeball-fail round-2 rows across BC + POTO + Vivid.

Same shape as D-2-tris: rows are non-stale (continuously seen + parser-
accepted on every scrape pre-edit). Eyeball gate surfaced them
2026-06-01 Session 5; partition mechanism doesn't catch (PARTITION-C-by-
definition only flags stale-but-accepted).

Three YAML edits landed in per-vendor commits BEFORE this script fires:
  - BC (SHA 5ae3cbc): title_denylist += "All stars" + "Battlegrass" +
    "Battle 2022" (specific) + "Chaeto" + "Cheato" + "Macroalgae" +
    "Macro Algae" (fleet-wide defensive)
  - POTO (SHA e96e8dd): NEW title_denylist block with 4 chaeto patterns
  - Vivid (SHA 477f684): NEW title_denylist block with 4 chaeto patterns

Audit-trail anchors (per-vendor most-recent status='success' at session-
open):
  BC = run_id 764 (same as D-2 / D-2-tris)
  POTO = run_id 807 (NEW; finished 2026-06-02 02:07 UTC, SHA d58f8db7)
  Vivid = run_id 803 (NEW; finished 2026-06-02 01:38 UTC, SHA d58f8db7)

Two modes: --dry-run (default) / --execute.
"""

from __future__ import annotations

import argparse
import sys

from scrapers.common.db import get_conn

# (vendor_id, slug, anchor_run_id, [(listing_id, expected_title), ...])
EYEBALL_FAIL_ROUND2_ROWS = [
    (5, "battlecorals", 764, [
        (67515, "BC All stars grow out  2025!!!"),
        (67712, "Battlegrass"),
        (67591, "Blood Bank Battle 2022"),
    ]),
    (10, "poto", 807, [
        (72884, "Atomic Broccoli Macroalgae"),
        (72921, "Nice bag full of CHEATO"),
    ]),
    (8, "vivid_aquariums", 803, [
        (72681, "Chaetomorpha Macro Algae"),
    ]),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--execute", action="store_true",
                        help="Run UPDATE + INSERTs in a single transaction.")
    args = parser.parse_args()
    mode = "EXECUTE" if args.execute else "DRY-RUN"

    print("=" * 78)
    print(f"CTK-107 D-2-quater — round-2 manual flip (mode: {mode})")
    print("=" * 78)

    with get_conn() as conn:
        pending = []
        for vendor_id, slug, anchor_run_id, expected_rows in EYEBALL_FAIL_ROUND2_ROWS:
            print()
            print(f"--- {slug} (vendor_id={vendor_id}, anchor_run_id={anchor_run_id}) ---")
            _verify_anchor(conn, anchor_run_id, vendor_id)
            ids = [lid for lid, _ in expected_rows]
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, raw_title, current_price, in_stock "
                    "FROM vendor_listings WHERE id = ANY(%s) ORDER BY id",
                    (ids,),
                )
                fetched = cur.fetchall()
            fetched_by_id = {r["id"]: r for r in fetched}
            for lid, _ in expected_rows:
                if lid not in fetched_by_id:
                    raise RuntimeError(f"row id={lid} not found in DB for vendor {slug}")
            print(f"  pre-state: {len(fetched)} rows")
            for lid, _ in expected_rows:
                r = fetched_by_id[lid]
                stock = "TRUE" if r["in_stock"] else "false"
                title = (r["raw_title"] or "")[:50]
                print(f"    id={lid:>6}  in_stock={stock:<5}  price={r['current_price']}  {title!r}")
            pending.append((vendor_id, slug, anchor_run_id, fetched))

        total = sum(len(rows) for _, _, _, rows in pending)
        print()
        print(f"=== IN-list summary: {total} rows across {len(pending)} vendor(s) ===")
        for _, slug, anchor, rows in pending:
            print(f"  {slug}: {len(rows)} rows -> scraper_run_id={anchor}")

        if not args.execute:
            print()
            print("DRY-RUN complete. Re-run with --execute.")
            return 0

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
                    print(f"  [{slug}] UPDATE rowcount={updated}; INSERT count={len(history_rows)}")
            print()
            print(f"Transaction COMMITTED. UPDATE total={total_updated}; INSERT total={total_history}")
        finally:
            conn.autocommit = True

        print()
        print("=" * 78)
        print("Post-update verify-pass — re-fetch the 6 ids")
        print("=" * 78)
        all_ids = [r["id"] for _, _, _, rows in pending for r in rows]
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, in_stock FROM vendor_listings WHERE id = ANY(%s) ORDER BY id",
                (all_ids,),
            )
            post = cur.fetchall()
        clean = sum(1 for r in post if not r["in_stock"])
        residual = [r for r in post if r["in_stock"]]
        print(f"  rows now in_stock=false: {clean} / {len(post)}")
        if residual:
            print(f"  RESIDUAL: {[r['id'] for r in residual]}")
            return 1
        print()
        print("VERIFY-PASS CLEAN — all 6 rows in_stock=false.")
        return 0


def _verify_anchor(conn, anchor_run_id, expected_vendor_id):
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
        raise RuntimeError(f"anchor run_id={anchor_run_id} status={row['status']!r} != success")
    if row["vendor_id"] != expected_vendor_id:
        raise RuntimeError(
            f"anchor run_id={anchor_run_id} vendor_id={row['vendor_id']} != {expected_vendor_id}"
        )
    print(f"  audit anchor verified: status=success vendor_id={expected_vendor_id} "
          f"finished_at={row['finished_at']} listings_seen={row['listings_seen']} "
          f"git_sha={row['git_sha'][:8]}")


if __name__ == "__main__":
    sys.exit(main())
