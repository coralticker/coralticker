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
ping thresholds surfaces here, and anything at or past the real-time ping
threshold is flagged with a [PING-DUE] marker rather than omitted. The
digest CANNOT confirm a ping actually fired — the hourly poller is best-
effort (GH Actions silently drops cron slots) and no ping-state table
exists (D-5) — so it flags the threshold crossing, not a fired ping.
Omitting the line would make the digest lie as a standalone "is the world
okay" surface (plan §Implementation plan #8 no-double-alert mechanism).

Operator-legibility rewrite (CTK-221): the render layer leads with a
react/no-react verdict, tags every line with a severity emoji, states
durations in days rather than raw UTC stamps, and drops the operator
jargon for plain English. Emoji ARE the point on this operator Slack
surface (the no-emoji-in-artifacts rule is lifted here — CTK-221 plan
§Voice); the palette matches the live CTK-218 watchdog on the same
channel: red = react now, amber = worth a look, green = healthy.

Per-vendor lines, per plan §7 (counts are PRE-overlap-dedup raw card
counts per migration 0024 — rendered as "cards", never "listings"):

  🔴 react: /montipora/ empty 2 days
  coralticker health digest — 2026-06-04
  🟢 aquasd (run 731): 15 categories healthy, 1 sparse (/cynarinas/: 1 card), 5 empty categories we track (nothing in stock)
  🔴 /montipora/ (aquasd): no cards for 2 days (3 scrapes) — could be a sellout or the scraper's category mapping broke; check the page
  🟢 Sold out / delisted in the last 24h — routine (corals sold or pulled); worth a look only if one vendor is unusually high:
    • aquasd — 12
    • poto — 4

A vendor with vendors.active=false renders a paused line instead of its
cohort lines (review-fold 2026-06-04): the hourly poller deliberately
quiet-skips inactive vendors to avoid pause-window noise, so the daily
digest is where an operator pause stays visible.

Runnable as:
  python -m scrapers.common.health_digest
"""

from __future__ import annotations

import logging
import re
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

# Trend-noise floor (CTK-221): a category whose 7-day median is below this
# many cards never renders a trend line, however large its percentage swing.
# A +100% on a median of 1.5 cards is arithmetic noise, not signal; a -73%
# on a median of 170 is real. Second gate, applied at render time on top of
# TREND_DEVIATION (classify_for_digest, which owns the deviation gate, is
# untouched — the floor lives here so the data layer stays as-is).
TREND_MIN_MEDIAN = 5

# Operator severity palette (CTK-221) — matches the live CTK-218 email-digest
# watchdog on the same operator Slack channel (commit 9ead160): red = react
# now, amber = worth a look, green = healthy / no action. Deliberately NOT the
# ✅/⚠️/🟥 artifact-review vocabulary — this is operator tooling, not a review
# surface, and emoji are the point here (plan §Voice lifts the no-emoji rule).
SEV_RED = "🔴"
SEV_AMBER = "🟠"
SEV_GREEN = "🟢"

# Lifts "no cards for N days" back out of a rendered react line so build_digest
# can headline the worst one in the top verdict. Kept in lockstep with the
# PING-DUE wording in render_vendor_lines; the format-regression test guards it.
_REACT_DAYS_RE = re.compile(r"no cards for (\d+) day")


# ---------------------------------------------------------------------------
# Pure section core — no DB, no network. Tests drive these directly.
# ---------------------------------------------------------------------------


def slot_for(started_at: datetime) -> datetime:
    """The nominal poller slot whose window (slot-1h, slot] contains
    started_at — i.e. the slot the real-time poller WOULD fire a ping in for
    this run. Not proof it did: GH Actions drops slots and the digest has no
    ping-state table (D-5), so callers must not assert a ping actually fired.
    """
    slot = started_at.replace(minute=SLOT_MINUTE, second=0, microsecond=0)
    if slot < started_at:
        slot += timedelta(hours=1)
    return slot


def classify_for_digest(runs: list[dict], thresholds: dict, expected_min: int) -> dict:
    """Bucket every path in the window for digest rendering.

    Returns {"healthy": [...], "sparse": [(path, count)], "curator_empty":
    [...], "warn": [(path, streak)], "pinged": [(path, streak,
    threshold_slot)], "trend": [(path, current, median)]} — the "pinged"
    bucket holds paths at or past the real-time ping threshold (it does NOT
    assert a ping fired; see render_vendor_lines / slot_for). It includes
    saturate-state paths (streak >= three_days_running + 5), which render
    the broken-detection wording.
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
            # The run that pushed the streak to the real-time ping threshold
            # sits at index streak - days in the newest-first window. This is
            # the slot the threshold was crossed in — NOT proof a ping fired
            # (poller is best-effort, GH drops slots; no ping-state table, D-5).
            threshold_slot = slot_for(runs[streak - days]["started_at"])
            buckets["pinged"].append((path, streak, threshold_slot))
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


def _plural(n: int, noun: str = "") -> str:
    """'day' -> 'days' unless n == 1. Empty noun returns just the suffix."""
    return f"{noun}{'' if n == 1 else 's'}"


def render_vendor_lines(
    slug: str, runs: list[dict], buckets: dict, thresholds: dict, now: datetime | None = None
) -> list[str]:
    if not runs:
        # Active vendor with zero successful runs in the window — the scraper
        # isn't landing runs at all, which is a react-now signal on its own.
        return [
            f"{SEV_RED} {slug}: no successful scrapes in the window — the scraper may be down, check it"
        ]
    if now is None:
        now = datetime.now(timezone.utc)
    days = thresholds["three_days_running"]

    sparse_detail = (
        " (" + ", ".join(f"{p}: {c} {_plural(c, 'card')}" for p, c in buckets["sparse"]) + ")"
        if buckets["sparse"]
        else ""
    )
    healthy_n = len(buckets["healthy"])
    empty_n = len(buckets["curator_empty"])
    # Green summary line — the healthy portion of the vendor, in plain English.
    # "empty categories we track" = curator-empty: a category we poll that had
    # nothing in stock this window (not a break — just no product).
    lines = [
        f"{SEV_GREEN} {slug} (run {runs[0]['id']}): "
        f"{healthy_n} categor{'y' if healthy_n == 1 else 'ies'} healthy, "
        f"{len(buckets['sparse'])} sparse{sparse_detail}, "
        f"{empty_n} empty categor{'y' if empty_n == 1 else 'ies'} we track (nothing in stock)"
    ]
    # Below-threshold zero streaks — worth a look, not yet react.
    for path, streak in buckets["warn"]:
        lines.append(
            f"{SEV_AMBER} {path} ({slug}): {streak} {_plural(streak, 'scrape')} in a row with zero cards "
            f"(reacts at {days})"
        )
    # At or past the real-time ping threshold — react. Duration is stated in
    # DAYS since the streak STARTED (runs[streak - 1], the oldest zero in the
    # run), NOT the later ping-threshold crossing: "how long has it been empty"
    # is the operator's actual question. Language softened per CTK-221 — the
    # digest no longer asserts "broken"; a zero streak is usually a sellout,
    # and the sellout-vs-break probe is a separate CTK.
    for path, streak, _threshold_slot in buckets["pinged"]:
        empty_days = (now - runs[streak - 1]["started_at"]).days
        lines.append(
            f"{SEV_RED} {path} ({slug}): no cards for {empty_days} {_plural(empty_days, 'day')} "
            f"({streak} {_plural(streak, 'scrape')}) — could be a sellout or the scraper's category "
            "mapping broke; check the page"
        )
    # Trend anomaly — only when the 7-day median clears the noise floor
    # (TREND_MIN_MEDIAN); the deviation gate itself already ran in classify.
    for path, current, median in buckets["trend"]:
        if median < TREND_MIN_MEDIAN:
            continue
        pct = round((current - median) / median * 100)
        direction = "down" if current < median else "up"
        lines.append(
            f"{SEV_AMBER} {path} ({slug}): {current} cards vs its 7-day median of {median:g} "
            f"({pct:+d}%, {direction})"
        )
    return lines


def build_cohort_section(
    vendor_entries: list[dict], oos_counts: list[tuple[str, int]], now: datetime | None = None
) -> str:
    """vendor_entries: [{slug, active, runs, thresholds, expected_min}] for
    category_cohort_signal vendors. oos_counts: [(slug, oos_24h)] for
    cohort_oos_at_persist vendors (fleet-wide as of 2026-06-04).

    `now` defaults to the current UTC instant so the untouched I/O shell
    (assemble_cohort_section) needs no change; tests pass it explicitly for
    a deterministic duration reading.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    lines: list[str] = []
    for entry in vendor_entries:
        if not entry["active"]:
            # Poller quiet-skips inactive vendors (pause-window noise); the
            # digest is where the pause stays visible. Review-fold 2026-06-04.
            # Green: a deliberate pause needs no action — the line is a
            # reminder, not an alert, so it stays out of the react/worth-a-look
            # counts the top verdict is built from.
            lines.append(
                f"{SEV_GREEN} {entry['slug']}: paused (not currently tracking) — "
                "unpause when you want it back"
            )
            continue
        buckets = classify_for_digest(entry["runs"], entry["thresholds"], entry["expected_min"])
        lines.extend(
            render_vendor_lines(entry["slug"], entry["runs"], buckets, entry["thresholds"], now=now)
        )
    # cohort-OOS tail — a routine, no-action stat (corals sell or get pulled
    # every day), so it stays 🟢 and out of the verdict counts. Rendered as a
    # vertical list, biggest spike first, so an unusually-high vendor stands
    # out at a glance. Zero-count vendors are dropped; an empty oos_counts
    # (no OOS-tracking vendors in this digest at all) renders nothing.
    nonzero = sorted((pair for pair in oos_counts if pair[1] > 0), key=lambda pair: pair[1], reverse=True)
    if oos_counts and not nonzero:
        lines.append(f"{SEV_GREEN} nothing sold or delisted in the last 24h")
    elif nonzero:
        lines.append(
            f"{SEV_GREEN} Sold out / delisted in the last 24h — routine (corals sold or pulled); "
            "worth a look only if one vendor is unusually high:"
        )
        lines.extend(f"  • {slug} — {n}" for slug, n in nonzero)
    return "\n".join(lines)


def _subject(line: str) -> str:
    """The category/vendor a severity line is about — the first token after
    the leading severity emoji."""
    parts = line.split()
    for i, tok in enumerate(parts):
        if tok in (SEV_RED, SEV_AMBER, SEV_GREEN) and i + 1 < len(parts):
            return parts[i + 1].rstrip(":")
    return parts[0] if parts else line


def build_verdict(sections: list[str]) -> str:
    """The react/no-react top line — the worst state across every vendor and
    bucket, derived from the already-rendered section lines (the per-line
    severity emoji is the single source of truth, so a future section that
    follows the same palette feeds the verdict for free).
    """
    lines = [ln for section in sections for ln in section.splitlines()]
    red = [ln for ln in lines if ln.startswith(SEV_RED)]
    amber = [ln for ln in lines if ln.startswith(SEV_AMBER)]
    if red:
        # Headline the longest-running empty category; fall back to the first
        # react line (e.g. a whole-scraper-down line has no day count).
        worst = None
        for ln in red:
            m = _REACT_DAYS_RE.search(ln)
            if m and (worst is None or int(m.group(1)) > worst[0]):
                worst = (int(m.group(1)), _subject(ln))
        if worst:
            n, path = worst
            return f"{SEV_RED} react: {path} empty {n} {_plural(n, 'day')}"
        return f"{SEV_RED} react: {_subject(red[0])} — check it"
    if amber:
        n = len(amber)
        return f"{SEV_AMBER} {n} categor{'y' if n == 1 else 'ies'} worth a look"
    return f"{SEV_GREEN} all healthy — no action"


def build_digest(now: datetime, sections: list[str]) -> str:
    body = [s for s in sections if s]
    verdict = build_verdict(body)
    header = f"coralticker health digest — {now:%Y-%m-%d}"
    return "\n".join([verdict, header] + body)


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
