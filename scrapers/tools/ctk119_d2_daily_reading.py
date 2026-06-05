"""CTK-119 D-2 — daily promo-rotation reading over the WWC feed.

One polite-paced /products.json pull per calendar day (day 1 = the 2026-06-04
D-1 audit pull), producing the multi-day rotation sample the plan's D-2
requires before any family pattern (BOGO / POS / Build A / Special / ...)
can lock as a denylist entry. Per reading:

  1. class census — WS-prefix + promo-tail rows in today's feed vs day 1's
     76-kill set; class rows born since the bridge (handle not in the day-1
     set = 63 bridged + 13 known post-sweep);
  2. promo-shaped title scan — family patterns over the full feed, split
     covered-by-denylist vs uncovered, each uncovered hit checked for
     intake-eligibility under the CURRENT filter (an eligible hit is a
     rotated promo SKU leaking into intake — the reactive exact-title-add
     trigger per plan.md review-fold #3);
  3. rotation evidence for the 7 exact promo entries — still feed-published?
  4. PT<->title mapping of the 63 bridged rows (matched by handle) — D-2
     evidence requirement;
  5. DB guard — prefix-row count + promo per-entry single-id check (no new
     class intake since the denylist landed).

Day 3+ passes --prior <previous snapshot> for a true cross-day diff of
promo-shaped titles. Trimmed feed snapshot written to --snapshot-out so the
next day has a diff basis.

Run via:
  python -m scrapers.tools.ctk119_d2_daily_reading \
      --snapshot-out PATH [--prior PATH] [--bridge-snapshot PATH]

Read-only both sides — no writes to Neon. Reads NEON_DATABASE_URL from .env
via scrapers.common.db's load_dotenv().
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import sys

from scrapers.common import db
from scrapers.common.parse_shopify import _should_keep
from scrapers.common.run import _load_yaml
from scrapers.tools.ctk119_d1_two_lens_audit import PROMO_ENTRIES, _fetch_feed

WWC_VENDOR_ID = 2

DEFAULT_BRIDGE_SNAPSHOT = (
    ".claude/plans/tickets/CTK-119/bridge-snapshot-2026-06-04.json"
)

# The 13 class-shaped rows the day-1 audit found in-feed but absent from the
# 2026-06-04 HEAD sweep (born post-sweep; see d1-two-lens-audit-2026-06-04.txt
# incl. its reconciliation note). Together with the 63 bridged handles these
# are the full day-1 class set (76); anything outside it is born since.
DAY1_POST_SWEEP_HANDLES = {
    "ws-wwc-harvest-moon-psammocora-coral",
    "ws-l-kiwilit",
    "ws-z-gpaly",
    "ws-m-rainm",
    "ws-kryptonite-candy-cane",
    "ws-wwc-purple-pinwheel-zoanthids",
    "ws-wwc-speckled-leather",
    "ws-wwc-scrambled-eggs-zoanthids",
    "ws-golden-eye-zoanthids",
    "ws-wwc-blue-angels-zoanthids",
    "ws-wwc-hairy-gorilla-nipples-zoanthids",
    "ws-c-sstell",
    "ws-l-tlady",
}

# Family patterns under D-2 observation. Word-bounded where the token is
# short enough to collide ('pos' inside e.g. 'Positron'); price-in-title is
# bare since '$' needs no boundary.
PROMO_PATTERNS = {
    "BOGO": re.compile(r"\bbogo\b", re.IGNORECASE),
    "POS": re.compile(r"\bpos\b", re.IGNORECASE),
    "Build A": re.compile(r"\bbuild a\b", re.IGNORECASE),
    "Special": re.compile(r"\bspecial\b", re.IGNORECASE),
    "Sale": re.compile(r"\bsale\b", re.IGNORECASE),
    "$N price-in-title": re.compile(r"\$\d"),
}


def _is_ws_prefix(title: str) -> bool:
    return title.lower().startswith("ws - ")


def _is_class(title: str) -> bool:
    return _is_ws_prefix(title) or title in PROMO_ENTRIES


def _patterns_hit(title: str) -> list[str]:
    return [name for name, rx in PROMO_PATTERNS.items() if rx.search(title)]


def _trim(products: list[dict]) -> list[dict]:
    out = []
    for p in products:
        out.append({
            "id": p.get("id"),
            "handle": p.get("handle"),
            "title": p.get("title") or "",
            "product_type": p.get("product_type") or "",
            # tags ride along for CTK-121's merch audit (shared instrument per
            # the ticket index — Dry Goods detection needs them; added after
            # the 2026-06-05 snapshot shipped without, so day-2 is PT-only).
            "tags": p.get("tags") or [],
            "published_at": p.get("published_at"),
            "available": any(v.get("available") for v in p.get("variants") or []),
        })
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--snapshot-out", required=True,
                        help="Path for today's trimmed feed snapshot (next day's --prior).")
    parser.add_argument("--prior",
                        help="Previous day's snapshot for the cross-day promo-title diff.")
    parser.add_argument("--bridge-snapshot", default=DEFAULT_BRIDGE_SNAPSHOT,
                        help="D-3 bridge snapshot (the 63 bridged rows).")
    args = parser.parse_args()

    bridge = json.load(open(args.bridge_snapshot, encoding="utf-8"))
    bridge_by_handle = {
        r["product_url"].rstrip("/").rsplit("/", 1)[-1]: r for r in bridge["rows"]
    }
    day1_handles = set(bridge_by_handle) | DAY1_POST_SWEEP_HANDLES
    print(f"day-1 class set: {len(bridge_by_handle)} bridged + "
          f"{len(DAY1_POST_SWEEP_HANDLES)} post-sweep = {len(day1_handles)} handles")

    cfg = _load_yaml("wwc")
    feed = _trim(_fetch_feed(cfg))
    today = datetime.date.today().isoformat()
    print(f"feed pull complete — {len(feed)} products ({today})")

    with open(args.snapshot_out, "w", encoding="utf-8") as f:
        json.dump({"ticket": "CTK-119", "pulled": today, "products": feed},
                  f, indent=2)
    print(f"snapshot written: {args.snapshot_out}")

    # ---- 1. Class census + born-since-bridge ----------------------------
    cls = [p for p in feed if _is_class(p["title"])]
    born = [p for p in cls if p["handle"] not in day1_handles]
    gone = day1_handles - {p["handle"] for p in cls}
    print(f"\n[1] class census: {len(cls)} class rows in feed (day 1: 76); "
          f"{len(born)} born since day 1, {len(gone)} day-1 handles left the feed")
    for p in born:
        print(f"  born-since: id={p['id']} pt={p['product_type']!r} "
              f"available={p['available']} {p['title']!r}")
    for h in sorted(gone):
        print(f"  left-feed: {h}")

    # ---- 2. Promo-shaped title scan (non-WS rows) ------------------------
    print("\n[2] promo-shaped title scan (family patterns, non-WS rows):")
    uncovered_eligible = 0
    for p in feed:
        if _is_ws_prefix(p["title"]):
            continue
        hits = _patterns_hit(p["title"])
        if not hits:
            continue
        covered = p["title"] in PROMO_ENTRIES
        if covered:
            print(f"  covered  [{', '.join(hits)}] {p['title']!r}")
            continue
        # Intake-eligibility under the CURRENT filter: would this row enter?
        # Real tags, not [] — wwc.yaml carries a tag_denylist axis, so empty
        # tags would over-report INTAKE-ELIGIBLE (lead-backend fix 2026-06-05).
        eligible = _should_keep(
            {"title": p["title"], "product_type": p["product_type"],
             "tags": p["tags"], "handle": p["handle"]},
            cfg["category_filter"],
        )
        flag = "  <- INTAKE-ELIGIBLE (reactive-add candidate)" if eligible else ""
        if eligible:
            uncovered_eligible += 1
        print(f"  uncovered [{', '.join(hits)}] pt={p['product_type']!r} "
              f"available={p['available']} {p['title']!r}{flag}")
    print(f"  uncovered + intake-eligible total: {uncovered_eligible}")

    # ---- 3. Rotation evidence for the 7 exact entries --------------------
    print("\n[3] promo-tail rotation evidence (the 7 exact entries):")
    titles_today = {p["title"]: p for p in feed}
    for entry in PROMO_ENTRIES:
        p = titles_today.get(entry)
        if p is None:
            print(f"  GONE from feed: {entry!r}")
        else:
            print(f"  still published: {entry!r} (available={p['available']})")

    # ---- 4. PT<->title mapping of the 63 bridged rows --------------------
    print("\n[4] PT<->title mapping of the 63 bridged rows (feed-matched):")
    pt_map: dict[str, list[dict]] = {}
    missing = []
    for handle, row in bridge_by_handle.items():
        p = next((q for q in feed if q["handle"] == handle), None)
        if p is None:
            missing.append(handle)
        else:
            pt_map.setdefault(p["product_type"], []).append(p)
    for pt in sorted(pt_map):
        print(f"  {pt!r}: {len(pt_map[pt])} rows")
        for p in sorted(pt_map[pt], key=lambda q: q["title"]):
            print(f"    {p['title']!r}")
    if missing:
        print(f"  not in today's feed ({len(missing)}): {sorted(missing)}")

    # ---- 5. DB guard — no new class intake since the denylist ------------
    print("\n[5] DB guard (read-only):")
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) AS n, count(*) FILTER (WHERE in_stock) AS n_in "
                "FROM vendor_listings WHERE vendor_id = %s "
                "AND raw_title ILIKE 'WS - %%'",
                (WWC_VENDOR_ID,),
            )
            r = cur.fetchone()
            print(f"  prefix rows: {r['n']} total, {r['n_in']} in_stock=true "
                  f"(day-1 audit: 81 total, 56 in_stock; post-bridge expect 81/0)")
            for entry, known_id in PROMO_ENTRIES.items():
                cur.execute(
                    "SELECT id, in_stock FROM vendor_listings "
                    "WHERE vendor_id = %s AND raw_title ILIKE %s",
                    (WWC_VENDOR_ID, f"%{entry}%"),
                )
                rows = cur.fetchall()
                extra = [x for x in rows if x["id"] != known_id]
                in_stock = [x for x in rows if x["in_stock"]]
                status = "OK" if not extra and not in_stock else "ANOMALY"
                print(f"  {status} {entry!r}: {len(rows)} row(s), "
                      f"{len(extra)} unexpected id(s), {len(in_stock)} in_stock=true")

    # ---- Cross-day diff (day 3+) -----------------------------------------
    if args.prior:
        prior = json.load(open(args.prior, encoding="utf-8"))
        def promo_titles(products):
            return {p["title"] for p in products
                    if not _is_ws_prefix(p["title"]) and _patterns_hit(p["title"])}
        prev, curr = promo_titles(prior["products"]), promo_titles(feed)
        print(f"\n[diff] promo-shaped titles vs {prior['pulled']}: "
              f"+{len(curr - prev)} / -{len(prev - curr)}")
        for t in sorted(curr - prev):
            print(f"  added:   {t!r}")
        for t in sorted(prev - curr):
            print(f"  removed: {t!r}")
    else:
        print("\n[diff] no --prior snapshot (day 2 vs day 1 is evidence-based: "
              "day 1 had no trimmed snapshot; first true diff runs day 3)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
