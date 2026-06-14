"""CTK-155 — bridge UPDATE for the launch-day junk-listing purge (3 vendors).

Flips the 6 persisted test/placeholder rows across POTO (vendor_id=10), TSA
(vendor_id=3), and WWC (vendor_id=2) to in_stock=false AFTER the CTK-155
denylist entries are live on origin/main. Ordering locked per CTK-132/141/153:
denylist-first strands the active-live rows in filtered intake (a filtered row
never enters the cohort, so cohort_oos_at_persist absent-pass can't flip it), so
this script IS the flip; bridge-first restock-flaps on the next fire. The two
stale rows (TSA 36925, WWC 15795) are still in_stock=true but already intake-
filtered (PT-denied) — stranded in filtered intake, so the cohort_oos absent-
pass can't auto-flip them (a filtered row never enters the cohort). This script
performs their flip; the new denylist entry is belt-and-suspenders for them.

This is the CTK-153 5-rail bridge EXTENDED TO 3 VENDORS — each vendor carries
its own exact-title set + EXPECTED_IDS rail and runs in its own single
transaction. As in CTK-153 the selector is an EXPLICIT EXACT-TITLE set
(`raw_title = ANY(titles)`), not a `raw_title ILIKE` re-derive: the cut is
title-based, the set is small and plan-time-frozen, and the two rails (title-set
+ ID-set) cross-check each other. Catalog churn between plan and execution (the
derived ID set != EXPECTED_IDS) ABORTs that vendor — re-audit, not bridge-anyway.

NOT bridged (forward-bind only, denylist catches them going forward):
  - TSA "Test Supplies Product (UPC)" — already in_stock=false; caught by the
    "Test Suppl" denylist substring but never enters this selector (not in the
    exact-title set, and already OOS). CTK-153 already-OOS precedent.

Safety rails, in order, PER VENDOR (same 5 as scripts/ctk153_bridge.py):
  1. Expected-ID-set check: derived in-stock IN-list must equal EXPECTED_IDS AND
     its titles must be a subset of the frozen title set, or abort that vendor.
  2. Audit anchor = most-recent status='success' run for that vendor, printed
     with git_sha so the operator can confirm it is a post-denylist run.
  3. Pre-bridge snapshot: the executed IN-lists + prior state for ALL vendors
     written to --snapshot-out BEFORE any write (exclusive-create — refuses to
     overwrite an earlier rollback artifact).
  4. Single transaction per vendor: UPDATE in_stock=false + price_history audit
     INSERTs (CTK-104/107/119/132/141/153 bridge shape — last-known price
     preserved).
  5. Post-verify: re-fetch, all rows in_stock=false.

Two modes:
  --dry-run (default): derive + rail-check all vendors + print intent; no writes.
  --execute --snapshot-out PATH: full run.

Run via:
  python -m scripts.ctk155_bridge [--execute --snapshot-out PATH]
"""

from __future__ import annotations

import argparse
import json
import sys

from scrapers.common.db import get_conn

# Plan Appendix A (2026-06-14 live + DB audit). Titles byte-exact.
VENDORS = {
    10: {  # POTO — Pieces of the Ocean
        "label": "poto",
        "titles": ["Title"],
        "expected_ids": {72999},
    },
    3: {  # TSA — Top Shelf Aquatics
        "label": "tsa",
        "titles": [
            "Live stock test",
            "Live stock test b",
            "Test Supply",
            "Test Supplies Product",
        ],
        "expected_ids": {35514, 36218, 36219, 36925},
    },
    2: {  # WWC — World Wide Corals
        "label": "wwc",
        "titles": ["test-WWC Striptease Acropora"],
        "expected_ids": {15795},
    },
}


def derive_in_list(conn, vendor_id: int, titles: list[str]) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, raw_title, current_price, in_stock, product_url "
            "FROM vendor_listings "
            "WHERE vendor_id = %s AND in_stock = true AND raw_title = ANY(%s) "
            "ORDER BY id",
            (vendor_id, titles),
        )
        return cur.fetchall()


def latest_success_anchor(conn, vendor_id: int, label: str) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, status, finished_at, listings_seen, git_sha "
            "FROM scraper_runs WHERE vendor_id = %s AND status = 'success' "
            "ORDER BY id DESC LIMIT 1",
            (vendor_id,),
        )
        row = cur.fetchone()
    if row is None:
        raise RuntimeError(f"no success run found for {label} — no valid anchor")
    print(
        f"  audit anchor: run_id={row['id']} finished_at={row['finished_at']} "
        f"listings_seen={row['listings_seen']} git_sha={(row['git_sha'] or '')[:8]}"
    )
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--execute", action="store_true",
                        help="Fire UPDATE + INSERTs per vendor in single transactions (default: dry-run).")
    parser.add_argument("--snapshot-out",
                        help="Path for the pre-bridge snapshot artifact (required with --execute).")
    args = parser.parse_args()
    if args.execute and not args.snapshot_out:
        parser.error("--execute requires --snapshot-out (pre-bridge snapshot artifact)")
    mode = "EXECUTE" if args.execute else "DRY-RUN"

    print("=" * 78)
    print(f"CTK-155 — launch-day junk purge bridge, 3 vendors (mode: {mode})")
    print("=" * 78)

    with get_conn() as conn:
        # ── Pass 1: derive + rail-check EVERY vendor before any write ──────────
        plan: list[dict] = []
        for vendor_id, cfg in VENDORS.items():
            label = cfg["label"]
            print(f"\n[{label}] (vendor_id={vendor_id})")
            rows = derive_in_list(conn, vendor_id, cfg["titles"])
            ids = {r["id"] for r in rows}
            for r in rows:
                print(f"  id={r['id']:>6} price={r['current_price']} "
                      f"{(r['raw_title'] or '')[:56]!r}")
            # Rail 1: ID-set must equal EXPECTED_IDS.
            if ids != cfg["expected_ids"]:
                print(f"ABORT [{label}]: derived in-stock IN-list {sorted(ids)} != "
                      f"expected {sorted(cfg['expected_ids'])} — catalog churned since "
                      f"plan-time audit; re-run the two-lens FP audit before bridging.")
                return 1
            # Title-set cross-check (selector enforces this, but pin it so a future
            # EXPECTED_IDS edit can't silently widen the title scope).
            frozen = set(cfg["titles"])
            stray = [r for r in rows if r["raw_title"] not in frozen]
            if stray:
                print(f"ABORT [{label}]: {len(stray)} selected row(s) carry a title "
                      f"outside the frozen set: {[r['id'] for r in stray]}")
                return 1
            anchor = latest_success_anchor(conn, vendor_id, label)
            print(f"  rail-check PASS: {len(rows)} rows, IN-list == EXPECTED_IDS, "
                  f"titles in frozen set.")
            plan.append({"vendor_id": vendor_id, "label": label, "rows": rows,
                         "anchor": anchor})

        total = sum(len(p["rows"]) for p in plan)
        print(f"\nrail-check PASS for all {len(plan)} vendors; {total} rows to bridge.")

        if not args.execute:
            print("\nDRY-RUN complete. The anchor is each vendor's latest success run — "
                  "a pre-push git_sha is EXPECTED (plan ordering: bridge immediately "
                  "after the denylist push, before any post-push fire; the anchor is an "
                  "audit pointer, not a gate). Re-run with --execute --snapshot-out <path>.")
            return 0

        # ── Rail 3: snapshot ALL vendors BEFORE any write (exclusive-create) ──
        snapshot = {
            "ticket": "CTK-155",
            "vendors": [
                {
                    "vendor_id": p["vendor_id"],
                    "label": p["label"],
                    "anchor_run_id": p["anchor"]["id"],
                    "anchor_git_sha": p["anchor"]["git_sha"],
                    "rows": [
                        {
                            "id": r["id"],
                            "in_stock": r["in_stock"],
                            "current_price": str(r["current_price"]) if r["current_price"] is not None else None,
                            "raw_title": r["raw_title"],
                            "product_url": r["product_url"],
                        }
                        for r in p["rows"]
                    ],
                }
                for p in plan
            ],
        }
        with open(args.snapshot_out, "x", encoding="utf-8") as f:
            json.dump(snapshot, f, indent=2, ensure_ascii=False)
        print(f"\npre-bridge snapshot written: {args.snapshot_out} ({total} rows)")

        # ── Rail 4: single transaction PER VENDOR ─────────────────────────────
        # conn.transaction() on the autocommit connection issues its own
        # BEGIN/COMMIT and resumes autocommit on exit (the canonical
        # persist_phase_a write path — no manual autocommit toggle needed). If a
        # vendor's transaction raises, that vendor rolls back; we STOP attempting
        # further vendors and fall through to the Rail 5 post-verify, which
        # reports the not-yet-flipped rows as RESIDUAL and exits non-zero — so a
        # mid-run failure surfaces loudly, never as a silent half-applied state.
        bridge_error: Exception | None = None
        for p in plan:
            label, rows, anchor = p["label"], p["rows"], p["anchor"]
            id_list = [r["id"] for r in rows]
            history_rows = [(r["id"], r["current_price"], False, anchor["id"]) for r in rows]
            try:
                with conn.transaction():
                    with conn.cursor() as cur:
                        cur.execute(
                            "UPDATE vendor_listings SET in_stock = false WHERE id = ANY(%s)",
                            (id_list,),
                        )
                        updated = cur.rowcount
                        if updated != len(id_list):
                            # Loud in-transaction invariant: the UPDATE must hit
                            # exactly the rail-checked rows. A mismatch means a row
                            # vanished between derive and write — raise to roll this
                            # vendor back rather than commit a partial flip.
                            raise RuntimeError(
                                f"[{label}] UPDATE matched {updated} rows, expected "
                                f"{len(id_list)} {sorted(id_list)} — catalog churned mid-run."
                            )
                        cur.executemany(
                            "INSERT INTO price_history (listing_id, price, in_stock, scraper_run_id) "
                            "VALUES (%s, %s, %s, %s)",
                            history_rows,
                        )
                print(f"  [{label}] COMMITTED. UPDATE={updated}; "
                      f"price_history INSERTs={len(history_rows)}")
            except Exception as e:  # surface loudly, stop, let Rail 5 report residuals
                bridge_error = e
                print(f"  [{label}] FAILED, rolled back: {e}")
                print("  STOPPING — earlier vendors stay committed; Rail 5 flags the "
                      "unflipped rows as RESIDUAL.")
                break

        # ── Rail 5: post-verify all vendors ───────────────────────────────────
        all_ids = [r["id"] for p in plan for r in p["rows"]]
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
        if bridge_error is not None:
            print("INCOMPLETE: a vendor failed mid-run (see above) — re-audit before re-run.")
            return 1
        print(f"VERIFY-PASS CLEAN — all {len(post)} rows in_stock=false.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
