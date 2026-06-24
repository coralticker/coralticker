"""scrapers/tests/test_staleness_cap.py — CTK-190 unit coverage for the
--days positive-int guard on scrapers.tools.staleness_cap.

The guard exists because the tool now runs --apply UNATTENDED on a weekly cron
(staleness-cap.yml). A zero/negative --days inverts make_interval(days => N)
and mass-flips in_stock=false fleet-wide — a Tier-1A wrong-availability event
if it ever reached the UPDATE. These tests assert the bad value is rejected
during argparse (exit 2) BEFORE any DB connection opens.

Two layers:
  - _positive_int   the pure type callable (valid/invalid in isolation)
  - main()          via patched argv, with db.get_conn booby-trapped so a DB
                    touch is a test failure — proves the short-circuit is
                    upstream of the connection, not just a no-op apply.

No pytest dependency. No DB connection (the booby-trap guarantees it).

Runnable as:
  python -m scrapers.tests.test_staleness_cap
"""

from __future__ import annotations

import argparse
import sys
import traceback

from scrapers.common import db
from scrapers.tools import staleness_cap


# ---------------------------------------------------------------------------
# _positive_int — the pure argparse type callable
# ---------------------------------------------------------------------------


def test_positive_int_accepts_positive():
    assert staleness_cap._positive_int("21") == 21
    assert staleness_cap._positive_int("1") == 1


def test_positive_int_rejects_zero():
    raised = False
    try:
        staleness_cap._positive_int("0")
    except argparse.ArgumentTypeError as e:
        raised = True
        assert "positive" in str(e)
    assert raised, "--days 0 must raise ArgumentTypeError"


def test_positive_int_rejects_negative():
    raised = False
    try:
        staleness_cap._positive_int("-1")
    except argparse.ArgumentTypeError as e:
        raised = True
        assert "positive" in str(e)
    assert raised, "--days -1 must raise ArgumentTypeError"


def test_positive_int_rejects_non_integer():
    raised = False
    try:
        staleness_cap._positive_int("3.5")
    except argparse.ArgumentTypeError:
        raised = True
    assert raised, "--days 3.5 must raise ArgumentTypeError"


# ---------------------------------------------------------------------------
# main() via patched argv — exit non-zero, no DB touch
# ---------------------------------------------------------------------------


def _run_main(argv):
    """Invoke staleness_cap.main() with a patched argv. Booby-trap
    db.get_conn so that reaching the DB raises AssertionError — the validation
    must exit during parse_args(), well before any connection. Always restores
    sys.argv and db.get_conn."""
    orig_argv = sys.argv
    orig_get_conn = db.get_conn

    def _boom(*a, **k):
        raise AssertionError(
            "db.get_conn called — --days validation did not short-circuit "
            "before DB access"
        )

    sys.argv = argv
    db.get_conn = _boom
    try:
        return staleness_cap.main()
    finally:
        sys.argv = orig_argv
        db.get_conn = orig_get_conn


def _assert_exits_2(argv, label):
    try:
        _run_main(argv)
    except SystemExit as e:
        # argparse error() exits 2; anything non-zero satisfies "exit non-zero",
        # but pin to 2 since that is argparse's contract for a bad argument.
        assert e.code == 2, f"{label}: expected exit code 2, got {e.code}"
        return
    raise AssertionError(f"{label}: expected SystemExit, none raised")


def test_main_days_zero_exits_2_no_db():
    _assert_exits_2(["staleness_cap", "--days", "0"], "--days 0")


def test_main_days_negative_exits_2_no_db():
    _assert_exits_2(["staleness_cap", "--days", "-1"], "--days -1")


def test_main_days_negative_with_apply_exits_2_no_db():
    """The unattended-cron shape: --apply present, bad --days. Must still
    exit before the booby-trapped get_conn — the value never reaches UPDATE."""
    _assert_exits_2(["staleness_cap", "--apply", "--days", "-7"], "--apply --days -7")


if __name__ == "__main__":
    tests = [
        test_positive_int_accepts_positive,
        test_positive_int_rejects_zero,
        test_positive_int_rejects_negative,
        test_positive_int_rejects_non_integer,
        test_main_days_zero_exits_2_no_db,
        test_main_days_negative_exits_2_no_db,
        test_main_days_negative_with_apply_exits_2_no_db,
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
