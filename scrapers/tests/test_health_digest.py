"""scrapers/tests/test_health_digest.py — CTK-097 + CTK-221 digest tests.

Pure-function tests against in-memory fixtures (no DB, no network) per plan
§Implementation plan #9 digest-assembly list + the 2026-06-04 review-fold
([INACTIVE] line). Reuses the run-703-shaped baseline from test_cohort_signal
so digest and ping suites pin the same world.

CTK-221 reshaped the render layer for operator legibility: a react/no-react
top verdict, per-line severity emoji (🔴/🟠/🟢), duration-in-days on the
react lines, plain-English nouns, and a trend-noise floor. The bucket
classifier (classify_for_digest) and the I/O shell are untouched, so the
bucket-classification tests below are unchanged; the render/verdict tests
pin the new shape and fail on a format regression.

Runnable as:
  python -m scrapers.tests.test_health_digest
"""

from __future__ import annotations

import sys
import traceback
from datetime import datetime, timedelta, timezone

from scrapers.common.cohort_signal import DEFAULT_THRESHOLDS
from scrapers.common.health_digest import (
    SEV_AMBER,
    SEV_GREEN,
    SEV_RED,
    _humanize_empty_duration,
    build_cohort_section,
    build_digest,
    build_verdict,
    classify_for_digest,
    render_vendor_lines,
    slot_for,
)
from scrapers.tests.test_cohort_signal import baseline_counts, make_runs, window

UTC = timezone.utc
EXPECTED_MIN = 3  # aquasd.yaml expected_min_per_category
# Fixed digest-fire instant, same UTC day as the newest fixture run
# (2026-06-04 09:51) so duration-in-days reads are deterministic.
NOW = datetime(2026, 6, 4, 17, 11, tzinfo=UTC)


def entry(slug="aquasd", active=True, runs=None):
    return {
        "slug": slug,
        "active": active,
        "runs": runs if runs is not None else make_runs([baseline_counts()] * 14),
        "thresholds": DEFAULT_THRESHOLDS,
        "expected_min": EXPECTED_MIN,
    }


def classify(runs):
    return classify_for_digest(runs, DEFAULT_THRESHOLDS, EXPECTED_MIN)


def render(slug, runs, buckets=None):
    return render_vendor_lines(slug, runs, buckets or classify(runs), DEFAULT_THRESHOLDS, now=NOW)


def make_hourly_runs(counts_newest_first, newest_start=datetime(2026, 6, 4, 16, 11, tzinfo=UTC)):
    """Like make_runs, but hourly-cadence spacing — a 14-run window spans ~14h,
    the case where a day-only duration reading would collapse to '0 days'."""
    return [
        {"id": 731 - i, "started_at": newest_start - timedelta(hours=i), "per_category_counts": c}
        for i, c in enumerate(counts_newest_first)
    ]


# ---------------------------------------------------------------------------
# Bucket classification (classify_for_digest — untouched by CTK-221)
# ---------------------------------------------------------------------------


def test_healthy_buckets():
    buckets = classify(make_runs([baseline_counts()] * 14))
    assert len(buckets["healthy"]) == 15
    assert buckets["sparse"] == [("/cynarinas/", 1)]
    assert buckets["warn"] == []
    assert buckets["pinged"] == []


def test_curator_empty_labeled_not_warned():
    buckets = classify(make_runs([baseline_counts()] * 14))
    assert sorted(buckets["curator_empty"]) == sorted(
        ["/clams/", "/acanthos/", "/wilsonis/", "/elegances/", "/wellsos-and-trachys/"]
    )
    assert buckets["warn"] == []


def test_pinged_bucket_keeps_streak_and_threshold_slot():
    # classify still computes threshold_slot even though the render layer now
    # ignores it (duration is measured from the streak START instead).
    buckets = classify(window(3))
    assert len(buckets["pinged"]) == 1
    path, streak, threshold_slot = buckets["pinged"][0]
    assert (path, streak) == ("/montipora/", 3)
    assert threshold_slot == datetime(2026, 6, 4, 10, 11, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Render layer (CTK-221) — severity, duration, plain English
# ---------------------------------------------------------------------------


def test_healthy_summary_is_green_and_plain_english():
    lines = render("aquasd", make_runs([baseline_counts()] * 14))
    summary = lines[0]
    assert summary.startswith(SEV_GREEN)
    assert summary == (
        f"{SEV_GREEN} aquasd (run 731): 15 categories healthy, "
        "1 sparse (/cynarinas/: 1 card), 5 empty categories we track (nothing in stock)"
    )
    # No operator jargon leaks into the summary.
    for jargon in ("curator-empty", "WARN", "|"):
        assert jargon not in summary


def test_warn_line_is_amber_and_counts_scrapes():
    lines = render("aquasd", window(2))
    warn = [ln for ln in lines if ln.startswith(SEV_AMBER)]
    assert warn == [
        f"{SEV_AMBER} /montipora/ (aquasd): 2 scrapes in a row with zero cards (reacts at 3)"
    ]
    assert all("0x" not in ln for ln in lines)


def test_pinged_line_is_red_with_duration_in_days():
    # streak 3: oldest zero is runs[2] @ 2026-06-02 09:51; NOW - that = 2 days.
    lines = render("aquasd", window(3))
    red = [ln for ln in lines if ln.startswith(SEV_RED)]
    assert red == [
        f"{SEV_RED} /montipora/ (aquasd): no cards for 2 days (3 scrapes) — "
        "could be a sellout or the scraper's category mapping broke; check the page"
    ]


def test_duration_measured_from_streak_start_not_threshold_slot():
    # streak 8: streak START is runs[7] @ 2026-05-28 -> 7 days. The later
    # threshold-slot crossing (2026-05-30 10:11) would read only 5 days; the
    # render must use the earlier, larger number (CTK-221 deliverable #3).
    line = [ln for ln in render("aquasd", window(8)) if ln.startswith(SEV_RED)][0]
    assert "no cards for 7 days" in line
    assert "5 days" not in line


def test_humanize_empty_duration_units():
    # Daily fixtures read in days (unchanged); sub-daily falls through to hours.
    assert _humanize_empty_duration(timedelta(days=7, hours=5)) == "7 days"
    assert _humanize_empty_duration(timedelta(days=1)) == "1 day"
    assert _humanize_empty_duration(timedelta(hours=3)) == "3 hours"
    assert _humanize_empty_duration(timedelta(hours=1)) == "1 hour"
    assert _humanize_empty_duration(timedelta(minutes=40)) == "under an hour"


def test_react_line_reads_hours_for_subdaily_vendor():
    # Hourly vendor, 3-scrape streak spanning ~3h: the react line must read
    # "3 hours", not the old cadence-blind "0 days" (CTK-221 /code-review fold).
    counts = [baseline_counts(**{"/montipora/": 0})] * 3 + [baseline_counts()] * 11
    runs = make_hourly_runs(counts)
    line = [ln for ln in render("aquasd", runs) if ln.startswith(SEV_RED)][0]
    assert "no cards for 3 hours" in line
    assert "0 days" not in line


def test_render_no_longer_asserts_broken_or_leaks_stamps():
    for n in (3, 8):  # normal + former-saturate streaks
        line = [ln for ln in render("aquasd", window(n)) if ln.startswith(SEV_RED)][0]
        for banned in (
            "broken-detection",
            "threshold crossed",
            "PING-DUE",
            "fired",
            "UTC",
            "best-effort",
        ):
            assert banned not in line
        assert "check the page" in line


def test_scraper_down_renders_red_line():
    # Active vendor, zero successful runs in the window -> scraper likely down.
    lines = render_vendor_lines("aquasd", [], {}, DEFAULT_THRESHOLDS, now=NOW)
    assert lines == [
        f"{SEV_RED} aquasd: no successful scrapes in the window — the scraper may be down, check it"
    ]


def test_trend_line_kept_above_median_floor():
    # /acropora/ 355 -> 120 (-66% vs median 355): median >> floor, line renders.
    sag = baseline_counts(**{"/acropora/": 120})
    runs = make_runs([sag] + [baseline_counts()] * 6)
    lines = render("aquasd", runs)
    trend = [ln for ln in lines if "7-day median" in ln]
    assert trend == [
        f"{SEV_AMBER} /acropora/ (aquasd): 120 cards vs its 7-day median of 355 (-66%, down)"
    ]


def test_trend_noise_floor_suppresses_tiny_median():
    # /scolys/ median 1 (below the 5-card floor) swings +200% -> suppressed.
    # /montipora/ median 170 (above the floor) swings -73% -> kept. classify
    # flags BOTH (it owns only the deviation gate); the render floor drops
    # the noisy one (CTK-221 deliverable #6).
    scolys = [3, 1, 1, 1, 1, 1, 1, 1]
    monti = [46, 170, 170, 170, 170, 170, 170, 170]
    counts = [
        baseline_counts(**{"/scolys/": scolys[i], "/montipora/": monti[i]}) for i in range(8)
    ]
    runs = make_runs(counts)
    buckets = classify(runs)
    trend_paths = {p for p, _, _ in buckets["trend"]}
    assert {"/scolys/", "/montipora/"} <= trend_paths  # classify keeps both

    lines = render("aquasd", runs, buckets)
    trend_lines = [ln for ln in lines if "7-day median" in ln]
    assert any("/montipora/" in ln for ln in trend_lines)  # kept
    assert all("/scolys/" not in ln for ln in trend_lines)  # dropped by the floor


# ---------------------------------------------------------------------------
# Verdict + section + digest assembly (CTK-221)
# ---------------------------------------------------------------------------


def test_verdict_green_when_all_healthy():
    section = build_cohort_section([entry()], [], now=NOW)
    assert build_verdict([section]) == f"{SEV_GREEN} all healthy — no action"


def test_verdict_amber_counts_categories_worth_a_look():
    section = build_cohort_section(
        [entry(slug="aquasd", runs=window(2)), entry(slug="poto", runs=window(2))], [], now=NOW
    )
    assert build_verdict([section]) == f"{SEV_AMBER} 2 categories worth a look"


def test_verdict_amber_singular():
    section = build_cohort_section([entry(runs=window(2))], [], now=NOW)
    assert build_verdict([section]) == f"{SEV_AMBER} 1 category worth a look"


def test_verdict_red_headlines_longest_empty_category():
    section = build_cohort_section([entry(runs=window(8))], [], now=NOW)
    assert build_verdict([section]) == f"{SEV_RED} react: /montipora/ empty 7 days"


def test_verdict_red_falls_back_when_no_day_count():
    # Whole-scraper-down red line carries no "N days" -> generic react headline.
    section = build_cohort_section([entry(runs=[])], [], now=NOW)
    assert build_verdict([section]) == f"{SEV_RED} react: aquasd — check it"


def test_verdict_red_outranks_amber():
    # A vendor with both a WARN (amber) and a PING-DUE (red) verdicts red.
    section = build_cohort_section(
        [entry(slug="aquasd", runs=window(8)), entry(slug="poto", runs=window(2))], [], now=NOW
    )
    verdict = build_verdict([section])
    assert verdict.startswith(SEV_RED)


def test_inactive_vendor_renders_green_paused_line():
    section = build_cohort_section([entry(active=False, runs=[])], [], now=NOW)
    assert section == (
        f"{SEV_GREEN} aquasd: paused (not currently tracking) — unpause when you want it back"
    )
    # A deliberate pause must not drive the verdict.
    assert build_verdict([section]) == f"{SEV_GREEN} all healthy — no action"


def test_oos_tail_is_bulleted_desc_with_zeros_dropped():
    # tidal_gardens (0) dropped; remaining sorted biggest-spike-first; one
    # bullet line per vendor under a 🟢 no-action header.
    section = build_cohort_section(
        [entry()], [("poto", 4), ("aquasd", 12), ("tidal_gardens", 0)], now=NOW
    )
    tail = section.splitlines()[-3:]
    assert tail == [
        f"{SEV_GREEN} Sold out / delisted in the last 24h — routine (corals sold or pulled); "
        "worth a look only if one vendor is unusually high:",
        "  • aquasd — 12",
        "  • poto — 4",
    ]


def test_oos_tail_all_zero_single_line():
    section = build_cohort_section([entry()], [("aquasd", 0), ("poto", 0)], now=NOW)
    assert section.splitlines()[-1] == f"{SEV_GREEN} nothing sold or delisted in the last 24h"
    assert "•" not in section


def test_oos_empty_list_renders_no_tail():
    # No OOS-tracking vendors in this digest -> no tail line at all (distinct
    # from the all-zero case, which does report "nothing ...").
    section = build_cohort_section([entry()], [], now=NOW)
    assert "sold or delisted" not in section
    assert "•" not in section


def test_build_digest_verdict_first_then_header():
    section = build_cohort_section([entry(runs=window(8))], [], now=NOW)
    message = build_digest(NOW, [section])
    lines = message.splitlines()
    assert lines[0] == f"{SEV_RED} react: /montipora/ empty 7 days"
    assert lines[1] == "coralticker health digest — 2026-06-04"
    assert lines[2].startswith(SEV_GREEN)  # vendor summary follows


def test_build_digest_drops_empty_sections():
    message = build_digest(NOW, ["section one", "", "section two"])
    lines = message.splitlines()
    assert lines[0].startswith(SEV_GREEN)  # verdict: no red/amber in the strings
    assert lines[1] == "coralticker health digest — 2026-06-04"
    assert lines[2:] == ["section one", "section two"]


def test_no_operator_jargon_in_a_full_digest():
    # End-to-end plain-English guard: a digest carrying every line type must
    # contain none of the retired operator nouns (CTK-221 deliverable #4).
    section = build_cohort_section(
        [entry(slug="aquasd", runs=window(8)), entry(slug="poto", runs=window(2))],
        [("aquasd", 39), ("poto", 8)],
        now=NOW,
    )
    message = build_digest(NOW, [section])
    for jargon in (
        "curator-empty",
        "cohort-OOS",
        "PING-DUE",
        "[WARN]",
        "[INACTIVE]",
        "0x",
        "threshold crossed",
        "broken-detection",
    ):
        assert jargon not in message, jargon


def test_slot_for_boundaries():
    # slot_for is untouched (classify still uses it); pin it stays correct.
    assert slot_for(datetime(2026, 6, 4, 9, 51, tzinfo=UTC)) == datetime(2026, 6, 4, 10, 11, tzinfo=UTC)
    assert slot_for(datetime(2026, 6, 4, 10, 11, tzinfo=UTC)) == datetime(2026, 6, 4, 10, 11, tzinfo=UTC)
    assert slot_for(datetime(2026, 6, 4, 10, 12, tzinfo=UTC)) == datetime(2026, 6, 4, 11, 11, tzinfo=UTC)


def main() -> None:
    tests = [
        test_healthy_buckets,
        test_curator_empty_labeled_not_warned,
        test_pinged_bucket_keeps_streak_and_threshold_slot,
        test_healthy_summary_is_green_and_plain_english,
        test_warn_line_is_amber_and_counts_scrapes,
        test_pinged_line_is_red_with_duration_in_days,
        test_humanize_empty_duration_units,
        test_react_line_reads_hours_for_subdaily_vendor,
        test_duration_measured_from_streak_start_not_threshold_slot,
        test_render_no_longer_asserts_broken_or_leaks_stamps,
        test_scraper_down_renders_red_line,
        test_trend_line_kept_above_median_floor,
        test_trend_noise_floor_suppresses_tiny_median,
        test_verdict_green_when_all_healthy,
        test_verdict_amber_counts_categories_worth_a_look,
        test_verdict_amber_singular,
        test_verdict_red_headlines_longest_empty_category,
        test_verdict_red_falls_back_when_no_day_count,
        test_verdict_red_outranks_amber,
        test_inactive_vendor_renders_green_paused_line,
        test_oos_tail_is_bulleted_desc_with_zeros_dropped,
        test_oos_tail_all_zero_single_line,
        test_oos_empty_list_renders_no_tail,
        test_build_digest_verdict_first_then_header,
        test_build_digest_drops_empty_sections,
        test_no_operator_jargon_in_a_full_digest,
        test_slot_for_boundaries,
    ]
    failures = []
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception:  # noqa: BLE001
            failures.append(t.__name__)
            print(f"FAIL {t.__name__}")
            traceback.print_exc()
    print(f"\n{len(tests) - len(failures)}/{len(tests)} tests passed")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
