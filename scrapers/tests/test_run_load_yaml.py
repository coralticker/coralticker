"""scrapers/tests/test_run_load_yaml.py — CTK-093 SC-3 unit coverage for
`scrapers.common.run._load_yaml` raise-on-missing.

Runnable as:
  python -m scrapers.tests.test_run_load_yaml
or
  python scrapers/tests/test_run_load_yaml.py

No pytest dependency. No DB connection — `_load_yaml` is a pure filesystem
read with `pathlib.Path` + `yaml.safe_load`. Each test stubs the path
resolution to a tmpdir-controlled YAML file.

Coverage:
  test_missing_file_raises_config_error  CTK-093 Q3 — bare error condition
  test_empty_file_returns_empty_dict     yaml.safe_load(...) or {} fallback
  test_present_file_returns_parsed_dict  happy path
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest import mock

from scrapers.common import run
from scrapers.common.errors import ConfigError


def _run_load_yaml_with_vendors_dir(slug: str, vendors_dir: Path) -> dict:
    """Invoke _load_yaml with a tmpdir-rooted vendors directory by stubbing
    the Path(__file__).parent.parent resolution. _load_yaml builds the
    YAML path as `<run.py parent>.parent / 'vendors' / f'{slug}.yaml'`;
    we patch the parent.parent target so the loader reads from tmpdir."""
    # Construct a fake module __file__ such that `Path(...).parent.parent`
    # resolves to vendors_dir.parent (so .parent.parent / "vendors" ==
    # vendors_dir). Two parent levels above the fake file land in vendors_dir's
    # grandparent, so position it as <grandparent>/common/run.py.
    fake_run_file = vendors_dir.parent / "common" / "run.py"
    with mock.patch.object(run, "__file__", str(fake_run_file)):
        return run._load_yaml(slug)


def test_missing_file_raises_config_error():
    """Missing YAML file → ConfigError raised. The path string appears in
    the error message so on-call has the offending path one click away."""
    with tempfile.TemporaryDirectory() as tmp:
        vendors_dir = Path(tmp) / "vendors"
        vendors_dir.mkdir()
        # Note: no YAML file written.
        raised = False
        try:
            _run_load_yaml_with_vendors_dir("nonexistent-vendor", vendors_dir)
        except ConfigError as e:
            raised = True
            assert "nonexistent-vendor.yaml" in str(e), (
                f"ConfigError message should name the missing YAML path; got: {e}"
            )
        assert raised, "missing YAML must raise ConfigError, not warn-and-default"


def test_empty_file_returns_empty_dict():
    """Present-but-empty YAML → returns {} (per-key defaults still apply).
    `yaml.safe_load('')` returns None; the `or {}` collapses to empty dict."""
    with tempfile.TemporaryDirectory() as tmp:
        vendors_dir = Path(tmp) / "vendors"
        vendors_dir.mkdir()
        (vendors_dir / "empty-vendor.yaml").write_text("", encoding="utf-8")
        result = _run_load_yaml_with_vendors_dir("empty-vendor", vendors_dir)
        assert result == {}, (
            f"empty YAML should collapse to empty dict via `... or {{}}`; got: {result!r}"
        )


def test_present_file_returns_parsed_dict():
    """Present YAML with keys → returns parsed dict."""
    with tempfile.TemporaryDirectory() as tmp:
        vendors_dir = Path(tmp) / "vendors"
        vendors_dir.mkdir()
        (vendors_dir / "test-vendor.yaml").write_text(
            "originator_prefix: tv\nproducts_per_page: 50\n",
            encoding="utf-8",
        )
        result = _run_load_yaml_with_vendors_dir("test-vendor", vendors_dir)
        assert result == {"originator_prefix": "tv", "products_per_page": 50}, (
            f"present YAML should parse to dict; got: {result!r}"
        )


# ─── Test runner ──────────────────────────────────────────────────────────────
TESTS = [
    test_missing_file_raises_config_error,
    test_empty_file_returns_empty_dict,
    test_present_file_returns_parsed_dict,
]


def main() -> int:
    passed = 0
    failed = 0
    for fn in TESTS:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL  {fn.__name__}: {e}")
            failed += 1
        except Exception as e:  # noqa: BLE001 — surface unexpected exception type
            print(f"  ERROR {fn.__name__}: {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed (total {len(TESTS)})")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
