"""CTK-153 — bridge UPDATE for the UC "Shopify Collective" Dalua dropship wave.

Flips the 23 leaked non-coral Unique Corals rows (vendor_id=6) to
in_stock=false AFTER the CTK-153 `tag_denylist: Dalua International LLC` entry
is live on origin/main. Ordering locked per CTK-132/141: denylist-first
strands the rows in filtered intake where UC's cohort_oos_at_persist absent-
pass can't flip them (the filtered row never enters the cohort), so this
script IS the flip; bridge-first restock-flaps on the next :29 fire.

SELECTOR DIVERGENCE FROM CTK-141 (the one substantive shape change):
  CTK-141 derived its IN-list via vendor-scoped `raw_title ILIKE` because that
  ticket's filter cut was TITLE-based (substring entries like '%shipping%').
  CTK-153's filter cut is TAG-based (`tag_denylist: Dalua International LLC`),
  and (a) the DB stores NO tag column to mirror that cut against, and (b) the
  23 leak titles share NO clean substring token (they are unrelated product
  names — "VCA AI Prime Visor", "Dual Random Flow Generators", "Shrimp Bickies
  SAS", a marketing-string row, ...). So the bridge cannot re-derive the cut
  semantically. It instead carries an EXPLICIT EXACT-TITLE set (TITLES below,
  plan Appendix A) and selects `raw_title = ANY(TITLES)`, guarded by the
  EXPECTED_IDS rail {165756..165778}. Both must agree at execution or the
  script ABORTs — catalog churn between plan and execution means re-audit, not
  bridge-anyway. This is a closed, plan-time-frozen set, NOT a live re-derive;
  the two rails (title-set + ID-set) cross-check each other.

  One leak title carries an em-dash (U+2014): "Trigger natural feeding
  behaviour in minutes — without polluting your tank." Preserved byte-exact in
  TITLES; a hyphen substitution would silently drop that row from the selector.

2 ALREADY-OOS Dalua rows (ids 67119 "Pixel Nano Arm", 67134 "Pixel Rear Arm")
= forward-bind ONLY, no bridge (CTK-141 TSA-132583 precedent). They are not in
the 23 leak titles and never enter this selector; the denylist entry catches
them on the next scrape so they stay OOS.

Safety rails, in order (same 5 as scripts/ctk141_bridge.py):
  1. Expected-ID-set check: derived in-stock IN-list must equal EXPECTED_IDS
     {165756..165778} AND its titles must be a subset of TITLES, or abort.
  2. Audit anchor = most-recent status='success' run, printed with git_sha so
     the operator can confirm it is a post-denylist run.
  3. Pre-bridge snapshot: the executed IN-list + prior state written to
     --snapshot-out BEFORE any write (exclusive-create — refuses to overwrite
     an earlier rollback artifact).
  4. Single transaction: UPDATE in_stock=false + price_history audit INSERTs
     (CTK-104/107/119/132/141 bridge shape — last-known price preserved).
  5. Post-verify: re-fetch, all rows in_stock=false.

Two modes:
  --dry-run (default): derive + rail-check + print intent; no writes.
  --execute --snapshot-out PATH: full run.

Run via:
  python -m scripts.ctk153_bridge [--execute --snapshot-out PATH]
"""

from __future__ import annotations

import argparse
import json
import sys

from scrapers.common.db import get_conn

VENDOR_ID = 6  # Unique Corals

# Plan Appendix A (2026-06-13 live + DB audit). Byte-exact titles — the em-dash
# in the "Trigger natural feeding behaviour..." row is U+2014, do not normalize.
TITLES = [
    "Dual Random Flow Generators",
    "Lid and Dosing Line",
    "Phat Fundamental Fertiliser",
    "Phat Shrimp Fertiliser",
    "Phat Traces Top Up Fertiliser",
    "Rail Mounting System (RMS)",
    "Rotatable Holder Vitamini",
    "Shrimp Aid SAS",
    "Shrimp Bickies SAS",
    "Shrimp Bits SAS",
    "Shrimp Food Spectrum Gold",
    "Shrimp Food Spectrum Red",
    "Shrimp Mineral Booster by SAS",
    "Shrimp Pops By SAS",
    "Shrimp Snow SAS",
    "Shrimp Sticks SAS",
    "Trigger natural feeding behaviour in minutes — without polluting your tank.",
    "VCA AI Prime Visor",
    "VCA Salinity Probe Kit",
    "Vitamini Rotatable Mounts",
    "X4 Hanging Kit",
    "X4 Rear Mounting Arm",
    "X4 Rear Mounting Arm Euro Brace Upgrade Kit Only",
]

EXPECTED_IDS = set(range(165756, 165779))  # contiguous ingest batch 165756..165778


def derive_in_list(conn) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, raw_title, current_price, in_stock, product_url "
            "FROM vendor_listings "
            "WHERE vendor_id = %s AND in_stock = true AND raw_title = ANY(%s) "
            "ORDER BY id",
            (VENDOR_ID, TITLES),
        )
        return cur.fetchall()


def latest_success_anchor(conn) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, status, finished_at, listings_seen, git_sha "
            "FROM scraper_runs WHERE vendor_id = %s AND status = 'success' "
            "ORDER BY id DESC LIMIT 1",
            (VENDOR_ID,),
        )
        row = cur.fetchone()
    if row is None:
        raise RuntimeError("no success run found for unique_corals — no valid anchor")
    print(
        f"  audit anchor: run_id={row['id']} finished_at={row['finished_at']} "
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
        parser.error("--execute requires --snapshot-out (pre-bridge snapshot artifact)")
    mode = "EXECUTE" if args.execute else "DRY-RUN"

    print("=" * 78)
    print(f"CTK-153 — bridge UPDATE, unique_corals (vendor_id={VENDOR_ID}) (mode: {mode})")
    print("=" * 78)

    with get_conn() as conn:
        # Rail 1: derive + cross-check both rails BEFORE any write.
        rows = derive_in_list(conn)
        ids = {r["id"] for r in rows}
        for r in rows:
            print(f"  id={r['id']:>6} price={r['current_price']} {(r['raw_title'] or '')[:56]!r}")
        if ids != EXPECTED_IDS:
            print(f"ABORT: derived in-stock IN-list {sorted(ids)} != expected "
                  f"{sorted(EXPECTED_IDS)} — catalog churned since plan-time audit; "
                  f"re-run the two-lens FP audit before bridging.")
            return 1
        # Title-set cross-check: every selected row's title is in the frozen
        # set (selector already enforces this, but pin it explicitly so a future
        # EXPECTED_IDS edit can't silently widen the title scope).
        stray = [r for r in rows if r["raw_title"] not in set(TITLES)]
        if stray:
            print(f"ABORT: {len(stray)} selected row(s) carry a title outside the "
                  f"frozen TITLES set: {[r['id'] for r in stray]}")
            return 1
        print(f"  rail-check PASS: {len(rows)} rows, IN-list == EXPECTED_IDS, titles in frozen set.")

        # Rail 2: audit anchor.
        anchor = latest_success_anchor(conn)

        if not args.execute:
            print()
            print("DRY-RUN complete. The anchor is the latest success run — a pre-push "
                  "git_sha is EXPECTED (plan ordering: bridge immediately after the "
                  "denylist push, before any post-push fire; the anchor is an audit "
                  "pointer, not a gate). Re-run with --execute --snapshot-out <path>.")
            return 0

        # Rail 3: snapshot BEFORE any write (exclusive-create).
        snapshot = {
            "ticket": "CTK-153",
            "vendor_id": VENDOR_ID,
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
        with open(args.snapshot_out, "x", encoding="utf-8") as f:
            json.dump(snapshot, f, indent=2, ensure_ascii=False)
        print(f"pre-bridge snapshot written: {args.snapshot_out} ({len(rows)} rows)")

        # Rail 4: single transaction — UPDATE + price_history INSERTs.
        conn.autocommit = False
        try:
            with conn.transaction():
                id_list = [r["id"] for r in rows]
                history_rows = [
                    (r["id"], r["current_price"], False, anchor["id"]) for r in rows
                ]
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE vendor_listings SET in_stock = false WHERE id = ANY(%s)",
                        (id_list,),
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

        # Rail 5: post-verify.
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
