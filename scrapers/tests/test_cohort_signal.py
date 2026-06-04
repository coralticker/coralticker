"""scrapers/tests/test_cohort_signal.py — CTK-097 threshold-core tests.

Pure-function tests against in-memory run fixtures (no DB, no network) per
plan §Implementation plan #9. The fixture baseline mirrors CTK-094 dispatch
run 703 (2026-05-31): 21 AquaSD paths — 5 curator-empty, 1 sparse
(/cynarinas/=1), 15 healthy — so the quiet-path assertion is pinned against
the same shape the live verify-pass rail observes.

Runnable as:
  python -m scrapers.tests.test_cohort_signal
"""

from __future__ import annotations

import sys
import traceback
from datetime import datetime, timedelta, timezone

from scrapers.common.cohort_signal import (
    DEFAULT_THRESHOLDS,
    SATURATE_AFTER,
    evaluate,
    filter_to_slot,
    format_ping,
    get_thresholds,
    in_current_slot,
    path_histories,
)

UTC = timezone.utc

# Run-703-shaped baseline (2026-05-31). 5 curator-empty, 1 sparse, 15 healthy.
CURATOR_EMPTY = ["/clams/", "/acanthos/", "/wilsonis/", "/elegances/", "/wellsos-and-trachys/"]
SPARSE = {"/cynarinas/": 1}
HEALTHY = {
    "/acans/": 38, "/acropora/": 355, "/anemones/": 22, "/blastos/": 19,
    "/chalices/": 41, "/euphyllia/": 87, "/favias/": 16, "/fungias-plates/": 12,
    "/gonis-alves/": 28, "/lobos/": 14, "/montipora/": 41, "/mushrooms/": 93,
    "/scolys/": 8, "/softies/": 120, "/zoanthids/": 110,
}


def baseline_counts(**overrides: int) -> dict[str, int]:
    counts = {path: 0 for path in CURATOR_EMPTY}
    counts.update(SPARSE)
    counts.update(HEALTHY)
    counts.update(overrides)
    return counts


def make_runs(counts_newest_first: list[dict[str, int]]) -> list[dict]:
    """Daily-cadence run fixtures, newest-first, ids descending from 731."""
    newest_start = datetime(2026, 6, 4, 9, 51, tzinfo=UTC)
    return [
        {
            "id": 731 - i,
            "started_at": newest_start - timedelta(days=i),
            "per_category_counts": counts,
        }
        for i, counts in enumerate(counts_newest_first)
    ]


def window(n_zero_newest: int, path: str = "/montipora/", depth: int = 14) -> list[dict]:
    """A depth-run window where `path` is zero for the newest n runs and
    healthy-baseline before that."""
    counts = [baseline_counts(**{path: 0})] * n_zero_newest
    counts += [baseline_counts()] * (depth - n_zero_newest)
    return make_runs(counts)


# ---------------------------------------------------------------------------
# Persistence predicate
# ---------------------------------------------------------------------------


def test_persistence_trips_at_exact_streak_3_with_prior_nonzero():
    verdicts = evaluate(window(3), DEFAULT_THRESHOLDS)
    assert len(verdicts) == 1, verdicts
    v = verdicts[0]
    assert v["kind"] == "persistence"
    assert v["path"] == "/montipora/"
    assert v["run_id"] == 731
    assert "3 consecutive scrapes" in v["detail"]
    assert "(was 41 on 2026-06-01)" in v["detail"]


def test_persistence_no_fire_streak_2():
    assert evaluate(window(2), DEFAULT_THRESHOLDS) == []


def test_persistence_no_fire_streak_4_already_fired():
    # Streak 4 fired yesterday at streak 3; exact-streak firing suppresses re-fire.
    assert evaluate(window(4), DEFAULT_THRESHOLDS) == []


def test_curator_empty_all_zero_window_never_fires():
    # The 5 baseline curator-empty paths are zero across the whole window —
    # including streak == 3 positions — and must never produce a verdict.
    runs = make_runs([baseline_counts()] * 14)
    assert evaluate(runs, DEFAULT_THRESHOLDS) == []


def test_short_window_all_zero_is_curator_empty_not_persistence():
    # A young vendor with only 3 all-zero observations for a path has no prior
    # non-zero in window: classified curator-empty, no fire (conservative).
    runs = make_runs([baseline_counts(**{"/montipora/": 0})] * 3)
    assert evaluate(runs, DEFAULT_THRESHOLDS) == []


# ---------------------------------------------------------------------------
# Breadth predicate
# ---------------------------------------------------------------------------


def zeroed(n: int) -> dict[str, int]:
    """Baseline with the first n healthy paths forced to zero (on top of the
    5 curator-empties, which count toward the breadth total by design —
    the ratified 8 already prices them in)."""
    overrides = {path: 0 for path in sorted(HEALTHY)[:n]}
    return baseline_counts(**overrides)


def test_breadth_trips_at_9_zeros_when_prior_below():
    # 5 curator-empty + 4 newly-zero healthy = 9 zeros > 8; prior run at 5.
    runs = make_runs([zeroed(4)] + [baseline_counts()] * 13)
    verdicts = evaluate(runs, DEFAULT_THRESHOLDS)
    breadth = [v for v in verdicts if v["kind"] == "breadth"]
    assert len(breadth) == 1, verdicts
    assert "9 of 21 categories at zero" in breadth[0]["detail"]
    assert breadth[0]["run_id"] == 731


def test_breadth_no_fire_at_exactly_8():
    # 5 curator-empty + 3 newly-zero = 8 zeros — not > 8.
    runs = make_runs([zeroed(3)] + [baseline_counts()] * 13)
    assert [v for v in evaluate(runs, DEFAULT_THRESHOLDS) if v["kind"] == "breadth"] == []


def test_breadth_no_fire_when_prior_run_also_tripped():
    # Transition gate: both newest runs at 9 zeros — fired yesterday, not today.
    runs = make_runs([zeroed(4), zeroed(4)] + [baseline_counts()] * 12)
    assert [v for v in evaluate(runs, DEFAULT_THRESHOLDS) if v["kind"] == "breadth"] == []


# ---------------------------------------------------------------------------
# Saturate-suppress hint
# ---------------------------------------------------------------------------


def test_saturate_hint_at_exact_streak_8_silent_at_9():
    threshold_plus = DEFAULT_THRESHOLDS["three_days_running"] + SATURATE_AFTER
    at_8 = evaluate(window(threshold_plus), DEFAULT_THRESHOLDS)
    assert len(at_8) == 1, at_8
    assert at_8[0]["kind"] == "saturate"
    assert "broken-detection candidate" in at_8[0]["detail"]
    assert evaluate(window(threshold_plus + 1), DEFAULT_THRESHOLDS) == []


# ---------------------------------------------------------------------------
# Slot-window dedup (plan D-5)
# ---------------------------------------------------------------------------


def test_slot_window_in_slot_fires():
    # Slot grid :11. Now 10:30 → window (09:11, 10:11]. AquaSD daily run at
    # 09:51 is in-window and fires, even though "now" sits past the slot
    # (GH-delayed poller fire evaluates its nominal slot's window).
    now = datetime(2026, 6, 4, 10, 30, tzinfo=UTC)
    started = datetime(2026, 6, 4, 9, 51, tzinfo=UTC)
    assert in_current_slot(started, now)
    verdicts = evaluate(window(3), DEFAULT_THRESHOLDS)
    assert filter_to_slot(verdicts, now) == verdicts


def test_slot_window_next_slot_suppressed():
    # Same tripping run re-evaluated by the next poll: now 11:30 → window
    # (10:11, 11:11]; the 09:51 run falls outside and is suppressed.
    now = datetime(2026, 6, 4, 11, 30, tzinfo=UTC)
    started = datetime(2026, 6, 4, 9, 51, tzinfo=UTC)
    assert not in_current_slot(started, now)
    assert filter_to_slot(evaluate(window(3), DEFAULT_THRESHOLDS), now) == []


def test_slot_boundary_inclusive_exclusive():
    # (prev slot, current slot] — a run exactly on the slot boundary belongs
    # to that slot; a run exactly on the previous boundary does not.
    now = datetime(2026, 6, 4, 10, 15, tzinfo=UTC)  # current slot 10:11
    assert in_current_slot(datetime(2026, 6, 4, 10, 11, tzinfo=UTC), now)
    assert not in_current_slot(datetime(2026, 6, 4, 9, 11, tzinfo=UTC), now)


# ---------------------------------------------------------------------------
# Missing-key + thresholds + healthy baseline + message format
# ---------------------------------------------------------------------------


def test_missing_key_treated_as_zero():
    # A path absent from a run's map wasn't iterated that run (YAML edit or
    # parser abort) — not "zero cards observed". The reader still treats it
    # as 0 (an uniterated path produced no cards either way), so dropping a
    # path from the parser's output behaves like an N->0 transition.
    counts_without = {p: c for p, c in baseline_counts().items() if p != "/montipora/"}
    runs = make_runs([counts_without] * 3 + [baseline_counts()] * 11)
    histories = path_histories(runs)
    assert histories["/montipora/"][:4] == [0, 0, 0, 41]
    verdicts = evaluate(runs, DEFAULT_THRESHOLDS)
    assert len(verdicts) == 1 and verdicts[0]["path"] == "/montipora/"


def test_thresholds_default_when_yaml_block_absent():
    assert get_thresholds({}) == {"three_days_running": 3, "max_empty_per_scrape": 8}
    assert get_thresholds({"cohort_signal_thresholds": None}) == DEFAULT_THRESHOLDS


def test_thresholds_read_from_yaml_block():
    config = {"cohort_signal_thresholds": {"three_days_running": 2, "max_empty_per_scrape": 4}}
    assert get_thresholds(config) == {"three_days_running": 2, "max_empty_per_scrape": 4}
    # Partial block: absent keys fall back per-key.
    partial = {"cohort_signal_thresholds": {"max_empty_per_scrape": 4}}
    assert get_thresholds(partial) == {"three_days_running": 3, "max_empty_per_scrape": 4}


def test_healthy_baseline_produces_zero_verdicts():
    # The verify-pass quiet path in unit form: a full run-703-shaped window
    # (5 curator-empty, 1 sparse, 15 healthy) must stay silent.
    runs = make_runs([baseline_counts()] * 14)
    assert evaluate(runs, DEFAULT_THRESHOLDS) == []


def test_format_ping_shape():
    verdicts = evaluate(window(3), DEFAULT_THRESHOLDS)
    message = format_ping("aquasd", verdicts)
    lines = message.splitlines()
    assert lines[0] == "cohort-signal WARN — aquasd"
    assert lines[1].startswith("/montipora/: 0 cards for 3 consecutive scrapes")
    assert lines[-1] == "run 731, started 2026-06-04 09:51 UTC"


def main() -> None:
    tests = [
        test_persistence_trips_at_exact_streak_3_with_prior_nonzero,
        test_persistence_no_fire_streak_2,
        test_persistence_no_fire_streak_4_already_fired,
        test_curator_empty_all_zero_window_never_fires,
        test_short_window_all_zero_is_curator_empty_not_persistence,
        test_breadth_trips_at_9_zeros_when_prior_below,
        test_breadth_no_fire_at_exactly_8,
        test_breadth_no_fire_when_prior_run_also_tripped,
        test_saturate_hint_at_exact_streak_8_silent_at_9,
        test_slot_window_in_slot_fires,
        test_slot_window_next_slot_suppressed,
        test_slot_boundary_inclusive_exclusive,
        test_missing_key_treated_as_zero,
        test_thresholds_default_when_yaml_block_absent,
        test_thresholds_read_from_yaml_block,
        test_healthy_baseline_produces_zero_verdicts,
        test_format_ping_shape,
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
