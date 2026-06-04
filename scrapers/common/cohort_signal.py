"""scrapers/common/cohort_signal.py — CTK-097 per-category cohort signal poller.

Hourly operator-side reader of scraper_runs.per_category_counts (CTK-094
migration 0024) for vendors with category_cohort_signal: true in their YAML
(AquaSD only at v1; POTO and TG write '{}' by design and are never selected).
Evaluates two threshold predicates and posts a real-time WARN ping to the
operator Slack channel (#coralticker-ops) when one trips. The daily health
digest (scrapers/common/health_digest.py, Session 3) is the guaranteed
delivery surface; this poller is best-effort latency reduction on top of it.

Predicates (CTK-097 plan §Implementation plan #2, transition-shaped over the
trailing 14 status='success' runs so curator-empty paths never ping):

- Persistence: a path's zero-streak on the latest run reaches EXACTLY
  three_days_running (default 3), with at least one non-zero observation
  earlier in the window. Streak 4+ does not re-fire.
- Breadth: the latest run's zero-entry count exceeds max_empty_per_scrape
  (default 8) and the prior run's did not.
- Saturate-suppress (CTK-090 F12 symptom handler): at zero-streak EXACTLY
  three_days_running + 5, one "broken-detection candidate" hint, then
  silence until the streak breaks. F12's "5 consecutive cron cycles" is
  read as vendor-scrape cycles, not poller cycles — an hourly poller
  watching a daily vendor would otherwise saturate in 5 hours on one
  unchanged run.

Ping dedup is stateless (plan D-5): every predicate trips on the newest run,
and a ping fires iff that run's started_at falls in the nominal slot window
(previous poller cron slot, current poller cron slot], slots derived from
the `11 * * * *` schedule. Slot windows partition time, so a run is
evaluated against exactly one window — exact-once without a state table.
A skipped poller fire orphans its slot's runs; the daily digest backstops.

Counts are PRE-overlap-dedup raw card counts (migration 0024 COMMENT —
/softies/ and /zoanthids/ share ~57 cards on AquaSD). Threshold logic only
ever compares a path against its own history, never across paths, never
against vendor_listings rows.

Thresholds per plan D-2: per-vendor YAML `cohort_signal_thresholds` block;
an absent block opts into the ratified defaults (3 / 8).

Runnable as:
  python -m scrapers.common.cohort_signal
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
import yaml

logger = logging.getLogger(__name__)

# Trailing window of status='success' runs read per vendor. Matches the
# migration-0024 comment's own LIMIT 14 query shape; a path at zero across
# the entire window is classified curator-empty (digest label, never a ping).
TRAILING_WINDOW = 14

# Poller cron minute (plan D-8, `11 * * * *`). Slot boundaries derive from
# this constant, not from wall-clock at fire time — a GH-delayed fire still
# evaluates the window of its nominal slot.
SLOT_MINUTE = 11

# Saturate hint fires at zero-streak == three_days_running + SATURATE_AFTER.
SATURATE_AFTER = 5

DEFAULT_THRESHOLDS = {"three_days_running": 3, "max_empty_per_scrape": 8}

VENDORS_DIR = Path(__file__).parent.parent / "vendors"


# ---------------------------------------------------------------------------
# Pure threshold core — no DB, no network. Tests drive these directly.
# ---------------------------------------------------------------------------


def get_thresholds(config: dict) -> dict:
    """Read cohort_signal_thresholds from a vendor config dict; absent block
    or absent keys opt into the ratified defaults (3 / 8) so a vendor without
    the YAML block behaves identically to one carrying the default values.
    """
    block = config.get("cohort_signal_thresholds") or {}
    return {
        "three_days_running": int(block.get("three_days_running", DEFAULT_THRESHOLDS["three_days_running"])),
        "max_empty_per_scrape": int(block.get("max_empty_per_scrape", DEFAULT_THRESHOLDS["max_empty_per_scrape"])),
    }


def path_histories(runs: list[dict]) -> dict[str, list[int]]:
    """Per-path count history, newest-first, over the union of paths seen in
    the window. A path missing from a run's map means the path wasn't iterated
    that run (YAML edit or parser abort), not "zero cards observed" — but the
    threshold reader treats it as 0 per plan §1: an uniterated path produces
    no cards either way, and the distinction lives in this comment rather
    than in a second sentinel value.
    """
    paths: set[str] = set()
    for run in runs:
        paths.update((run["per_category_counts"] or {}).keys())
    return {
        path: [int((run["per_category_counts"] or {}).get(path, 0)) for run in runs]
        for path in sorted(paths)
    }


def zero_streak(history: list[int]) -> int:
    """Consecutive zeros from the newest observation."""
    streak = 0
    for count in history:
        if count != 0:
            break
        streak += 1
    return streak


def is_curator_empty(history: list[int]) -> bool:
    """All-zero across the window — AquaSD-curator-curated empty (5 baseline
    paths at v1: /clams/ /acanthos/ /wilsonis/ /elegances/ /wellsos-and-trachys/).
    Digest labels these; pings never fire on them.
    """
    return all(count == 0 for count in history)


def last_nonzero(history: list[int], runs: list[dict]) -> tuple[int, datetime] | None:
    """Most recent non-zero observation as (count, run started_at), for the
    "(was 41 on 2026-06-01)" ping context line. None when curator-empty.
    """
    for count, run in zip(history, runs):
        if count != 0:
            return count, run["started_at"]
    return None


def evaluate(runs: list[dict], thresholds: dict) -> list[dict]:
    """Evaluate both predicates + the saturate hint against a newest-first
    run window. Every verdict trips on runs[0] (streaks are counted from the
    newest run; breadth compares runs[0] against runs[1]) — the slot-window
    filter therefore only ever inspects runs[0].started_at.

    Returns a list of verdict dicts:
      {"kind": "persistence"|"breadth"|"saturate", "path": str|None,
       "run_id": int, "started_at": datetime, "detail": str}
    """
    if not runs:
        return []

    days = thresholds["three_days_running"]
    max_empty = thresholds["max_empty_per_scrape"]
    latest = runs[0]
    verdicts: list[dict] = []

    histories = path_histories(runs)

    for path, history in histories.items():
        if is_curator_empty(history):
            continue
        streak = zero_streak(history)
        if streak == days:
            prior = last_nonzero(history, runs)
            was = f" (was {prior[0]} on {prior[1]:%Y-%m-%d})" if prior else ""
            verdicts.append({
                "kind": "persistence",
                "path": path,
                "run_id": latest["id"],
                "started_at": latest["started_at"],
                "detail": f"{path}: 0 cards for {streak} consecutive scrapes{was}",
            })
        elif streak == days + SATURATE_AFTER:
            verdicts.append({
                "kind": "saturate",
                "path": path,
                "run_id": latest["id"],
                "started_at": latest["started_at"],
                "detail": (
                    f"{path}: still at zero after {streak} scrapes — "
                    "broken-detection candidate (CTK-090 F12)"
                ),
            })

    # Breadth — transition gate: fires only when the latest run trips and the
    # prior run didn't. With a single-run window the prior count is taken as
    # 0 (a first-ever scrape arriving with >max_empty zeros fires; vendor
    # onboarding is exactly when a misconfigured category_paths list should
    # be loud).
    zeros_latest = sum(1 for history in histories.values() if history[0] == 0)
    zeros_prior = (
        sum(1 for history in histories.values() if len(history) > 1 and history[1] == 0)
        if len(runs) > 1
        else 0
    )
    if zeros_latest > max_empty and zeros_prior <= max_empty:
        verdicts.append({
            "kind": "breadth",
            "path": None,
            "run_id": latest["id"],
            "started_at": latest["started_at"],
            "detail": (
                f"{zeros_latest} of {len(histories)} categories at zero in latest "
                f"scrape (threshold {max_empty}) — fleet-wide drift candidate"
            ),
        })

    return verdicts


def current_slot(now: datetime) -> datetime:
    """Most recent nominal poller slot (:SLOT_MINUTE) at or before now."""
    slot = now.replace(minute=SLOT_MINUTE, second=0, microsecond=0)
    if slot > now:
        slot -= timedelta(hours=1)
    return slot


def in_current_slot(started_at: datetime, now: datetime) -> bool:
    """Slot-window membership (plan D-5): (previous slot, current slot].
    A run evaluated on a later poll falls outside the then-current window
    and is suppressed — exact-once without state.
    """
    slot = current_slot(now)
    return slot - timedelta(hours=1) < started_at <= slot


def filter_to_slot(verdicts: list[dict], now: datetime) -> list[dict]:
    """Keep only verdicts whose tripping run landed in the current slot window."""
    return [v for v in verdicts if in_current_slot(v["started_at"], now)]


def format_ping(slug: str, verdicts: list[dict]) -> str:
    """One Slack message per vendor per poll, bundling all surviving verdicts.
    Operator-scan shape per plan §7; plain mrkdwn text, no block kit.
    """
    lines = [f"cohort-signal WARN — {slug}"]
    lines.extend(v["detail"] for v in verdicts)
    run = verdicts[0]
    lines.append(f"run {run['run_id']}, started {run['started_at']:%Y-%m-%d %H:%M} UTC")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# I/O shell — YAML discovery, DB read, Slack post, orchestration.
# ---------------------------------------------------------------------------


def load_cohort_vendor_configs() -> list[dict]:
    """All vendor YAML configs with category_cohort_signal: true, slug included.
    YAML-driven discovery per plan §1 — data-side discovery can't bind
    per-vendor thresholds and would silently pick up an untuned vendor.
    """
    configs = []
    for yaml_path in sorted(VENDORS_DIR.glob("*.yaml")):
        config = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
        if config.get("category_cohort_signal"):
            config.setdefault("slug", yaml_path.stem)
            configs.append(config)
    return configs


def fetch_recent_success_runs(conn, vendor_id: int) -> list[dict]:
    """Trailing TRAILING_WINDOW status='success' runs, newest-first.
    psycopg's dict_row + jsonb give per_category_counts back as a dict.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, started_at, per_category_counts "
            "FROM scraper_runs "
            "WHERE vendor_id = %s AND status = 'success' "
            "ORDER BY started_at DESC LIMIT %s",
            (vendor_id, TRAILING_WINDOW),
        )
        return cur.fetchall()


def post_slack(text: str) -> None:
    """Direct webhook POST per arch §6.3 lean-direct-curl posture. Raises on
    non-2xx so a webhook failure fails the workflow run loud.
    """
    resp = requests.post(
        os.environ["SLACK_WEBHOOK_URL"],
        json={"text": text},
        timeout=10,
    )
    resp.raise_for_status()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    now = datetime.now(timezone.utc)

    from scrapers.common import db  # late import keeps the pure core test-importable without psycopg env

    configs = load_cohort_vendor_configs()
    if not configs:
        logger.info("no cohort-signal vendors configured; nothing to poll")
        return 0

    conn = db.get_conn()
    try:
        for config in configs:
            slug = config["slug"]
            with conn.cursor() as cur:
                cur.execute("SELECT id, active FROM vendors WHERE slug = %s", (slug,))
                rows = cur.fetchall()
            if not rows:
                raise RuntimeError(f"vendors row not found for slug={slug!r}")
            if not rows[0]["active"]:
                # Inactive = operator pause window. The poller is observability,
                # not scrape-path — skip quiet rather than inherit run.py's
                # loud-raise (which would add hourly noise alerts during every
                # pause window, the exact failure shape open-items' cron-during-
                # pause entry tracks).
                logger.info("vendor %s inactive; skipping cohort poll", slug)
                continue

            runs = fetch_recent_success_runs(conn, rows[0]["id"])
            verdicts = filter_to_slot(evaluate(runs, get_thresholds(config)), now)
            if verdicts:
                message = format_ping(slug, verdicts)
                logger.warning("posting cohort-signal ping for %s:\n%s", slug, message)
                post_slack(message)
            else:
                logger.info("vendor %s: no cohort-signal verdicts this slot", slug)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
