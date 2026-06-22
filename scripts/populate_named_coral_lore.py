"""CTK-162 — populate named_corals.lore for the 7 most-hunted acros (decision #85
backfill, /brand-manager + /copy-writer copy Jon-ratified verbatim).

Data UPDATE keyed on slug against live Neon (NOT a migration — the lore column
shipped in migration 0051). Parameterized psycopg write (slug = %s) so em-dashes
(U+2014), curly artifacts, and the inner straight quotes round-trip exactly with
no hand-escaping. Per-slug rowcount guard: a slug that does not exist on live
Neon writes 0 rows and is reported as NOT FOUND rather than silently skipped.
Read-back SELECT confirms the stored value after the write.

Idempotent: re-running rewrites the same values. Run from repo root:
    .venv/bin/python -m scripts.populate_named_coral_lore
"""

from __future__ import annotations

from psycopg.rows import dict_row

from scrapers.common.db import get_conn

# (slug, lore) — copy locked verbatim per the directive. Quote styles chosen so
# the inner straight quotes survive without escaping where possible.
ROWS: list[tuple[str, str]] = [
    (
        "battlecorals-pc-rainbow",
        'A red stag with an orange inner and a blue rim — the Battlecorals '
        'signature most people mean when they say "rainbow."',
    ),
    (
        "jf-homewrecker",
        "Jason Fox's signature tenuis — copied so widely that the original's "
        "worth seeking out by name.",
    ),
    (
        "ora-red-planet-acropora",
        'A red tabling acro that two growers both sell as "Red Planet" — '
        "ORA's and Aqua SD's aren't the same coral, so check which one.",
    ),
    (
        "wwc-walt-disney-acropora",
        "The benchmark rainbow tenuis — rarely in stock, and the name gets "
        "borrowed so often that the WWC original is the one to look for.",
    ),
    (
        "tsa-strawberry-shortcake-acropora",
        'A microclados so widely grown that "Strawberry Shortcake" now covers '
        "several different corals — the grower matters more than the name.",
    ),
    (
        "tsa-garf-bonsai-acropora",
        "A GARF (Geothermal Aquaculture Research Foundation) valida grown by "
        "TSA — a storied old lineage, deep blue-purple with green tips.",
    ),
    (
        "tyree-pink-lemonade",
        "A classic Tyree limited edition and one of the old-guard named acros "
        "— lime-green branches under pink polyps.",
    ),
]


def main() -> None:
    written: list[str] = []
    missing: list[str] = []

    with get_conn() as conn:
        with conn.cursor() as cur:
            for slug, lore in ROWS:
                cur.execute(
                    "UPDATE named_corals SET lore = %s WHERE slug = %s",
                    (lore, slug),
                )
                if cur.rowcount == 1:
                    written.append(slug)
                else:
                    missing.append(slug)

        with conn.cursor(row_factory=dict_row) as cur:
            slugs = [slug for slug, _ in ROWS]
            cur.execute(
                "SELECT slug, lore FROM named_corals WHERE slug = ANY(%s) ORDER BY slug",
                (slugs,),
            )
            readback = cur.fetchall()

    print(f"WRITTEN ({len(written)}/{len(ROWS)}): {', '.join(written)}")
    if missing:
        print(f"!! NOT FOUND ({len(missing)}) — no lore written, needs slug reconciliation:")
        for slug in missing:
            print(f"   - {slug}")

    print("\nREAD-BACK (slug, lore):")
    for row in readback:
        print(f"\n  {row['slug']}")
        print(f"    {row['lore']}")


if __name__ == "__main__":
    main()
