"""CTK-119 D-1 — two-lens false-kill audit for the WWC `WS - ` prefix +
promo-tail title_denylist entries, per feedback_audit_pass_two_lens_split.md.

Lens 1 (live feed x _should_keep): full /products.json pull (polite-paced per
wwc.yaml request_delay_sec), every product evaluated under the PRE-CTK-119
filter vs the CTK-119 filter as loaded from wwc.yaml. A "kill" is a product
the old filter kept and the new filter drops. Audit criteria:
  - every kill is either title-initial `WS - ` or one of the 7 exact promo
    titles (anything else = FAIL — a live coral got caught);
  - kills are cross-checked against the 2026-06-04 HEAD-sweep row list;
    kills absent from the sweep are listed for eyeball (expected shape:
    class members born after the sweep, not corals).
The kill count among old-kept rows is the expected `listings_seen` delta for
verify-pass step 1 — record it in results.md.

Lens 2 (DB raw_title ILIKE): collision scan over ALL WWC rows in Neon —
  - prefix preview: rows ILIKE 'WS - %' (anchored; doubles as the D-3 bridge
    candidate preview);
  - per promo entry: rows ILIKE '%<entry>%' whose id is NOT the known sweep
    id for that entry = collision = FAIL. Entries carry `$`/`/` but no
    LIKE wildcards (%/_) — patterns are safe unescaped; re-check before
    reusing this shape with new entries;
  - substring counterfactual (informational): rows containing 'ws - ' NOT
    title-initial — what a substring entry would have false-killed.

Run via:
  python -m scrapers.tools.ctk119_d1_two_lens_audit <head-sweep-file>

Read-only — no writes either side. Exit 0 = audit PASS, 1 = FAIL or error.
Reads NEON_DATABASE_URL from .env via scrapers.common.db's load_dotenv().
"""

from __future__ import annotations

import copy
import json
import re
import sys

from scrapers.common import db, http
from scrapers.common.parse_shopify import _should_keep
from scrapers.common.run import _load_yaml


WWC_VENDOR_ID = 2

# The 7 CTK-119 promo-tail entries with their known sweep ids (head-sweep
# 2026-06-04). Used by lens 2 to discriminate expected hits from collisions.
PROMO_ENTRIES: dict[str, int] = {
    "Acro Frag POS": 15744,
    "Special Sale - Frag": 15770,
    "BOGO Beginner SPS Frag": 15771,
    "$10 GSP Frag": 15772,
    "Favia/Favites BOGO": 15781,
    "May $25 Build A Monti Pack": 15782,
    "Rainbow Hammer January Special": 15800,
}

# Sweep rows quote titles with repr() — apostrophe-bearing titles ("WWC's
# Wholesale Choice") print double-quoted, the rest single-quoted. Accept both
# (first run missed ids 15536/15748 on this; reconciled in the audit artifact).
SWEEP_ROW_RE = re.compile(r"^\s+id=(\d+) HTTP \d+ \$\S+ (['\"]).*\2 (https://\S+)$")


def _load_sweep(path: str) -> dict[str, int]:
    """Parse the SUMMARY rows of the HEAD-sweep artifact -> {url: id}."""
    urls: dict[str, int] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            m = SWEEP_ROW_RE.match(line.rstrip())
            if m:
                urls[m.group(3)] = int(m.group(1))
    return urls


def _fetch_feed(cfg: dict) -> list[dict]:
    """Full /products.json pull mirroring fetch_and_parse pagination, minus
    normalize/diff — audit wants raw product dicts."""
    base_url = cfg["base_url"].rstrip("/")
    page_size = int(cfg.get("page_size", 250))
    max_pages = int(cfg.get("max_pages", 30))
    delay = float(cfg.get("request_delay_sec", 2.0))
    products: list[dict] = []
    for page in range(1, max_pages + 1):
        url = f"{base_url}{cfg.get('products_path', '/products.json')}?limit={page_size}&page={page}"
        result = http.fetch(url, request_delay_sec=delay)
        if result.error_class is not None:
            raise RuntimeError(f"page {page}: {result.error_class}: {result.error_message}")
        batch = json.loads(result.body).get("products") or []
        if not batch:
            break
        products.extend(batch)
        if len(batch) < page_size:
            break
    return products


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python -m scrapers.tools.ctk119_d1_two_lens_audit <head-sweep-file>")
        return 1

    sweep_urls = _load_sweep(sys.argv[1])
    print(f"sweep artifact: {len(sweep_urls)} dead-route rows loaded")

    cfg = _load_yaml("wwc")
    new_filter = cfg["category_filter"]
    old_filter = copy.deepcopy(new_filter)
    old_filter.pop("title_denylist_prefix", None)
    old_filter["title_denylist"] = [
        e for e in old_filter["title_denylist"] if e not in PROMO_ENTRIES
    ]
    base_url = cfg["base_url"].rstrip("/")

    failed = False

    # ---- Lens 1: live feed x _should_keep -------------------------------
    feed = _fetch_feed(cfg)
    print(f"lens 1: feed pull complete — {len(feed)} products")

    kills = [
        p for p in feed
        if _should_keep(p, old_filter) and not _should_keep(p, new_filter)
    ]
    print(f"lens 1: kill count (old-kept, new-dropped): {len(kills)}"
          f"  <- expected listings_seen delta for verify-pass step 1")

    not_in_sweep = 0
    for p in kills:
        title = p.get("title") or ""
        url = f"{base_url}/products/{p.get('handle', '')}"
        is_class = title.startswith("WS - ") or title.lower().startswith("ws - ") \
            or title in PROMO_ENTRIES
        in_sweep = url in sweep_urls
        if not is_class:
            failed = True
            print(f"  FAIL non-class kill: {title!r} {url}")
        elif not in_sweep:
            not_in_sweep += 1
            print(f"  eyeball (class-shaped, not in sweep — born post-sweep?): {title!r} {url}")
    print(f"lens 1: {len(kills) - not_in_sweep}/{len(kills)} kills sweep-listed, "
          f"{not_in_sweep} class-shaped post-sweep, 0 non-class"
          if not failed else "lens 1: FAIL — non-class kill(s) above")

    # ---- Lens 2: DB raw_title ILIKE collision scan -----------------------
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, raw_title, in_stock FROM vendor_listings "
                "WHERE vendor_id = %s AND raw_title ILIKE 'WS - %%' ORDER BY id",
                (WWC_VENDOR_ID,),
            )
            prefix_rows = cur.fetchall()
            in_stock_n = sum(1 for r in prefix_rows if r["in_stock"])
            print(f"lens 2: prefix scan ILIKE 'WS - %' -> {len(prefix_rows)} rows "
                  f"({in_stock_n} in_stock=true; D-3 bridge candidate preview)")

            for entry, known_id in PROMO_ENTRIES.items():
                cur.execute(
                    "SELECT id, raw_title FROM vendor_listings "
                    "WHERE vendor_id = %s AND raw_title ILIKE %s ORDER BY id",
                    (WWC_VENDOR_ID, f"%{entry}%"),
                )
                rows = cur.fetchall()
                collisions = [r for r in rows if r["id"] != known_id]
                if collisions:
                    failed = True
                    for r in collisions:
                        print(f"  FAIL collision on {entry!r}: id={r['id']} {r['raw_title']!r}")
                else:
                    print(f"lens 2: {entry!r} -> {len(rows)} row(s), expected id only")

            # Informational: the substring counterfactual.
            cur.execute(
                "SELECT id, raw_title, in_stock FROM vendor_listings "
                "WHERE vendor_id = %s AND raw_title ILIKE '%%ws - %%' "
                "AND raw_title NOT ILIKE 'WS - %%' ORDER BY id",
                (WWC_VENDOR_ID,),
            )
            counterfactual = cur.fetchall()
            print(f"lens 2: substring counterfactual (contains 'ws - ', not title-"
                  f"initial): {len(counterfactual)} row(s) a substring entry would false-kill")
            for r in counterfactual:
                print(f"  counterfactual: id={r['id']} in_stock={r['in_stock']} {r['raw_title']!r}")

    print(f"\nAUDIT {'FAIL' if failed else 'PASS'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
