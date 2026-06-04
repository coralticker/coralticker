"""scrapers/common/health_digest.py — CTK-097 daily operator health digest.

Bootstraps the arch §6.5 daily health-check digest (designed at CTK-001,
never previously built — CTK-097 plan D-6) with the per-category cohort
block as its only v1 section. One Slack message per day to the operator
channel at 17:11 UTC (plan D-8 — §6.5's nominal "noon ET" intent on an
off-minute slot per the top-of-hour degradation discipline).

Section-builder structure: SECTION_BUILDERS is an ordered list of functions
returning section text (or "" to omit). The §6.5 blocks that remain unbuilt
(per-vendor scoreboard, DB capacity, GH Actions minutes, etc.) land here
additively as new builders under their own CTK without restructuring.

The cohort section is the guaranteed-delivery counterpart to the hourly
real-time ping (scrapers/common/cohort_signal.py): everything below the
ping thresholds surfaces here, and anything that DID ping is cross-
referenced with a [PINGED] marker + fire slot rather than omitted, so the
digest reads truthfully as a standalone "is the world okay" surface
(plan §Implementation plan #8 no-double-alert mechanism).

Per-vendor lines, per plan §7 (counts are PRE-overlap-dedup raw card
counts per migration 0024 — rendered as "cards", never "listings"):

  per-category cohort (aquasd, run 731):
    15 healthy | 1 sparse (/cynarinas/=1) | 5 curator-empty | 0 WARN
    [PINGED] /montipora/: 0x3 scrapes — real-time ping fired 2026-06-04 10:11 UTC
  cohort-OOS last 24h: aquasd 12, poto 4, tidal-gardens 0

A vendor with vendors.active=false renders an [INACTIVE] line instead of
its cohort lines (review-fold 2026-06-04): the hourly poller deliberately
quiet-skips inactive vendors to avoid pause-window noise, so the daily
digest is where an operator pause stays visible.

Runnable as:
  python -m scrapers.common.health_digest
"""

from __future__ import annotations

import logging
import statistics
import sys
from datetime import datetime, timedelta, timezone

from scrapers.common.cohort_signal import (
    SLOT_MINUTE,
    fetch_recent_success_runs,
    get_thresholds,
    is_curator_empty,
    path_histories,
    post_slack,
    zero_streak,
)

logger = logging.getLogger(__name__)

# Trend marker threshold: a nonzero-current path renders a trend line only
# when it sits more than this fraction off its 7-day median (plan §7 —
# full 21-row tables daily are noise, not signal).
TREND_DEVIATION = 0.5


# ---------------------------------------------------------------------------
# Pure section core — no DB, no network. Tests drive these directly.
# ---------------------------------------------------------------------------


def slot_for(started_at: datetime) -> datetime:
    """The nominal poller slot whose window (slot-1h, slot] contains
    started_at — i.e. the slot in which the real-time ping for a run fired.
    """
    slot = started_at.replace(minute=SLOT_MINUTE, second=0, microsecond=0)
    if slot < started_at:
        slot += timedelta(hours=1)
    return slot


def classify_for_digest(runs: list[dict], thresholds: dict, expected_min: int) -> dict:
    """Bucket every path in the window for digest rendering.

    Returns {"healthy": [...], "sparse": [(path, count)], "curator_empty":
    [...], "warn": [(path, streak)], "pinged": [(path, streak, fire_slot)],
    "trend": [(path, current, median)]} — pinged includes saturate-state
    paths (streak >= three_days_running + 5), which render the broken-
    detection wording.
    """
    days = thresholds["three_days_running"]
    buckets: dict = {"healthy": [], "sparse": [], "curator_empty": [], "warn": [], "pinged": [], "trend": []}
    if not runs:
        return buckets

    histories = path_histories(runs)
    newest_start = runs[0]["started_at"]
    week_ago = newest_start - timedelta(days=7)

    for path, history in histories.items():
        if is_curator_empty(history):
            buckets["curator_empty"].append(path)
            continue
        streak = zero_streak(history)
        if streak >= days:
            # The run that completed the streak (fired the ping) sits at
            # index streak - days in the newest-first window.
            fire_slot = slot_for(runs[streak - days]["started_at"])
            buckets["pinged"].append((path, streak, fire_slot))
            continue
        if streak >= 1:
            buckets["warn"].append((path, streak))
            continue
        current = history[0]
        if current < expected_min:
            buckets["sparse"].append((path, current))
        else:
            buckets["healthy"].append(path)
        # Trend marker — nonzero current vs 7d median (zeros are handled by
        # the streak buckets above; trend catches partial sags a zero-based
        # predicate never sees).
        week_counts = [
            count
            for count, run in zip(history, runs)
            if run["started_at"] >= week_ago
        ]
        median = statistics.median(week_counts) if week_counts else 0
        if median > 0 and abs(current - median) / median > TREND_DEVIATION:
            buckets["trend"].append((path, current, median))

    return buckets


def render_vendor_lines(slug: str, runs: list[dict], buckets: dict, thresholds: dict) -> list[str]:
    if not runs:
        return [f"per-category cohort ({slug}): no successful runs in window"]
    days = thresholds["three_days_running"]
    sparse_detail = (
        " (" + ", ".join(f"{p}={c}" for p, c in buckets["sparse"]) + ")" if buckets["sparse"] else ""
    )
    lines = [
        f"per-category cohort ({slug}, run {runs[0]['id']}):",
        (
            f"  {len(buckets['healthy'])} healthy | {len(buckets['sparse'])} sparse{sparse_detail} | "
            f"{len(buckets['curator_empty'])} curator-empty | {len(buckets['warn'])} WARN"
        ),
    ]
    for path, streak in buckets["warn"]:
        lines.append(f"  [WARN] {path}: 0 cards, {streak} scrape(s) running (pings at {days})")
    for path, streak, fire_slot in buckets["pinged"]:
        if streak >= days + 5:
            lines.append(
                f"  [PINGED] {path}: 0x{streak} scrapes — broken-detection candidate, "
                f"first ping fired {fire_slot:%Y-%m-%d %H:%M} UTC"
            )
        else:
            lines.append(
                f"  [PINGED] {path}: 0x{streak} scrapes — real-time ping fired "
                f"{fire_slot:%Y-%m-%d %H:%M} UTC"
            )
    for path, current, median in buckets["trend"]:
        pct = round((current - median) / median * 100)
        lines.append(f"  trend: {path}: {current} cards vs 7d median {median:g} ({pct:+d}%)")
    return lines


def build_cohort_section(vendor_entries: list[dict], oos_counts: list[tuple[str, int]]) -> str:
    """vendor_entries: [{slug, active, runs, thresholds, expected_min}] for
    category_cohort_signal vendors. oos_counts: [(slug, oos_24h)] for
    cohort_oos_at_persist vendors (fleet-wide as of 2026-06-04).
    """
    lines: list[str] = []
    for entry in vendor_entries:
        if not entry["active"]:
            # Poller quiet-skips inactive vendors (pause-window noise);
            # the digest is where the pause stays visible. Review-fold
            # 2026-06-04.
            lines.append(
                f"[INACTIVE] {entry['slug']} — vendors.active=false; cohort poll skipped "
                "(operator pause?)"
            )
            continue
        buckets = classify_for_digest(entry["runs"], entry["thresholds"], entry["expected_min"])
        lines.extend(render_vendor_lines(entry["slug"], entry["runs"], buckets, entry["thresholds"]))
    if oos_counts:
        lines.append("cohort-OOS last 24h: " + ", ".join(f"{slug} {n}" for slug, n in oos_counts))
    return "\n".join(lines)


def build_digest(now: datetime, sections: list[str]) -> str:
    body = [s for s in sections if s]
    return "\n".join([f"coralticker health digest — {now:%Y-%m-%d}"] + body)


# ---------------------------------------------------------------------------
# I/O shell — data assembly + post. SECTION_BUILDERS keeps future §6.5
# blocks (scoreboard / DB capacity / GHA minutes / ...) additive.
# ---------------------------------------------------------------------------


def _vendor_row(conn, slug: str) -> dict:
    with conn.cursor() as cur:
        cur.execute("SELECT id, active FROM vendors WHERE slug = %s", (slug,))
        rows = cur.fetchall()
    if not rows:
        raise RuntimeError(f"vendors row not found for slug={slug!r}")
    return rows[0]


def _oos_24h(conn, vendor_id: int) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COALESCE(SUM(listings_oos), 0) AS oos FROM scraper_runs "
            "WHERE vendor_id = %s AND status = 'success' "
            "AND started_at > now() - interval '24 hours'",
            (vendor_id,),
        )
        return int(cur.fetchall()[0]["oos"])


def assemble_cohort_section(conn) -> str:
    import yaml

    from scrapers.common.cohort_signal import VENDORS_DIR

    vendor_entries = []
    oos_counts: list[tuple[str, int]] = []
    for yaml_path in sorted(VENDORS_DIR.glob("*.yaml")):
        config = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
        slug = config.get("slug", yaml_path.stem)
        if not (config.get("category_cohort_signal") or config.get("cohort_oos_at_persist")):
            continue
        row = _vendor_row(conn, slug)
        if config.get("category_cohort_signal"):
            vendor_entries.append({
                "slug": slug,
                "active": row["active"],
                "runs": fetch_recent_success_runs(conn, row["id"]) if row["active"] else [],
                "thresholds": get_thresholds(config),
                "expected_min": int(config.get("expected_min_per_category", 3)),
            })
        if config.get("cohort_oos_at_persist") and row["active"]:
            oos_counts.append((slug, _oos_24h(conn, row["id"])))
    return build_cohort_section(vendor_entries, oos_counts)


SECTION_BUILDERS = [assemble_cohort_section]


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    now = datetime.now(timezone.utc)

    from scrapers.common import db  # late import keeps the pure core test-importable without psycopg env

    conn = db.get_conn()
    try:
        sections = [builder(conn) for builder in SECTION_BUILDERS]
    finally:
        conn.close()

    message = build_digest(now, sections)
    logger.info("posting health digest:\n%s", message)
    post_slack(message)
    return 0


if __name__ == "__main__":
    sys.exit(main())
