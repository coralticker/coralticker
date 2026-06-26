"""scrapers/tests/test_category_coverage_breaker.py — CTK-200 circuit-breaker.

Pure unit — no DB, no network. CTK-200 productizes the CTK-199 backfill into a
scheduled weekly audit; the breaker is the unattended-safety gate that aborts the
apply (exit 2, zero writes) when a run would change more than expected. A large
weekly drift is an anomaly signal, not normal rotation.

Exercise-the-guarantee (feedback_review_results_test_exercises_guarantee): each
assert pins a boundary that FAILS if the gate logic is loosened — the OR of the
two ceilings, the > (not >=) boundary, the zero-change no-op, and the empty-fleet
fail-safe. The guard tests pin the (0, 100] / >0 param contract so a future
"positive-int" loosening trips a red test.
"""

from __future__ import annotations

import argparse

import pytest

from scrapers.tools.ctk199_category_coverage_backfill import (
    _breaker_tripped,
    _positive_int,
    _pct,
)

# Representative fleet size (in-stock listings); the % ceiling is taken over this.
FLEET = 7133


def test_breaker_passes_under_both_ceilings():
    # A normal week: a handful of changes, well under 100 and under 1.5%.
    assert _breaker_tripped(25, FLEET, 100, 1.5) is False


def test_breaker_zero_changes_never_trips():
    # Nothing to write is never an anomaly — even against a tiny fleet it must not
    # trip (else a quiet week false-alarms Slack).
    assert _breaker_tripped(0, FLEET, 100, 1.5) is False
    assert _breaker_tripped(0, 1, 100, 1.5) is False


def test_breaker_absolute_ceiling_is_strict_greater_than():
    # Exactly at the ceiling does NOT trip; one over does. Pins the > boundary.
    assert _breaker_tripped(100, FLEET, 100, 1.5) is False
    assert _breaker_tripped(101, FLEET, 100, 1.5) is True


def test_breaker_pct_ceiling_trips_independently_of_absolute():
    # On a small fleet, a count UNDER the absolute ceiling can still exceed the
    # %-ceiling — the OR matters. 90/1000 = 9% > 1.5%, but 90 < 100.
    assert _breaker_tripped(90, 1000, 100, 1.5) is True


def test_breaker_pct_boundary_is_strict_greater_than():
    # applied/fleet*100 == max_pct does not trip; just over does.
    assert _breaker_tripped(15, 1000, 100, 1.5) is False   # exactly 1.5%
    assert _breaker_tripped(16, 1000, 100, 1.5) is True    # 1.6%


def test_breaker_empty_fleet_fails_safe():
    # A fleet count of 0 (DB read returned nothing) can't yield a ratio — abort
    # rather than divide-by-zero or silently pass.
    assert _breaker_tripped(10, 0, 100, 1.5) is True


def test_positive_int_guard():
    assert _positive_int("100") == 100
    for bad in ("0", "-1", "-100"):
        with pytest.raises(argparse.ArgumentTypeError):
            _positive_int(bad)


def test_pct_guard_rejects_outside_open_0_to_100():
    assert _pct("1.5") == 1.5
    assert _pct("100") == 100.0          # upper bound inclusive
    for bad in ("0", "-1", "100.1", "150"):
        with pytest.raises(argparse.ArgumentTypeError):
            _pct(bad)
