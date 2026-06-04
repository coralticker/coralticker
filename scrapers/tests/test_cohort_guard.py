"""scrapers/tests/test_cohort_guard.py — CTK-120 D-4 unit coverage for the
Stage 5.65 cohort-guard pure helpers in scrapers.common.run:

  _completeness_degraded   D-1 pages-gate predicate + no-op guards
  _resolve_flip_cap        D-2 default floor/ratio + YAML override validation
  _flip_cap_tripped        D-2 strict-greater boundary (at-cap passes)

Gate-level behavior (the booleans dropping cohort decisions inside
_apply_cohort_gate) lives in test_diff_cohort_oos.py with the rest of the
fold-#12 gate suite. This file covers the rails' input handling — the
canary_floor ConfigError pattern (run.py Stage 5.6) had no unit home before
CTK-120; cohort_flip_cap validation tests land here as the config-rail
precedent.

No pytest dependency. No DB connection — all three helpers are pure.

Runnable as:
  python -m scrapers.tests.test_cohort_guard
"""

from __future__ import annotations

import sys
import traceback

from scrapers.common.run import (
    _completeness_degraded,
    _flip_cap_tripped,
    _resolve_flip_cap,
)
from scrapers.common.errors import ConfigError


# ---------------------------------------------------------------------------
# D-1 — _completeness_degraded
# ---------------------------------------------------------------------------


def test_completeness_none_pages_is_silent():
    """pages_fetched=None (pre-CTK-094 parser / pre-parse failure) → rail
    silent regardless of median. Mirrors Stage 5.8's original no-op guard."""
    assert _completeness_degraded(None, 10.0) is False


def test_completeness_zero_median_is_silent():
    """median_pages_7d=0 (pre-median bootstrap, NULL legacy rows filtered by
    db.get_7d_median_pages_fetched) → rail silent. No false-fire in a
    vendor's first 7 days."""
    assert _completeness_degraded(1, 0.0) is False


def test_completeness_below_half_median_fires():
    """4 of ~9-page median = 44% < 50% → degraded. The TSA worked example
    band (pagination dies mid-catalog, canary silent at 20-99% of median)."""
    assert _completeness_degraded(4, 9.0) is True


def test_completeness_at_half_median_passes():
    """Exactly 50% does NOT fire — predicate is strict-less (pages_fetched
    < 0.5 * median), unchanged from Stage 5.8."""
    assert _completeness_degraded(5, 10.0) is False


def test_completeness_full_fetch_passes():
    assert _completeness_degraded(9, 9.0) is False


# ---------------------------------------------------------------------------
# D-2 — _resolve_flip_cap: default floor / ratio + crossover
# ---------------------------------------------------------------------------


def test_flip_cap_default_floor_small_vendor():
    """Small vendor (reef_chasers-class, prev_in_stock=138): 0.25 x 138 =
    34.5 → floor 50 wins."""
    assert _resolve_flip_cap({}, 138) == 50


def test_flip_cap_default_ratio_large_vendor():
    """Large vendor (TSA-class, prev_in_stock=1844): 0.25 x 1844 = 461 →
    ratio wins over the floor."""
    assert _resolve_flip_cap({}, 1844) == 461


def test_flip_cap_floor_ratio_crossover():
    """Crossover at prev_in_stock=200: 0.25 x 200 = 50 = floor (either side
    of 200 flips which term wins)."""
    assert _resolve_flip_cap({}, 200) == 50
    assert _resolve_flip_cap({}, 199) == 50   # ratio 49.75 → floor
    assert _resolve_flip_cap({}, 204) == 51   # ratio 51 → ratio


def test_flip_cap_zero_prev_in_stock_is_floor():
    """Empty catalog (first scrape) → floor 50. The cap rail never blocks a
    bootstrap run (cohort absent-set is empty anyway with no existing rows)."""
    assert _resolve_flip_cap({}, 0) == 50


# ---------------------------------------------------------------------------
# D-2 — _resolve_flip_cap: YAML override + ConfigError validation
# (canary_floor pattern: coalesce-then-range-check)
# ---------------------------------------------------------------------------


def test_flip_cap_yaml_override_wins():
    """cohort_flip_cap overrides the default absolutely. Operator use case:
    a known one-shot mass-flip (e.g., a cohort_oos_at_persist opt-in backlog
    flush, CTK-105 run-889 class) gets a temporary override for the flush
    cycle; no vendor carries a standing override as of CTK-120 Session 1a."""
    assert _resolve_flip_cap({"cohort_flip_cap": 2000}, 2300) == 2000


def test_flip_cap_blank_yaml_collapses_to_default():
    """`cohort_flip_cap:` / `: ~` / `: null` parse to None; `or None`
    coalesce treats them as absent (canary_floor parity per run.py Stage 5.6
    Session 5 fold #3) — default applies, no TypeError on int(None)."""
    assert _resolve_flip_cap({"cohort_flip_cap": None}, 1000) == 250
    assert _resolve_flip_cap({"cohort_flip_cap": ""}, 1000) == 250
    assert _resolve_flip_cap({"cohort_flip_cap": 0}, 1000) == 250


def test_flip_cap_negative_override_raises_config_error():
    """Negative typo (cohort_flip_cap: -15) makes len(cohort) > cap always
    True — every cohort run would trip the guard and land 'partial'. Loud
    ConfigError beats that silent semantic; routes to error_class='config'
    via the run() handler, same as canary_floor range validation."""
    raised = False
    try:
        _resolve_flip_cap({"cohort_flip_cap": -15}, 1000)
    except ConfigError as e:
        raised = True
        assert "cohort_flip_cap" in str(e)
    assert raised, "negative cohort_flip_cap must raise ConfigError"


def test_flip_cap_extreme_override_raises_config_error():
    """Off-by-orders-of-magnitude typo (cohort_flip_cap: 100000) silently
    disables the cap rail; 10000 upper bound matches canary_floor's."""
    raised = False
    try:
        _resolve_flip_cap({"cohort_flip_cap": 100000}, 1000)
    except ConfigError:
        raised = True
    assert raised, "out-of-range cohort_flip_cap must raise ConfigError"


def test_flip_cap_boundary_values_of_range():
    """Range is exclusive at both ends per the (0, 10000) contract: 1 and
    9999 valid; 10000 raises."""
    assert _resolve_flip_cap({"cohort_flip_cap": 1}, 1000) == 1
    assert _resolve_flip_cap({"cohort_flip_cap": 9999}, 1000) == 9999
    raised = False
    try:
        _resolve_flip_cap({"cohort_flip_cap": 10000}, 1000)
    except ConfigError:
        raised = True
    assert raised


# ---------------------------------------------------------------------------
# D-2 — _flip_cap_tripped: at-cap passes, cap+1 trips
# ---------------------------------------------------------------------------


def test_flip_cap_tripped_at_cap_passes():
    """Strict-greater contract: a cohort absent-set exactly AT the cap
    persists. A vendor delisting precisely cap rows in one cycle is the
    accepted edge of legit churn, not a trip."""
    assert _flip_cap_tripped(50, 50) is False


def test_flip_cap_tripped_cap_plus_one_trips():
    assert _flip_cap_tripped(51, 50) is True


def test_flip_cap_tripped_zero_cohort_never_trips():
    assert _flip_cap_tripped(0, 50) is False


if __name__ == "__main__":
    tests = [
        test_completeness_none_pages_is_silent,
        test_completeness_zero_median_is_silent,
        test_completeness_below_half_median_fires,
        test_completeness_at_half_median_passes,
        test_completeness_full_fetch_passes,
        test_flip_cap_default_floor_small_vendor,
        test_flip_cap_default_ratio_large_vendor,
        test_flip_cap_floor_ratio_crossover,
        test_flip_cap_zero_prev_in_stock_is_floor,
        test_flip_cap_yaml_override_wins,
        test_flip_cap_blank_yaml_collapses_to_default,
        test_flip_cap_negative_override_raises_config_error,
        test_flip_cap_extreme_override_raises_config_error,
        test_flip_cap_boundary_values_of_range,
        test_flip_cap_tripped_at_cap_passes,
        test_flip_cap_tripped_cap_plus_one_trips,
        test_flip_cap_tripped_zero_cohort_never_trips,
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
