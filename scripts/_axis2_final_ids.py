"""Lock the final per-vendor delete-ID list for migration 0023.

Python-side regex (proper `\b` word boundaries; PG POSIX `~*` interprets `\b`
as backspace not word-boundary). Emits per-vendor (id, raw_title) for embedding
in migration 0023 SQL.
"""

from __future__ import annotations

import re

from scrapers.common.db import get_conn

# Per-vendor: (id, slug, hit_pattern, exclusion_pattern, notes)
VENDORS = [
    (1, "pacific_east",
     re.compile(r"(strawberry\s+conch|jumbo\s+nassarius|phyto|pod\s+pub|live\s+marine\s+phytoplankton)", re.I),
     re.compile(r"(maxima|emerald.*(blastomussa|psammacora|chalice|coral|iles|city))", re.I),
     "PE: 3 expected — Strawberry Conch + Jumbo Nassarius + PhytoPunch."),
    (3, "tsa",
     re.compile(r"(sticker|t-shirt|hoodie|sweatshirt|wrasse|hawkfish|dartfish|gudgeon|tilefish|filefish|hippopus|squamosa|derasa|maxima\s+clam|ultra\s+(black|gold|blue)?\s*maxima|ultra\s+derasa|ultra\s+hippopus|ultra\s+gold\s+squamosa)", re.I),
     re.compile(r"(tang\s+yuma\s+mushroom|crazy\s+clown\s+zoanthid|clown\s+town\s+yuma|\bcoral\b)", re.I),
     "TSA: ~27 expected — stickers/T-shirts/hoodies + clams + 4 fish; excludes 3 coral lineages."),
    (4, "jf",
     re.compile(r"(hybrid\s+tang|local\s+pick\s+up)", re.I),
     re.compile(r"NEVER_MATCH_THIS_STRING_xyzzy", re.I),
     "JF: 1 expected — Hybrid Tang. Structural-gap flag."),
    (5, "battlecorals",
     re.compile(r"(gift\s*card|tee\s*shirt|t-?shirt|hoodie|merch)", re.I),
     re.compile(r"NEVER_MATCH_THIS_STRING_xyzzy", re.I),
     "BC: 5 expected — Gift Cards + 4 Tee Shirts. Structural-gap flag."),
    (6, "unique_corals",
     re.compile(r"(seeclear|magnet|reactor|injector|feed\s+assembly|supplement|skimmer|\bpump\b|controller|wavemaker|fixture|radion|\bwand\b|tubing|\bsock\b|\bato\b|gauge|\bvalve\b|activated\s+carbon|\bgfo\b|\btest\s+kit|tweezer|forceps|\bnet\b|alkalinity|nitrate\s+kit|\bled\b|\blighting\b|\bholder\b|mounting|aquarium\s+x4|rail|slider|core7|corechem|\btriton\b|bundle|illumagic|dalua|panta|x4|lab\s+icp|lab\s+n-doc|life\s+support|flow\s+bundle|pixel\s+led|return\s+pump|protein\s+skimmer|hydrowizard|wave\s*maker|magnetic|prism|stn-x|cya-no|rotor|peristaltic|terminator|impeller|bus\s+cable|power\s+supply|power\s+cord|flange\s+seal|honey\s+comb|adapter\s+ring|quick\s+mount|silencer|protective\s+net|flow\s+straightener|controller\s+upgrade|replacement|mount\s+bracket|hydrotube|cd42|pads\s+kit|adjustable\s+mount|panta\s+clean|panta\s+lith|dastaco|pax\s+bellum|arid|cyanobacteria|alkalinity)", re.I),
     re.compile(r"(\bcoral\b|\btorch\b|holy\s+grail|acropora|montipora|chalice|zoanthid|psammacora|wysiwyg|euphyllia|blastomussa|stick\s+together|cyanoacrylate)", re.I),
     "UC: ~105 expected — equipment/supplements/lighting; coral-name guard excludes lineage names."),
]


def main() -> None:
    print("# Per-vendor delete-ID enumeration (CTK-095 Axis 2 migration 0023)\n")
    all_per_vendor = {}
    total = 0
    with get_conn() as conn:
        for vid, slug, hit_re, excl_re, notes in VENDORS:
            print(f"## vendor_id={vid} slug={slug}")
            print(f"  notes: {notes}")
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, raw_title, product_url FROM vendor_listings "
                    "WHERE vendor_id = %s AND in_stock = true ORDER BY id",
                    (vid,),
                )
                rows = cur.fetchall()
            kept = [r for r in rows if hit_re.search(r["raw_title"] or "") and not excl_re.search(r["raw_title"] or "")]
            print(f"  count: {len(kept)}")
            all_per_vendor[vid] = kept
            total += len(kept)
            for r in kept:
                print(f"    id={r['id']:>6}  {r['raw_title'][:75]!r}")
            print()
    print(f"# TOTAL across 5 vendors: {total} rows")
    print()
    print("# IDs by vendor (paste-ready for migration SQL):")
    for vid, kept in all_per_vendor.items():
        ids = [r["id"] for r in kept]
        print(f"-- vendor_id={vid}: {len(ids)} ids")
        # Chunk into lines of 10 for readability in SQL
        for i in range(0, len(ids), 10):
            print(f"   {', '.join(str(x) for x in ids[i:i+10])},")


if __name__ == "__main__":
    main()
