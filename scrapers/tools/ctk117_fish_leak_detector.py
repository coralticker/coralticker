"""CTK-117 Arm 1 — committed fish-leak forward-detection probe.

Replaces the ad-hoc D-5 verify query (CTK-104) with a reproducible, read-only
tool. Joins every in-stock vendor_listings row against a WIDENED fish-noun
detector and emits operator flags. The detector is a FLAG, never a stored
classification — it deliberately diverges from (and does NOT touch)
normalize._CATEGORY_PATTERNS / infer_category, which feed the user-facing Type
label fleet-wide and must stay narrow (Butterfly / Tang / Foxface collide with
real coral trade names; widening production category would mis-tag real corals).
Because it's a flag for operator eyeballs, it tunes AGGRESSIVE — a false flag
is cheap, a missed fish leak on a coral-only feed is the trust-floor failure
CTK-104 closed.

Detector vs. the production fish pattern (normalize.py:40):
  - widened with TSA genus noun-phrases that escaped category inference
    (anthias / puffer / butterfly / foxface / basslet) on top of the existing
    fish / wrasse / tang / goby / clownfish / blenny terms;
  - boundary-anchored as `\\b(?:...)\\b` — the production pattern
    `\\bfish|wrasse|tang|goby|clownfish|blenny\\b` carries `\\b` only on the
    first and last alternatives (alternation-boundary bug), so its middle terms
    substring-match; this probe groups the alternation under shared boundaries
    so `tang` does NOT fire on "Tangerine" (a real coral lineage) while still
    catching "Yellow Tang".

Applied in-process to raw_title (Python `re`), NOT in SQL: PostgreSQL POSIX
`~*` reads `\\b` as a backspace literal, not a word boundary
(feedback_pg_posix_vs_python_regex_word_boundary.md), so a SQL-side regex would
silently mis-anchor. SQL fetches the rows with a plain predicate; Python applies
the boundary regex. Two-lens-compatible per feedback_audit_pass_two_lens_split.md.

Output is split into two sections to fight alert fatigue:
  Section 1 — TSA fish-noun hits (HIGH SIGNAL). TSA is the only vendor whose
    allowlist admits fish (Livestock product_type covers coral + fish); the
    other vendors are coral-pure by allowlist construction. TSA hits are the
    eyeball-worthy set.
  Section 2 — fleet (non-TSA) coral-name collisions (eyeball-noise, expected).
    The aggressive detector flags real corals fleet-wide every run
    ("Butterfly Effect" zoa, "Tang"-named morphs); this section is the known
    collision tail, separated so it doesn't bury Section 1.

Run via:
  python -m scrapers.tools.ctk117_fish_leak_detector

Read-only — no writes. Always exits 0 on a clean run (informational flag
emitter, not a pass/fail gate — both sections carry expected collision noise);
exits 1 only on error. Reads NEON_DATABASE_URL from .env via
scrapers.common.db's load_dotenv().
"""

from __future__ import annotations

import re
import sys

from scrapers.common import db


TSA_SLUG = "tsa"

# Widened, boundary-anchored fish-noun detector. Grouped alternation under a
# single `\b(?:...)\b` — every term carries word boundaries (fixes the
# normalize.py:40 alternation-boundary bug where only `fish`/`blenny` did).
# Grow this list as new TSA fish shapes surface; it never feeds production
# category, so aggressive additions are safe.
_FISH_TERMS = (
    "fish", "wrasse", "tang", "goby", "clownfish", "blenny",   # existing prod terms
    "anthias", "puffer", "butterfly", "foxface", "basslet",    # CTK-117 TSA genus widening
    # CTK-117 /code-review fold (Finding 2): single-word -fish compounds. The
    # grouped \b(?:...)\b won't match a base term inside a compound (`butterfly`
    # does not fire on "Butterflyfish"; there is no word boundary before the
    # trailing "fish"), so each compound TSA tags as its own fish family needs
    # an explicit term. Grounded in TSA's tag_denylist (Angelfish / Hawkfish /
    # Tilefish / Filefish) plus the Butterflyfish form.
    "butterflyfish", "hawkfish", "angelfish", "tilefish", "filefish",
)
_FISH_RE = re.compile(r"\b(?:" + "|".join(_FISH_TERMS) + r")\b", re.IGNORECASE)


def detect_fish_terms(raw_title: str) -> list[str]:
    """Return the sorted unique fish-noun terms matched in raw_title (lowercased),
    or [] when none. The load-bearing detector surface — unit-pinned in
    scrapers/tests/test_ctk117_fish_detector.py (regression anchor: the
    id=38474-class "Clownfish & Anemone Aquarium Kit" title must flag)."""
    if not raw_title:
        return []
    return sorted({m.lower() for m in _FISH_RE.findall(raw_title)})


def main() -> int:
    tsa_hits: list[dict] = []
    fleet_hits: list[dict] = []
    try:
        with db.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT vl.id, vl.raw_title, vl.category, v.slug "
                    "FROM vendor_listings vl "
                    "JOIN vendors v ON v.id = vl.vendor_id "
                    "WHERE vl.in_stock = true "
                    "ORDER BY v.slug, vl.id"
                )
                rows = cur.fetchall()
    except Exception as e:  # noqa: BLE001 — probe surfaces the error loudly, exits 1
        print(f"ERROR: {type(e).__name__}: {e}")
        return 1

    scanned = len(rows)
    for r in rows:
        terms = detect_fish_terms(r["raw_title"] or "")
        if not terms:
            continue
        hit = {
            "id": r["id"],
            "slug": r["slug"],
            "terms": terms,
            "category": r["category"],
            "raw_title": r["raw_title"],
        }
        (tsa_hits if r["slug"] == TSA_SLUG else fleet_hits).append(hit)

    print(f"scanned {scanned} in-stock rows fleet-wide\n")

    print("=== Section 1: TSA fish-noun hits (HIGH SIGNAL — eyeball these) ===")
    if not tsa_hits:
        print("  (none)")
    for h in tsa_hits:
        print(f"  id={h['id']} {h['terms']} category={h['category']!r} {h['raw_title']!r}")
    print(f"  {len(tsa_hits)} TSA hit(s)\n")

    print("=== Section 2: fleet (non-TSA) coral-name collisions (eyeball-noise, expected) ===")
    if not fleet_hits:
        print("  (none)")
    for h in fleet_hits:
        print(f"  {h['slug']} id={h['id']} {h['terms']} {h['raw_title']!r}")
    print(f"  {len(fleet_hits)} fleet collision(s)")

    print(f"\nDETECTOR RUN OK — {len(tsa_hits)} TSA / {len(fleet_hits)} fleet "
          f"flag(s) across {scanned} in-stock rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
