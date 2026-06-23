"""CTK-162 / CTK-184 — populate named_corals.lore for the active named corals
(decision #85 backfill, copy Jon-ratified verbatim). CTK-162 seeded the 7
most-hunted acros; CTK-184 extends to the remaining 13 (audit trail in
.claude/plans/tickets/CTK-162/coral-facts-reconciliation.md, "CTK-184" section).

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
    # CTK-184 — remaining 13, curated down from named_corals.notes (Jon-ratified).
    (
        "gorilla-nipple-zoa",
        "A teal zoa with orange polyps, named for its distinctively raised, "
        "knobby shape.",
    ),
    (
        "jf-burning-banana-stylocoeniella",
        "A Jason Fox signature in Stylocoeniella, an encrusting SPS — not the "
        "acros and montis that usually get the designer names.",
    ),
    (
        "jf-foxflame",
        "A pink-bodied acro tipped in yellow, one of the Jason Fox signature "
        "pieces from the early top-ten lists.",
    ),
    (
        "jf-jack-o-lantern-leptoseris",
        "A Leptoseris with an orange base and green centers — one of Jason "
        "Fox's most-copied pieces, so the name gets around.",
    ),
    (
        "jf-raja-rampage-chalice",
        "Jason Fox's signature chalice, and the best-known piece in his chalice "
        "lineup.",
    ),
    (
        "jf-slow-burn-monti",
        "A green, fluorescence-heavy Montipora, one of the early Jason Fox "
        "top-ten.",
    ),
    (
        "magician-zoanthid",
        "A zoa with a glittering blue center that sits right on the line "
        "between zoanthid and paly.",
    ),
    (
        "tsa-bill-murray-acropora",
        "A signature Acropora lineage from Top Shelf Aquatics.",
    ),
    (
        "tsa-fruity-pebbles-acropora",
        "Top Shelf Aquatics' best-known acro and the parent of the Fruity "
        "Splice morph — the name's spread well past the original piece.",
    ),
    (
        "utter-chaos-zoanthid",
        "A purple-based zoa swirled with yellow-green and skirted in orange — "
        "chaotic enough to earn the name.",
    ),
    (
        "wwc-dragon-soul-torch",
        "A torch that turns up under several names — Hellfire, Indo Gold, 24k — "
        "reportedly the same coral; Dragon Soul is World Wide Corals' label for "
        "it.",
    ),
    (
        "wwc-og-bounce-mushroom",
        "World Wide Corals' original bounce mushroom, the piece the whole "
        "bounce craze traces back to.",
    ),
    (
        "wwc-sunkist-bounce-mushroom",
        "Orange bubbles over a dark blue-green base, a bounce World Wide Corals "
        "has propagated for more than a decade.",
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
