"""CTK-119 D-3 — bridge UPDATE for the WWC available-with-dead-link class.

Flips the WS-prefix + promo-tail rows to in_stock=false AFTER the D-1
denylist is live on origin/main (ordering hazard per CTK-119 plan.md:
bridge-first would restock-flap on the next scrape; denylist-first strands
the rows in filtered_urls where nothing ever flips them — so this script IS
the flip, and the post-bridge survival scrape is the verify).

IN-list is re-derived at execution time (the 2026-06-04 sweep list will have
churned): vendor_id=2 + in_stock=true + (raw_title anchored-ILIKE 'WS - %'
OR substring-ILIKE one of the PROMO_ENTRIES below — a HAND-MAINTAINED mirror
of the wwc.yaml promo title_denylist semantics, not derived from the YAML;
keep it in step on any entry change (/code-review fold #1, 2026-06-06).
Entries carry $ and / but no LIKE wildcards (%/_); escape before reuse if
that changes.

Safety rails, in order:
  1. HEAD spot-check (every Nth row, ~10 total, 2s polite pacing) — each
     must be non-200; any 200 aborts (class no longer dead, or a collision
     slipped in).
  2. Audit anchor = most-recent vendor_id=2 status='success' run, verified +
     printed with git_sha so the operator can confirm it's a post-D-1 run
     (listings_seen should sit ~76 below the pre-D-1 band).
  3. Pre-bridge snapshot (CTK-119 review-fold #2): the executed IN-list +
     prior state (id, in_stock, current_price, raw_title, product_url) is
     written to --snapshot-out BEFORE the UPDATE.
  4. Single transaction: UPDATE + audit-trail price_history INSERTs
     (CTK-104/107 bridge shape — last-known price preserved, NULL tolerated
     per ids 15771/15781; price_history.price is nullable, 51 precedent
     rows).
  5. Post-verify: re-fetch, all rows in_stock=false.

Two modes:
  --dry-run (default): derive + spot-check + print intent; no writes.
  --execute --snapshot-out PATH: full run.

Run via:
  python -m scripts.ctk119_d3_bridge [--execute --snapshot-out PATH]
"""

from __future__ import annotations

import argparse
import json
import sys
import time

import requests

from scrapers.common.db import get_conn

WWC_VENDOR_ID = 2
HEAD_SPOT_CHECKS = 10
HEAD_DELAY_SEC = 2.0
HEAD_UA = "Mozilla/5.0 (CoralTicker CTK-119 route-liveness spot-check)"

# HAND-MAINTAINED mirror of wwc.yaml title_denylist CTK-119 promo entries
# (substring semantics -> %...% ILIKE): 6 exact-compound + the 'Build A'
# family entry (D-2 lock 2026-06-06; subsumes the former May $25 exact
# entry). The prefix entry mirrors ANCHORED (no leading %).
PROMO_ENTRIES = [
    "Acro Frag POS",
    "Special Sale - Frag",
    "BOGO Beginner SPS Frag",
    "$10 GSP Frag",
    "Favia/Favites BOGO",
    "Build A",
    "Rainbow Hammer January Special",
]


def derive_in_list(conn) -> list[dict]:
    promo_clauses = " OR ".join(["raw_title ILIKE %s"] * len(PROMO_ENTRIES))
    params = [WWC_VENDOR_ID] + [f"%{e}%" for e in PROMO_ENTRIES]
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, raw_title, current_price, in_stock, product_url "
            "FROM vendor_listings "
            f"WHERE vendor_id = %s AND in_stock = true "
            f"AND (raw_title ILIKE 'WS - %%' OR {promo_clauses}) "
            "ORDER BY id",
            params,
        )
        return cur.fetchall()


def head_spot_check(rows: list[dict]) -> int:
    """Probe every Nth row; return count of 200s (must be 0 to proceed)."""
    step = max(1, len(rows) // HEAD_SPOT_CHECKS)
    sample = rows[::step][:HEAD_SPOT_CHECKS]
    live = 0
    print(f"HEAD spot-check: {len(sample)} of {len(rows)} rows, {HEAD_DELAY_SEC}s pacing")
    for r in sample:
        try:
            resp = requests.head(
                r["product_url"], headers={"User-Agent": HEAD_UA},
                timeout=20, allow_redirects=False,
            )
            status = resp.status_code
        except requests.RequestException as e:
            status = f"ERR {type(e).__name__}"
        marker = ""
        if status == 200:
            live += 1
            marker = "  <- LIVE ROUTE, ABORT CANDIDATE"
        print(f"  id={r['id']:>6} HTTP {status} {(r['raw_title'] or '')[:48]!r}{marker}")
        time.sleep(HEAD_DELAY_SEC)
    return live


def latest_success_anchor(conn) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, status, finished_at, listings_seen, git_sha "
            "FROM scraper_runs WHERE vendor_id = %s AND status = 'success' "
            "ORDER BY id DESC LIMIT 1",
            (WWC_VENDOR_ID,),
        )
        row = cur.fetchone()
    if row is None:
        raise RuntimeError("no success run found for WWC — no valid anchor")
    print(
        f"audit anchor: run_id={row['id']} finished_at={row['finished_at']} "
        f"listings_seen={row['listings_seen']} git_sha={(row['git_sha'] or '')[:8]}"
    )
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--execute", action="store_true",
                        help="Fire UPDATE + INSERTs in a single transaction (default: dry-run).")
    parser.add_argument("--snapshot-out",
                        help="Path for the pre-bridge snapshot artifact (required with --execute).")
    args = parser.parse_args()
    if args.execute and not args.snapshot_out:
        parser.error("--execute requires --snapshot-out (review-fold #2 snapshot artifact)")
    mode = "EXECUTE" if args.execute else "DRY-RUN"

    print("=" * 78)
    print(f"CTK-119 D-3 — bridge UPDATE (mode: {mode})")
    print("=" * 78)

    with get_conn() as conn:
        rows = derive_in_list(conn)
        n_prefix = sum(1 for r in rows if (r["raw_title"] or "").lower().startswith("ws - "))
        n_null_price = sum(1 for r in rows if r["current_price"] is None)
        print(f"IN-list derived: {len(rows)} rows ({n_prefix} WS-prefix, "
              f"{len(rows) - n_prefix} promo, {n_null_price} NULL-price)")
        for r in rows:
            print(f"  id={r['id']:>6} price={r['current_price']} {(r['raw_title'] or '')[:56]!r}")
        if not rows:
            print("IN-list empty — nothing to bridge.")
            return 0

        live = head_spot_check(rows)
        if live:
            print(f"ABORT: {live} spot-checked route(s) returned 200 — class is not "
                  f"uniformly dead; re-audit before bridging.")
            return 1

        anchor = latest_success_anchor(conn)

        if not args.execute:
            print()
            print("DRY-RUN complete. Confirm the anchor above is a POST-D-1 run "
                  "(listings_seen ~76 below the pre-D-1 ~1082 band), then re-run "
                  "with --execute --snapshot-out <path>.")
            return 0

        # Review-fold #2 — snapshot BEFORE any write.
        snapshot = {
            "ticket": "CTK-119",
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
        with open(args.snapshot_out, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, indent=2)
        print(f"pre-bridge snapshot written: {args.snapshot_out} ({len(rows)} rows)")

        print()
        print("Firing UPDATE + price_history INSERTs in single transaction")
        conn.autocommit = False
        try:
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
            print(f"Transaction COMMITTED. UPDATE={updated}; price_history INSERTs={len(history_rows)}")
        finally:
            conn.autocommit = True

        # Post-verify.
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, in_stock FROM vendor_listings WHERE id = ANY(%s)",
                ([r["id"] for r in rows],),
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
