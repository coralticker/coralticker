"""Apply migration 0031 — CTK-126 origin_vendor / canonical_name attribution fix.

Renames two named_corals rows from reseller-prefixed to originator-correct
forms (id=1 Battlecorals PC Rainbow -> PC Rainbow Acropora / Pro Corals;
id=14 TSA Garf Bonsai Acropora -> GARF Bonsai Acropora / GARF) and preserves
the old canonical forms as aliases. slug is untouched (architecture #47).

Uses scrapers.common.db.get_conn per #65. Migration carries its own
BEGIN/COMMIT.

Smoke per directive (baseline parity per the 0030 precedent, anchored to ONE
explicit cutoff timestamp per the open-items apply-script pattern):
  (1) baseline BEFORE apply — set of (listing_id, named_coral_id) for the
      affected corals, anchored at first_seen_at <= cutoff so a scrape landing
      a new id=1/id=14 match mid-apply does not read as drift.
  (2) post-apply named_corals shape — canonical/normalized/origin updated,
      slug UNCHANGED (#47 immutability guard).
  (3) post-apply aliases — old canonical forms present as auto-link rows.
  (4) vendor_listings parity — same cutoff-anchored set as the baseline; the
      migration does not touch vendor_listings, so this MUST be identical.
      Existing matches keep landing. Mismatch prints both sets.
  (5) matcher resolution — load_match_cache + match_listing on representative
      titles (new canonical, new alias=old canonical, prefix, existing alias)
      all resolve to the correct named_coral_id. Proves the rename did not drop
      any match path.
"""

from __future__ import annotations

import sys
from pathlib import Path

from scrapers.common.db import get_conn
from scrapers.common.matcher import load_match_cache, match_listing
from scrapers.common.normalize import normalize_title

MIGRATION_PATH = (
    Path(__file__).resolve().parent.parent
    / "supabase"
    / "migrations"
    / "0031_fix_origin_vendor_originator_attribution.sql"
)

AFFECTED_IDS = (1, 14)

# Expected post-apply named_corals shape — (canonical, normalized, origin, slug).
# slug is the immutability guard: it MUST be unchanged (#47).
EXPECTED = {
    1: ("PC Rainbow Acropora", "pc rainbow acropora", "Pro Corals", "battlecorals-pc-rainbow"),
    14: ("GARF Bonsai Acropora", "garf bonsai acropora", "GARF", "tsa-garf-bonsai-acropora"),
}

# Representative titles -> expected named_coral_id. Covers new canonical (exact
# + prefix), the new alias (old reseller-prefixed canonical), and a pre-existing
# alias kept through the migration.
RESOLUTION_CASES = [
    ("PC Rainbow Acropora", 1),                 # new canonical (stage-1 exact)
    ("PC Rainbow Acropora ultra colony", 1),    # new canonical (stage-2 prefix)
    ("Battlecorals PC Rainbow", 1),             # new alias = old canonical
    ("Pro Corals Rainbow Acro", 1),             # pre-existing alias, still works
    ("GARF Bonsai Acropora", 14),               # new canonical
    ("TSA Garf Bonsai Acropora", 14),           # new alias = old canonical
    ("OG Garf Bonsai", 14),                     # pre-existing alias, still works
]


def main() -> int:
    sql = MIGRATION_PATH.read_text(encoding="utf-8")

    with get_conn() as conn:
        # One explicit cutoff for both baseline + parity reads.
        with conn.cursor() as cur:
            cur.execute("SELECT now() AS cutoff")
            cutoff = cur.fetchone()["cutoff"]
        print(f"cutoff anchor: {cutoff.isoformat()}")

        print("=" * 70)
        print("baseline — vendor_listings matched to affected corals (cutoff-anchored)")
        print("=" * 70)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, named_coral_id
                FROM vendor_listings
                WHERE named_coral_id = ANY(%s)
                  AND first_seen_at <= %s
                ORDER BY id
                """,
                (list(AFFECTED_IDS), cutoff),
            )
            baseline = {(r["id"], r["named_coral_id"]) for r in cur.fetchall()}
        print(f"  {len(baseline)} listings (expect 11 on id=1 + 8 on id=14 = 19 at audit time)")

        with conn.cursor() as cur:
            print(f"executing: {MIGRATION_PATH.name} ({len(sql)} bytes)...")
            try:
                cur.execute(sql)
            except Exception as exc:
                print(f"  FAILED: {type(exc).__name__}: {exc}")
                return 1
            print("  ok")

        print()
        print("=" * 70)
        print("post-apply — named_corals shape + slug immutability (#47)")
        print("=" * 70)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, canonical_name, normalized_name, origin_vendor, slug "
                "FROM named_corals WHERE id = ANY(%s) ORDER BY id",
                (list(AFFECTED_IDS),),
            )
            rows = {r["id"]: r for r in cur.fetchall()}
        for cid, (cn, nn, ov, slug) in EXPECTED.items():
            r = rows.get(cid)
            got = (r["canonical_name"], r["normalized_name"], r["origin_vendor"], r["slug"])
            if got == (cn, nn, ov, slug):
                print(f"  id={cid}: PASS  {cn} / {nn} / {ov} / slug={slug} (unchanged)")
            else:
                print(f"  id={cid}: FAIL  expected {(cn, nn, ov, slug)}, got {got}")
                return 1

        print()
        print("=" * 70)
        print("post-apply — old canonical preserved as aliases")
        print("=" * 70)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT named_coral_id, alias_text FROM aliases "
                "WHERE named_coral_id = ANY(%s) ORDER BY named_coral_id, id",
                (list(AFFECTED_IDS),),
            )
            alias_set = {(r["named_coral_id"], r["alias_text"]) for r in cur.fetchall()}
        for expected_alias in [(1, "battlecorals pc rainbow"), (14, "tsa garf bonsai acropora")]:
            if expected_alias in alias_set:
                print(f"  PASS  alias present: {expected_alias}")
            else:
                print(f"  FAIL  alias missing: {expected_alias}")
                return 1

        print()
        print("=" * 70)
        print("parity — vendor_listings matches unchanged (cutoff-anchored)")
        print("=" * 70)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, named_coral_id
                FROM vendor_listings
                WHERE named_coral_id = ANY(%s)
                  AND first_seen_at <= %s
                ORDER BY id
                """,
                (list(AFFECTED_IDS), cutoff),
            )
            post = {(r["id"], r["named_coral_id"]) for r in cur.fetchall()}
        if post == baseline:
            print(f"  PASS  {len(post)} listings, identical match set")
        else:
            print(f"  MISMATCH  baseline {len(baseline)} vs post {len(post)}")
            print(f"    baseline-only: {sorted(baseline - post)}")
            print(f"    post-only:     {sorted(post - baseline)}")
            return 1

        print()
        print("=" * 70)
        print("matcher resolution — representative titles resolve correctly")
        print("=" * 70)
        cache = load_match_cache(conn)
        ok = True
        for raw_title, expected_id in RESOLUTION_CASES:
            result = match_listing(cache, normalize_title(raw_title))
            status = "PASS" if result.named_coral_id == expected_id else "FAIL"
            if result.named_coral_id != expected_id:
                ok = False
            print(
                f"  {status}  '{raw_title}' -> id={result.named_coral_id} "
                f"({result.match_method}); expected id={expected_id}"
            )
        if not ok:
            return 1

    print()
    print("all smoke checks PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
