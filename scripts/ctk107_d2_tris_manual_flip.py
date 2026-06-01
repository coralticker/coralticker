"""CTK-107 D-2-tris — hand-coded surgical UPDATE on 11 close-gate
eyeball-fail rows across BC + UC + TSA.

Distinct from D-2 / D-2-bis (which used partition-B re-derivation from
stale rowset): these 11 rows are NOT stale. They're being continuously
seen + accepted by the (pre-D-2-tris) parser on every scrape; the
partition mechanism doesn't catch them. The eyeball gate surfaced them
2026-06-01 Session 4.

Three YAML edits landed in their respective per-vendor commits BEFORE
this script fires (SHAs 5c6546a + 0db1475 + 9a6d0db on origin/main):
  - BC title_denylist += "DCC " + "DCS " + "Impeller" (catches 6 pump rows)
  - UC tag_denylist += "Marco Rocks" + "MarcoRocks" (catches 2 rock rows)
  - TSA tag_denylist += "Biomedia"; NEW title_denylist += "Test Livestock"
    (catches 3 rows: bio media + 2 test placeholders)

YAML pushed FIRST so that on the next cron-fired scrape, the parser
rejects these 11 URLs → they land in filtered_urls → cohort-OOS excludes
them per CTK-094 fold #4 → DB row stays at whatever in_stock value we
set here. This script flips them to in_stock=false; subsequent scrapes
honor the deny + don't UPSERT them back.

Audit-trail price_history INSERTs follow CTK-104 6-fish bridge precedent
+ CTK-107 D-2/D-2-bis per-vendor anchor convention. Anchors:
  BC = run_id 764 (most-recent status='success' at session-open)
  UC = run_id 781 (same)
  TSA = run_id 786 (post-CTK-105-opt-in run, listings_oos=196 — the
        confirmed first-wave cohort-OOS spike, semantically the right
        anchor for TSA writes on 2026-06-01)

Two modes:
  --dry-run   : print intent; no writes
  --execute   : single transaction wrapping UPDATE + INSERTs
"""

from __future__ import annotations

import argparse
import sys

from scrapers.common.db import get_conn

# (vendor_id, slug, anchor_run_id, [(listing_id, raw_title), ...])
# 11 rows total: 6 BC + 2 UC + 3 TSA.
EYEBALL_FAIL_ROWS = [
    (5, "battlecorals", 764, [
        (67732, "DCC 200 SW2 Impeller"),
        (67733, "DCC 200 SW2"),
        (67734, "DCC 300 Impeller"),
        (67735, "DCC 300"),
        (67736, "DCS 700 Impeller"),
        (67737, "DCS 400"),
    ]),
    (6, "unique_corals", 781, [
        (67288, "MarcoRocks Coralline Foundation Rock (20lb & 40lb box)"),
        (67290, "MarcoRocks Coralline Reef Saver Rock (20lb or 40lb Box)"),
    ]),
    (3, "tsa", 786, [
        (35385, "Test Livestock"),
        (35386, "Test Livestock Product"),
        (39368, "Wild Reef Pre-Seeded Bio Media"),
    ]),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Run UPDATE + INSERTs in a single transaction. Without this flag, dry-run only.",
    )
    args = parser.parse_args()
    mode = "EXECUTE" if args.execute else "DRY-RUN"

    print("=" * 78)
    print(f"CTK-107 D-2-tris — hand-coded manual flip (mode: {mode})")
    print("=" * 78)

    with get_conn() as conn:
        # Phase 1 — verify each anchor + pre-fetch current_price for each row.
        pending: list[tuple[int, str, int, list[dict]]] = []
        for vendor_id, slug, anchor_run_id, expected_rows in EYEBALL_FAIL_ROWS:
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
            # Sanity-check expected vs fetched
            for lid, expected_title in expected_rows:
                if lid not in fetched_by_id:
                    raise RuntimeError(f"row id={lid} not found in DB for vendor {slug}")
            print(f"  pre-state: {len(fetched)} rows fetched")
            for lid, expected_title in expected_rows:
                r = fetched_by_id[lid]
                stock_marker = "TRUE" if r["in_stock"] else "false"
                title = (r["raw_title"] or "")[:50]
                print(f"    id={lid:>6}  in_stock={stock_marker:<5}  price={r['current_price']}  {title!r}")
            already_oos = [r for r in fetched if not r["in_stock"]]
            if already_oos:
                print(f"  NOTE: {len(already_oos)} row(s) already in_stock=false; UPDATE is a no-op for those")
            pending.append((vendor_id, slug, anchor_run_id, fetched))

        total = sum(len(rows) for _, _, _, rows in pending)
        print()
        print(f"=== IN-list summary: {total} rows across {len(pending)} vendor(s) ===")
        for _, slug, anchor, rows in pending:
            print(f"  {slug}: {len(rows)} rows -> scraper_run_id={anchor}")

        if not args.execute:
            print()
            print("DRY-RUN complete. Re-run with --execute to fire.")
            return 0

        # Phase 2 — write under explicit transaction.
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
                    print(f"  [{slug}] UPDATE rowcount={updated}; price_history INSERT count={len(history_rows)}")
            print()
            print(f"Transaction COMMITTED. UPDATE total={total_updated}; price_history INSERT total={total_history}")
        finally:
            conn.autocommit = True

        # Phase 3 — verify-pass: confirm all 11 rows now in_stock=false.
        print()
        print("=" * 78)
        print("Post-update verify-pass — re-fetch the 11 ids")
        print("=" * 78)
        all_ids = [lid for _, _, _, rows in pending for lid, in_ in [(r["id"], r["in_stock"]) for r in rows]]
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
            print(f"  RESIDUAL ({len(residual)} rows still in_stock=true):")
            for r in residual:
                print(f"    id={r['id']}")
            return 1
        print()
        print("VERIFY-PASS CLEAN — all 11 rows in_stock=false.")
        return 0


def _verify_anchor(conn, anchor_run_id: int, expected_vendor_id: int) -> None:
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
        raise RuntimeError(f"audit anchor run_id={anchor_run_id} status={row['status']!r} != 'success'")
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


if __name__ == "__main__":
    sys.exit(main())
