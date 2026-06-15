"""scrapers/tests/test_data_row_parity.py — CTK-161 D-3 INV-01 parity (Python
half). Pins the Python mirror (scrapers/tools/data_row.py) to the committed
golden (lib/format/data-row-golden.json). The TS half (lib/format/data-row.test.ts)
pins formatDataRow() to the SAME file — so a drift on EITHER side fails its own
test, with no node-in-pytest coupling.

Pure — no DB, no network, no env. Runnable as:
  python -m scrapers.tests.test_data_row_parity

Coverage:
  test_golden_parity                 every golden case: mirror output == expected
  test_relative_minute_singular      60s -> "1 minute ago" (boundary, mirrors TS)
  test_relative_hour_singular        3600s -> "1 hour ago"
  test_relative_day_singular         86400s -> "1 day ago"
  test_relative_future_clamps        future timestamp -> "1 minute ago" (clamp)
  test_unknown_kind_raises           an unmapped value-kind raises (drift guard)
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scrapers.tools.data_row import format_data_row, format_relative_time

GOLDEN_PATH = Path(__file__).resolve().parents[2] / "lib" / "format" / "data-row-golden.json"

NOW = datetime(2026, 5, 14, 12, 0, 0, tzinfo=timezone.utc)


def _load_golden() -> dict:
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


def test_golden_parity():
    golden = _load_golden()
    now = datetime.fromisoformat(golden["now"])
    for case in golden["cases"]:
        got = format_data_row(case["fields"], now)
        assert got == case["expected"], (
            f"{case['name']}: mirror produced {got!r}, golden expects {case['expected']!r}"
        )


def test_relative_minute_singular():
    past = NOW - timedelta(seconds=60)
    assert format_relative_time(past, NOW) == "1 minute ago"


def test_relative_hour_singular():
    past = NOW - timedelta(seconds=3600)
    assert format_relative_time(past, NOW) == "1 hour ago"


def test_relative_day_singular():
    past = NOW - timedelta(seconds=86_400)
    assert format_relative_time(past, NOW) == "1 day ago"


def test_relative_future_clamps():
    # Negative diff clamps to 0, minute floor clamps to 1 — mirrors the TS source.
    future = NOW + timedelta(seconds=30)
    assert format_relative_time(future, NOW) == "1 minute ago"


def test_unknown_kind_raises():
    try:
        format_data_row([{"label": "X", "value": {"kind": "nope"}}], NOW)
    except ValueError:
        return
    raise AssertionError("expected ValueError on an unmapped value-kind")


def _run_all():
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failures = 0
    for fn in fns:
        try:
            fn()
            print(f"ok   {fn.__name__}")
        except AssertionError as e:
            failures += 1
            print(f"FAIL {fn.__name__}: {e}")
    print(f"\n{len(fns) - failures}/{len(fns)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    import sys
    sys.exit(_run_all())
