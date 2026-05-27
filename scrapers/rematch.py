"""Cold-start rematch for a single newly-seeded named_coral — arch §3.8.

When a row lands in `named_corals`, historic vendor_listings rows with
`named_coral_id IS NULL` don't link to it automatically. This script
runs the §3.4 cascade against the new row only, UPDATEs hits, and sets
`matched_at = first_seen_at` (NOT `now()`) per decision #30 so the §4
notifier — which polls `WHERE matched_at > last_poll` — does not blast
retroactive wishlist hits on listings that have already been visible
for days.

CLI:

    python -m scrapers.rematch --named-coral-id=N

For batch backfills across the v1 seed (20 corals) use the thin wrapper:

    python -m scrapers.rematch_v1_batch

Scope (arch §3.8 + plan §B3a):
  - Scan window: `last_seen_at >= now() - interval '7 days'`. Dormant
    listings outside the window are skipped — bounds runtime to §3.8's
    "takes seconds" budget at ~10k×1 scale.
  - Backfill filter: `named_coral_id IS NULL`. Cold-start exists to fill
    NULLs, not overwrite real-time-scrape matches against other corals.
  - Cache shape: filtered to one named_coral + its aliases. The cascade
    in scrapers.common.matcher.match_listing iterates the (one-element)
    named_corals list + (filtered) alias lists; hits against other
    corals are structurally impossible because they're absent from the
    cache. No edits to scrapers/common/matcher.py, but the stage-6 fuzzy
    tie-breaker (matcher.py:293 — `runner_score = scored[1][0] if
    len(scored) > 1 else 0.0`) is structurally disabled here: with a
    one-element cache, `runner_score = 0.0`, so the margin guard
    `(best_score - runner_score) >= PG_TRGM_TIE_BREAKER_MARGIN` trivially
    passes for any best_score >= PG_TRGM_BASE_THRESHOLD. Stage-6 false-
    positive envelope is accordingly wider in rematch than in real-time
    scrape (which has the full cache + the second-best legitimate runner
    for the guard to compare against). Hand off to CTK-002 eval set per
    /reef-lead Q-1 lean 2026-05-25.
  - Per-vendor originator_prefix is read from each vendor's YAML at
    `scrapers/vendors/<slug>.yaml` and looked up by vendor_id at match
    time, mirroring the real-time-scrape wiring in scrapers/common/run.py.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
import yaml

from scrapers.common import db
from scrapers.common.matcher import (
    Alias,
    MatchCache,
    NamedCoral,
    _trigrams,
    match_listing,
)

log = logging.getLogger(__name__)

LAST_SEEN_WINDOW_DAYS = 7


def _load_single_coral_cache(conn: psycopg.Connection, named_coral_id: int) -> MatchCache:
    """Load one named_corals row + its aliases into a MatchCache. The
    cascade in match_listing operates on this filtered cache without
    modification — only this coral can match.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, canonical_name, normalized_name, requires_vendor_prefix, category "
            "FROM named_corals WHERE id = %s AND active = TRUE",
            (named_coral_id,),
        )
        rows = cur.fetchall()
    if not rows:
        raise RuntimeError(
            f"named_coral_id={named_coral_id} not found or inactive in named_corals"
        )
    r = rows[0]
    nc = NamedCoral(
        id=int(r["id"]),
        canonical_name=r["canonical_name"],
        normalized_name=r["normalized_name"],
        requires_vendor_prefix=bool(r["requires_vendor_prefix"]),
        category=int(r["category"]),
        trigrams=_trigrams(r["normalized_name"]),
    )

    with conn.cursor() as cur:
        cur.execute(
            "SELECT alias_text, named_coral_id, cluster_label, match_behavior "
            "FROM aliases WHERE named_coral_id = %s",
            (named_coral_id,),
        )
        al_rows = cur.fetchall()
    auto_link: list[Alias] = []
    flag_review: list[Alias] = []
    for ar in al_rows:
        a = Alias(
            alias_text=ar["alias_text"],
            named_coral_id=(int(ar["named_coral_id"]) if ar["named_coral_id"] is not None else None),
            cluster_label=ar["cluster_label"],
            match_behavior=ar["match_behavior"],
        )
        if a.match_behavior == "auto-link":
            auto_link.append(a)
        elif a.match_behavior == "flag-review":
            flag_review.append(a)

    return MatchCache(
        named_corals=[nc],
        canonical_index={nc.normalized_name: nc},
        nc_by_id={nc.id: nc},
        auto_link_aliases=auto_link,
        flag_review_aliases=flag_review,
        named_corals_by_length_desc=[nc],
    )


def _load_vendor_prefix_map(conn: psycopg.Connection) -> dict[int, str | None]:
    """Map vendor_id -> originator_prefix from each vendor's YAML config.
    Vendors with no YAML (or no originator_prefix key) map to None — stage 3
    of the cascade is then skipped for that vendor's listings.

    Includes inactive vendors so the test-vendor pattern (active=false,
    no YAML) yields a None lookup that the cascade tolerates. Production
    listings only exist for active vendors; the inactive entries are
    inert.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT id, slug FROM vendors")
        rows = cur.fetchall()
    yaml_dir = Path(__file__).parent / "vendors"
    out: dict[int, str | None] = {}
    for r in rows:
        slug = r["slug"]
        yaml_path = yaml_dir / f"{slug}.yaml"
        prefix: str | None = None
        if yaml_path.exists():
            data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
            prefix = data.get("originator_prefix")
        out[int(r["id"])] = prefix
    return out


def rematch_one(conn: psycopg.Connection, named_coral_id: int) -> dict:
    """Re-run the §3.4 cascade against `named_coral_id` for every
    in-window, currently-unmatched listing. UPDATEs hits with
    matched_at = first_seen_at per decision #30.

    Returns a summary dict:
        {
          "named_coral_id": int,
          "canonical_name": str,
          "scanned": int,        # listings examined
          "updated": int,        # listings UPDATEd (cascade hit)
          "elapsed_sec": float,
        }
    """
    started = time.monotonic()
    cache = _load_single_coral_cache(conn, named_coral_id)
    vendor_prefixes = _load_vendor_prefix_map(conn)
    canonical_name = cache.named_corals[0].canonical_name

    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=LAST_SEEN_WINDOW_DAYS)
    ).isoformat()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT vl.id, vl.vendor_id, vl.normalized_title "
            "FROM vendor_listings vl "
            "JOIN vendors v ON v.id = vl.vendor_id "
            "WHERE vl.last_seen_at >= %s "
            "AND vl.named_coral_id IS NULL "
            "AND (vl.match_method IS NULL OR vl.match_method NOT LIKE 'cluster:%%') "
            "AND v.active = TRUE",
            (cutoff,),
        )
        listings = cur.fetchall()

    updated = 0
    for lst in listings:
        prefix = vendor_prefixes.get(int(lst["vendor_id"]))
        result = match_listing(
            cache,
            lst["normalized_title"] or "",
            originator_prefix=prefix,
        )
        if result.named_coral_id is None:
            continue
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE vendor_listings SET "
                "named_coral_id = %s, match_confidence = %s, "
                "match_method = %s, matched_at = first_seen_at "
                "WHERE id = %s AND named_coral_id IS NULL",
                (result.named_coral_id, result.match_confidence,
                 result.match_method, int(lst["id"])),
            )
        updated += 1

    elapsed = time.monotonic() - started
    summary = {
        "named_coral_id": named_coral_id,
        "canonical_name": canonical_name,
        "scanned": len(listings),
        "updated": updated,
        "elapsed_sec": round(elapsed, 3),
    }
    log.info(
        "rematch_one id=%d canonical=%r scanned=%d updated=%d elapsed=%.3fs",
        named_coral_id, canonical_name, len(listings), updated, elapsed,
    )
    return summary


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    parser = argparse.ArgumentParser(
        prog="scrapers.rematch",
        description="Cold-start rematch for a single newly-seeded named_coral (arch §3.8).",
    )
    parser.add_argument(
        "--named-coral-id", type=int, required=True,
        help="named_corals.id to re-evaluate against the §3.4 cascade",
    )
    args = parser.parse_args()

    with db.get_conn() as conn:
        summary = rematch_one(conn, named_coral_id=args.named_coral_id)
    print(
        f"named_coral_id={summary['named_coral_id']} "
        f"canonical={summary['canonical_name']!r} "
        f"scanned={summary['scanned']} updated={summary['updated']} "
        f"elapsed={summary['elapsed_sec']}s"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
