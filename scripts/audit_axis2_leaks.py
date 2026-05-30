"""CTK-095 Axis 2 — live-pull /products.json × DB cross-ref audit.

For each of 5 vendors:
  1. Live-pull /products.json (all pages) — get (handle, title, product_type, tags).
  2. Query DB for in_stock rows (id, product_url, raw_title).
  3. Intersect by URL (= base/products/handle).
  4. Apply per-vendor non-coral regex to (title, tags) from live + (raw_title) from DB.
  5. For each leak: classify STALE (live tags overlap existing denylist) vs.
     ROTATION (new tag-shape). STALE = legacy row pre-denylist that survived
     CTK-041 intersection-DELETE OR intake filter has gap. ROTATION = needs
     new denylist additions.

Output: per-vendor (leak_count, denylist_addition_candidates, urls_to_delete).
Used to inform YAML edits + migration 0023 hardcoded URL lists.
"""

from __future__ import annotations

import json
import re
import time
from collections import Counter
from urllib.request import Request, urlopen

from scrapers.common.db import get_conn

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
DELAY = 2.0

# (id, slug, base, max_pages, current_denylist_lower, hit_re, fp_re)
VENDORS = [
    (1, "pacific_east", "https://pacificeastaquaculture.com", 8,
     {"algae muncher", "astrea snails", "cerith", "conch", "crab", "inverts",
      "nassarius", "nerite", "snail", "trochus"},
     re.compile(r"(conch|nassarius|snail|invert|crab|trochus|cerith|nerite|shrimp|urchin|starfish|hermit|sea\s*hare|food|phytoplankton|copepod|live\s*food|pod\b)", re.I),
     re.compile(r"(toadstool|leptastrea|cyphastrea|goniastrea|plesiastrea|paragoniastrea|astreopora|frozen|tangerine)", re.I)),
    (3, "tsa", "https://topshelfaquatics.com", 14,
     {"algae eater", "angelfish", "beginner fish", "clownfish", "invert",
      "live rock", "macroalgae", "mangrove", "nano fish", "refugiums",
      "tang", "wysiwyg fish"},
     re.compile(r"(hawkfish|dartfish|gudgeon|\bclam\b|hippopus|tridacna|squamosa|maxima\s+clam|derasa|crocea|wrasse|clown|goby|damsel|chromis|cardinal|firefish|blenny|angelfish)", re.I),
     re.compile(r"(toadstool|leptastrea|cyphastrea|goniastrea|tangerine|wysiwyg\s+coral)", re.I)),
    (4, "jf", "https://jasonfoxsignaturecorals.com", 3,
     set(),
     re.compile(r"(\btang\b|wrasse|clown|hawkfish|dartfish|goby|damsel|chromis|cardinal|firefish|blenny|fish|shrimp|hermit|crab|snail|clam)", re.I),
     re.compile(r"(toadstool|leptastrea|cyphastrea|goniastrea|tangerine)", re.I)),
    (5, "battlecorals", "https://battlecorals.com", 3,
     set(),
     re.compile(r"(gift\s*card|merch|sticker|tee\s*shirt|t-?shirt|hoodie|apparel)", re.I),
     re.compile(r"^$", re.I)),
    (6, "unique_corals", "https://uniquecorals.com", 4,
     {"dalua", "goods", "illumagic", "maintenance", "openbox", "other dg",
      "panta rhei", "pns", "shipping", "used"},
     re.compile(r"(seeclear|magnet|reactor|injector|feed\s+assembly|supplement|skimmer|\bpump\b|controller|wavemaker|fixture|radion|\bwand\b|tubing|sock|\bato\b|gauge|valve|carbon|gfo|salt\b|test\s+kit|tweezer|forceps|\bnet\b|alkalinity|nitrate|\bled\b|lighting|holder|mounting|aquarium\s+x4)", re.I),
     re.compile(r"(toadstool|leptastrea|cyphastrea|goniastrea|tangerine)", re.I)),
]


def fetch_page(base: str, page: int) -> list[dict]:
    url = f"{base}/products.json?limit=250&page={page}"
    req = Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urlopen(req, timeout=30) as resp:
        body = resp.read()
    return json.loads(body).get("products", [])


def walk_vendor(base: str, max_pages: int) -> list[dict]:
    items = []
    for page in range(1, max_pages + 1):
        products = fetch_page(base, page)
        items.extend(products)
        if len(products) < 250:
            break
        time.sleep(DELAY)
    return items


def main() -> None:
    with get_conn() as conn:
        for vid, slug, base, max_pages, current_denylist, hit_re, fp_re in VENDORS:
            print(f"\n=== vendor_id={vid} slug={slug} ===", flush=True)

            # Live walk
            live = walk_vendor(base, max_pages)
            # Map handle → (title, product_type, tags)
            live_by_handle = {p["handle"]: p for p in live}

            # DB pull
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, product_url, raw_title FROM vendor_listings "
                    "WHERE vendor_id = %s AND in_stock = true",
                    (vid,),
                )
                db_rows = cur.fetchall()

            # URL canonicalization — DB rows have absolute URLs like https://.../products/<handle>
            # Extract handle from product_url
            db_by_handle: dict[str, dict] = {}
            for r in db_rows:
                url = r["product_url"]
                if "/products/" in url:
                    h = url.split("/products/", 1)[1].split("?")[0].split("/")[0]
                    db_by_handle[h] = {"id": r["id"], "url": url, "raw_title": r["raw_title"]}

            print(f"  live: {len(live)}  db_in_stock: {len(db_rows)}  joined_by_handle: {len(db_by_handle)}", flush=True)

            # Find leaks: DB in_stock rows whose live counterpart matches non-coral signature
            leaks_stale: list[dict] = []
            leaks_rotation: list[dict] = []
            rotation_tag_counter: Counter = Counter()

            for handle, dbrow in db_by_handle.items():
                lr = live_by_handle.get(handle)
                if not lr:
                    # In DB but no longer on live catalog — skip (delisted; not our scope)
                    continue
                title = lr.get("title") or ""
                tags = lr.get("tags") or []
                pt = lr.get("product_type") or ""

                # False-positive guard
                if fp_re.search(title) or any(fp_re.search(t) for t in tags):
                    continue

                # Hit detection: title OR any tag matches non-coral regex
                title_hit = hit_re.search(title)
                tag_hits = [t for t in tags if hit_re.search(t)]
                if not (title_hit or tag_hits):
                    continue

                row = {
                    "handle": handle,
                    "db_id": dbrow["id"],
                    "url": dbrow["url"],
                    "title": title,
                    "pt": pt,
                    "tags": tags,
                    "match": title_hit.group(0) if title_hit else tag_hits[0],
                }

                # STALE: any tag overlaps existing denylist (case-insensitive)
                if any(t.lower() in current_denylist for t in tags):
                    leaks_stale.append(row)
                else:
                    leaks_rotation.append(row)
                    # Capture all tags from rotation hits to suggest denylist additions
                    for t in tags:
                        rotation_tag_counter[t] += 1

            print(f"  LEAKS: stale={len(leaks_stale)} rotation={len(leaks_rotation)}", flush=True)

            print("  STALE sample (10):", flush=True)
            for r in leaks_stale[:10]:
                print(f"    id={r['db_id']:>5}  handle={r['handle']!r}  PT={r['pt']!r}  title={r['title'][:50]!r}  tags={r['tags']}", flush=True)

            print("  ROTATION (all):", flush=True)
            for r in leaks_rotation[:30]:
                print(f"    id={r['db_id']:>5}  handle={r['handle']!r}  PT={r['pt']!r}  title={r['title'][:50]!r}  tags={r['tags']}", flush=True)
            if len(leaks_rotation) > 30:
                print(f"    ... ({len(leaks_rotation)-30} more)", flush=True)

            if rotation_tag_counter:
                print("  rotation-tag frequency (top 20):", flush=True)
                for tag, count in rotation_tag_counter.most_common(20):
                    print(f"    {count:3d}  {tag!r}", flush=True)

            # Total URLs to delete (stale + rotation)
            all_leak_urls = [r["url"] for r in leaks_stale + leaks_rotation]
            print(f"  TOTAL URLs to delete: {len(all_leak_urls)}", flush=True)

            time.sleep(DELAY)


if __name__ == "__main__":
    main()
