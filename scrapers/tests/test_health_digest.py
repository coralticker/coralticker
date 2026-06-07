"""scrapers/tests/test_health_digest.py — CTK-097 digest-assembly tests.

Pure-function tests against in-memory fixtures (no DB, no network) per plan
§Implementation plan #9 digest-assembly list + the 2026-06-04 review-fold
([INACTIVE] line). Reuses the run-703-shaped baseline from
test_cohort_signal so digest and ping suites pin the same world.

Runnable as:
  python -m scrapers.tests.test_health_digest
"""

from __future__ import annotations

import sys
import traceback
from datetime import datetime, timezone

from scrapers.common.cohort_signal import DEFAULT_THRESHOLDS
from scrapers.common.health_digest import (
    build_cohort_section,
    build_digest,
    classify_for_digest,
    render_vendor_lines,
    slot_for,
)
from scrapers.tests.test_cohort_signal import baseline_counts, make_runs, window

UTC = timezone.utc
EXPECTED_MIN = 3  # aquasd.yaml expected_min_per_category


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


# ---------------------------------------------------------------------------
# Bucket classification
# ---------------------------------------------------------------------------


def test_healthy_collapse_to_count_no_itemized_lines():
    runs = make_runs([baseline_counts()] * 14)
    buckets = classify(runs)
    assert len(buckets["healthy"]) == 15
    lines = render_vendor_lines("aquasd", runs, buckets, DEFAULT_THRESHOLDS)
    assert lines[1].startswith("  15 healthy | 1 sparse (/cynarinas/=1) | 5 curator-empty | 0 WARN")
    # No per-path line for any healthy path.
    assert all("/acropora/" not in line for line in lines)


def test_curator_empty_labeled_not_warned():
    buckets = classify(make_runs([baseline_counts()] * 14))
    assert sorted(buckets["curator_empty"]) == sorted(
        ["/clams/", "/acanthos/", "/wilsonis/", "/elegances/", "/wellsos-and-trachys/"]
    )
    assert buckets["warn"] == []


def test_sparse_not_warned():
    buckets = classify(make_runs([baseline_counts()] * 14))
    assert buckets["sparse"] == [("/cynarinas/", 1)]
    assert buckets["warn"] == []


def test_below_threshold_streak_renders_warn_line():
    runs = window(2)  # /montipora/ zero for 2 scrapes — below ping threshold
    buckets = classify(runs)
    assert buckets["warn"] == [("/montipora/", 2)]
    lines = render_vendor_lines("aquasd", runs, buckets, DEFAULT_THRESHOLDS)
    assert any(line.startswith("  [WARN] /montipora/: 0 cards, 2 scrape(s) running") for line in lines)


def test_pinged_cross_reference_with_threshold_slot():
    runs = window(3)  # threshold crossed at streak 3 — newest run 2026-06-04 09:51 -> slot 10:11
    buckets = classify(runs)
    assert len(buckets["pinged"]) == 1
    path, streak, threshold_slot = buckets["pinged"][0]
    assert (path, streak) == ("/montipora/", 3)
    assert threshold_slot == datetime(2026, 6, 4, 10, 11, tzinfo=UTC)
    lines = render_vendor_lines("aquasd", runs, buckets, DEFAULT_THRESHOLDS)
    assert any(
        line == (
            "  [PING-DUE] /montipora/: 0x3 scrapes — real-time ping threshold crossed "
            "2026-06-04 10:11 UTC; poller best-effort, that slot may have been dropped"
        )
        for line in lines
    )


def test_pinged_line_does_not_assert_a_ping_fired():
    # The defect that reopened the verify window: the digest computes the
    # slot from streak arithmetic alone and has no ping-state table (D-5),
    # so it must never claim a ping "fired" — GH drops poller slots, and a
    # false "already alerted" read makes the operator dismiss the condition.
    for n in (3, 8):  # normal and saturate (broken-detection) wordings
        runs = window(n)
        lines = render_vendor_lines("aquasd", runs, classify(runs), DEFAULT_THRESHOLDS)
        pinged = [ln for ln in lines if "[PING-DUE]" in ln]
        assert len(pinged) == 1
        line = pinged[0]
        assert "fired" not in line  # no fired-ping assertion, either wording
        assert "[PINGED]" not in line  # the past-tense marker is gone
        assert "best-effort" in line and "may have been dropped" in line


def test_pinged_streak_5_threshold_slot_points_at_completing_run():
    # Streak 5: the threshold was crossed two runs ago (streak hit 3 on 2026-06-02 09:51).
    runs = window(5)
    buckets = classify(runs)
    _, streak, threshold_slot = buckets["pinged"][0]
    assert streak == 5
    assert threshold_slot == datetime(2026, 6, 2, 10, 11, tzinfo=UTC)


def test_saturate_state_renders_broken_detection_wording():
    runs = window(8)
    lines = render_vendor_lines("aquasd", runs, classify(runs), DEFAULT_THRESHOLDS)
    assert any("broken-detection candidate" in line for line in lines)


def test_trend_marker_only_past_50pct_deviation():
    # /acropora/ sags 355 -> 120 (-66% vs median 355): trend line renders.
    # /euphyllia/ 87 -> 60 (-31%): no trend line.
    sag = baseline_counts(**{"/acropora/": 120, "/euphyllia/": 60})
    runs = make_runs([sag] + [baseline_counts()] * 6)
    buckets = classify(runs)
    assert [(p, c) for p, c, _ in buckets["trend"]] == [("/acropora/", 120)]
    lines = render_vendor_lines("aquasd", runs, buckets, DEFAULT_THRESHOLDS)
    assert any(line.startswith("  trend: /acropora/: 120 cards vs 7d median 355 (-66%)") for line in lines)


# ---------------------------------------------------------------------------
# Section + digest assembly
# ---------------------------------------------------------------------------


def test_inactive_vendor_renders_inactive_line():
    # Review-fold 2026-06-04: the poller quiet-skips inactive vendors; the
    # digest is where the pause stays visible.
    section = build_cohort_section([entry(active=False, runs=[])], [])
    assert section == (
        "[INACTIVE] aquasd — vendors.active=false; cohort poll skipped (operator pause?)"
    )


def test_no_runs_renders_no_runs_line():
    section = build_cohort_section([entry(runs=[])], [])
    assert section == "per-category cohort (aquasd): no successful runs in window"


def test_cohort_oos_tail_line():
    section = build_cohort_section([entry()], [("aquasd", 12), ("poto", 4), ("tidal_gardens", 0)])
    assert section.splitlines()[-1] == "cohort-OOS last 24h: aquasd 12, poto 4, tidal_gardens 0"


def test_build_digest_header_and_empty_section_omitted():
    now = datetime(2026, 6, 4, 17, 11, tzinfo=UTC)
    message = build_digest(now, ["section one", "", "section two"])
    lines = message.splitlines()
    assert lines[0] == "coralticker health digest — 2026-06-04"
    assert lines[1:] == ["section one", "section two"]


def test_slot_for_boundaries():
    # 09:51 run -> 10:11 slot; a run exactly on :11 belongs to its own slot.
    assert slot_for(datetime(2026, 6, 4, 9, 51, tzinfo=UTC)) == datetime(2026, 6, 4, 10, 11, tzinfo=UTC)
    assert slot_for(datetime(2026, 6, 4, 10, 11, tzinfo=UTC)) == datetime(2026, 6, 4, 10, 11, tzinfo=UTC)
    assert slot_for(datetime(2026, 6, 4, 10, 12, tzinfo=UTC)) == datetime(2026, 6, 4, 11, 11, tzinfo=UTC)


def main() -> None:
    tests = [
        test_healthy_collapse_to_count_no_itemized_lines,
        test_curator_empty_labeled_not_warned,
        test_sparse_not_warned,
        test_below_threshold_streak_renders_warn_line,
        test_pinged_cross_reference_with_threshold_slot,
        test_pinged_line_does_not_assert_a_ping_fired,
        test_pinged_streak_5_threshold_slot_points_at_completing_run,
        test_saturate_state_renders_broken_detection_wording,
        test_trend_marker_only_past_50pct_deviation,
        test_inactive_vendor_renders_inactive_line,
        test_no_runs_renders_no_runs_line,
        test_cohort_oos_tail_line,
        test_build_digest_header_and_empty_section_omitted,
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
