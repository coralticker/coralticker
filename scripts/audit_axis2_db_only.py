"""CTK-095 Axis 2 — DB-only raw_title regex audit.

The previous audit required live /products.json join. That misses rows
delisted from live but still `in_stock=true` in DB because cohort-comparison-OOS
isn't shipped (CTK-094 DRAFT). User-facing /vendor pages render from DB
in_stock=true regardless of live catalog presence — so the user-facing leak
shape is DB-only.

This audit pulls every in_stock row per vendor + applies a per-vendor
non-coral regex to raw_title. Output: count + sample of leak rows per vendor.
"""

from __future__ import annotations

import re
from collections import Counter

from scrapers.common.db import get_conn

# (vendor_id, slug, hit_re_pattern, false_positive_re_pattern)
VENDORS = [
    (1, "pacific_east",
     r"(conch|nassarius|snail|invert|crab|trochus|cerith|nerite|shrimp|urchin|starfish|hermit|sea\s*hare|food|phytoplankton|copepod|live\s*food|\bpod\b|\bclam\b|sea\s*star|nudibranch|tile\s*fish|\btang\b|hawkfish|dartfish|wrasse|clownfish|goby|chromis|damsel|blenny|cardinal|firefish|gudgeon|hippopus|tridacna|squamosa|maxima|derasa|crocea|angelfish|filefish|emerald)",
     r"(toadstool|leptastrea|cyphastrea|goniastrea|plesiastrea|paragoniastrea|astreopora|frozen|tangerine|tangelo|tangier)"),
    (3, "tsa",
     r"(hawkfish|dartfish|gudgeon|\bclam\b|hippopus|tridacna|squamosa|maxima\s+clam|derasa|crocea|wrasse|\bclown\b|goby|damsel|chromis|cardinal|firefish|blenny|angelfish|filefish|\btang\b|shrimp|urchin|starfish|hermit|snail|nassarius|\bconch\b|\bcrab\b|invert|tee\s*shirt|t-?shirt|hoodie|sticker|gift\s*card|apparel)",
     r"(toadstool|leptastrea|cyphastrea|goniastrea|tangerine|tangelo|wysiwyg\s+coral|coraline)"),
    (4, "jf",
     r"(\btang\b|wrasse|\bclown\b|hawkfish|dartfish|goby|damsel|chromis|cardinal|firefish|blenny|fish|shrimp|hermit|crab|snail|clam|gudgeon|hippopus|tridacna|squamosa|maxima|derasa|crocea|angelfish|filefish)",
     r"(toadstool|leptastrea|cyphastrea|goniastrea|tangerine|frozen|tangelo)"),
    (5, "battlecorals",
     r"(gift\s*card|merch|sticker|tee\s*shirt|t-?shirt|hoodie|apparel)",
     r"^$"),
    (6, "unique_corals",
     r"(seeclear|magnet|reactor|injector|feed\s+assembly|supplement|skimmer|\bpump\b|controller|wavemaker|fixture|radion|\bwand\b|tubing|\bsock\b|\bato\b|gauge|\bvalve\b|activated\s+carbon|\bgfo\b|\bsalt\b|test\s+kit|tweezer|forceps|\bnet\b|alkalinity|nitrate\s+kit|\bled\b|\blighting\b|\bholder\b|mounting|aquarium\s+x4|rail|slider|core7|corechem|\btriton\b|bundle|illumagic|dalua|panta|x4)",
     r"(toadstool|leptastrea|cyphastrea|goniastrea|tangerine|coral\s+rx|coraline)"),
]


def main() -> None:
    with get_conn() as conn:
        for vid, slug, hit_pattern, fp_pattern in VENDORS:
            print(f"\n=== vendor_id={vid} slug={slug} ===", flush=True)
            hit_re = re.compile(hit_pattern, re.I)
            fp_re = re.compile(fp_pattern, re.I) if fp_pattern else None

            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, product_url, raw_title FROM vendor_listings "
                    "WHERE vendor_id = %s AND in_stock = true "
                    "ORDER BY id",
                    (vid,),
                )
                rows = cur.fetchall()

            print(f"  total in_stock: {len(rows)}", flush=True)

            leaks: list[dict] = []
            for r in rows:
                title = r["raw_title"] or ""
                if hit_re.search(title):
                    if fp_re and fp_re.search(title):
                        continue
                    leaks.append({"id": r["id"], "url": r["product_url"], "title": title})

            print(f"  LEAKS: {len(leaks)}", flush=True)
            for L in leaks[:60]:
                print(f"    id={L['id']:>6}  title={L['title'][:70]!r}", flush=True)
            if len(leaks) > 60:
                print(f"    ... ({len(leaks)-60} more)", flush=True)


if __name__ == "__main__":
    main()
