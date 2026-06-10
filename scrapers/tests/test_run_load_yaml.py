"""scrapers/tests/test_run_load_yaml.py — CTK-093 SC-3 unit coverage for
`scrapers.common.run._load_yaml` raise-on-missing, extended by CTK-102 with
category_filter axis shape-validation coverage.

Runnable as:
  python -m scrapers.tests.test_run_load_yaml
or
  python scrapers/tests/test_run_load_yaml.py

No pytest dependency. No DB connection — `_load_yaml` is a pure filesystem
read with `pathlib.Path` + `yaml.safe_load`. Each test stubs the path
resolution to a tmpdir-controlled YAML file (except the live-fleet sweep,
which deliberately reads the real scrapers/vendors/ directory).

Coverage:
  test_missing_file_raises_config_error       CTK-093 Q3 — bare error condition
  test_empty_file_returns_empty_dict          yaml.safe_load(...) or {} fallback
  test_present_file_returns_parsed_dict       happy path
  test_blank_entry_on_denylist_axis_raises    CTK-102 F1 — '' / normalize-blank
  test_comparator_padding_rules               CTK-102 /code-review F2-F4 fold
  test_scalar_axis_raises                     CTK-102 F3 — scalar char-iterate
  test_non_string_entry_raises                CTK-102 F4 — AttributeError class
  test_product_type_allowlist_blank_entry_allowed  CTK-102 — live-fleet exemption
  test_category_filter_non_mapping_raises     CTK-102 — block-level shape
  test_top_level_non_mapping_raises           CTK-102 — file-level shape + falsy
  test_valid_multi_axis_passes_through        CTK-102 — pass-through + null axis
  test_all_live_vendor_yamls_load_clean       CTK-102 SC-3 — canonical fleet pin
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


# ─── CTK-102 — category_filter axis shape-validation ─────────────────────────


def _expect_config_error(slug: str, vendors_dir: Path, yaml_text: str, *expect: str):
    """Write yaml_text as <slug>.yaml, load it, assert ConfigError whose
    message contains every `expect` substring (slug + axis name per the
    plan's message contract)."""
    (vendors_dir / f"{slug}.yaml").write_text(yaml_text, encoding="utf-8")
    try:
        _run_load_yaml_with_vendors_dir(slug, vendors_dir)
    except ConfigError as e:
        for fragment in expect:
            assert fragment in str(e), (
                f"ConfigError message should contain {fragment!r}; got: {e}"
            )
        return
    raise AssertionError(
        f"malformed config must raise ConfigError at load time, not pass: "
        f"{yaml_text!r}"
    )


def test_blank_entry_on_denylist_axis_raises():
    """CTK-102 F1 — an empty entry on a substring/prefix axis is
    match-everything ('' is a substring of every title; startswith('') is
    always True) → silently empty catalog. Must raise at load, naming
    vendor slug + axis. On tag_denylist the equivalent degenerate shape is
    an entry that normalizes to blank. (Whitespace-PADDED title entries are
    deliberately legal — see test_comparator_padding_rules.)"""
    with tempfile.TemporaryDirectory() as tmp:
        vendors_dir = Path(tmp) / "vendors"
        vendors_dir.mkdir()
        _expect_config_error(
            "f1-vendor", vendors_dir,
            'category_filter:\n  title_denylist:\n    - Chaeto\n    - ""\n',
            "f1-vendor", "title_denylist",
        )
        _expect_config_error(
            "f1-vendor", vendors_dir,
            'category_filter:\n  title_denylist_prefix:\n    - ""\n',
            "f1-vendor", "title_denylist_prefix",
        )
        _expect_config_error(
            "f1-vendor", vendors_dir,
            'category_filter:\n  tag_denylist:\n    - ""\n',
            "f1-vendor", "tag_denylist",
        )


def test_comparator_padding_rules():
    """CTK-102 /code-review F2-F4 fold — per-entry blank/padding rules match
    each axis's ACTUAL parse-side comparator in _should_keep:

      tag_allowlist     lowercase membership, NO strip → padded entry can
                        never match a tag → reject.
      product_type_     raw exact match → whitespace-only entry can never
      allowlist         match the empty-PT bucket ('' != ' ') → reject;
                        '' itself stays exempt (live empty-PT bucket).
      tag_denylist      _normalize_tag membership → an entry folding to ''
                        ('-', whitespace) can never match a real tag →
                        reject.
      title axes        raw-lowercase substring/prefix → padding IS
                        matchable (UC 'ARID ' trailing-space, CTK-096
                        Q-NEW-1) → NOT strip-rejected; pass-through pinned
                        in test_valid_multi_axis_passes_through."""
    with tempfile.TemporaryDirectory() as tmp:
        vendors_dir = Path(tmp) / "vendors"
        vendors_dir.mkdir()
        _expect_config_error(
            "pad-vendor", vendors_dir,
            'category_filter:\n  tag_allowlist:\n    - " Coral"\n',
            "pad-vendor", "tag_allowlist", "' Coral'",
        )
        _expect_config_error(
            "pad-vendor", vendors_dir,
            'category_filter:\n  product_type_allowlist:\n    - " "\n',
            "pad-vendor", "product_type_allowlist", "' '",
        )
        _expect_config_error(
            "pad-vendor", vendors_dir,
            'category_filter:\n  tag_denylist:\n    - "-"\n',
            "pad-vendor", "tag_denylist", "'-'",
        )


def test_scalar_axis_raises():
    """CTK-102 F3 — a scalar where a list is expected. The parse-side
    `for e in <axis>` iterates a string char-by-char (`tag_denylist: coral`
    → ['c','o','r','a','l']) — silent mis-filter, no crash. The plan's F1
    scalar shape (`product_type_allowlist: ""`) is the same class: today
    the `or []` collapse silently DISABLES the axis (equipment leaks), so
    both scalar shapes must raise at load."""
    with tempfile.TemporaryDirectory() as tmp:
        vendors_dir = Path(tmp) / "vendors"
        vendors_dir.mkdir()
        _expect_config_error(
            "f3-vendor", vendors_dir,
            "category_filter:\n  tag_denylist: coral\n",
            "f3-vendor", "tag_denylist", "'coral'",
        )
        _expect_config_error(
            "f3-vendor", vendors_dir,
            'category_filter:\n  product_type_allowlist: ""\n',
            "f3-vendor", "product_type_allowlist",
        )


def test_non_string_entry_raises():
    """CTK-102 F4 — a non-string entry (`tag_denylist: [123]`) hits
    AttributeError on .lower() mid-scrape with error_class='other' pointing
    on-call at the vendor surface; must instead raise ConfigError at load.
    A non-string scalar axis (`tag_denylist: 123`) is caught by the F3
    list-shape check. YAML bools (`- true`) are non-string entries too."""
    with tempfile.TemporaryDirectory() as tmp:
        vendors_dir = Path(tmp) / "vendors"
        vendors_dir.mkdir()
        _expect_config_error(
            "f4-vendor", vendors_dir,
            "category_filter:\n  tag_denylist:\n    - 123\n",
            "f4-vendor", "tag_denylist", "123",
        )
        _expect_config_error(
            "f4-vendor", vendors_dir,
            "category_filter:\n  tag_denylist: 123\n",
            "f4-vendor", "tag_denylist",
        )
        _expect_config_error(
            "f4-vendor", vendors_dir,
            "category_filter:\n  tag_allowlist:\n    - true\n",
            "f4-vendor", "tag_allowlist",
        )


def test_product_type_allowlist_blank_entry_allowed():
    """CTK-102 — the F1 blank-entry rejection EXEMPTS product_type_allowlist:
    '' there is an exact match against an empty product_type, a deliberate
    live shape on 5 of 11 fleet YAMLs (battlecorals / jf / poto / tsa /
    unique_corals empty-PT buckets). Rejecting it would false-positive
    half the fleet at next checkout."""
    with tempfile.TemporaryDirectory() as tmp:
        vendors_dir = Path(tmp) / "vendors"
        vendors_dir.mkdir()
        (vendors_dir / "pt-vendor.yaml").write_text(
            'category_filter:\n  product_type_allowlist:\n    - ""\n    - CORAL\n',
            encoding="utf-8",
        )
        result = _run_load_yaml_with_vendors_dir("pt-vendor", vendors_dir)
        assert result["category_filter"]["product_type_allowlist"] == ["", "CORAL"], (
            f"'' member of product_type_allowlist must pass through; got: {result!r}"
        )


def test_category_filter_non_mapping_raises():
    """CTK-102 — category_filter itself must be a mapping; a scalar/list
    there would AttributeError on the first .get at parse time."""
    with tempfile.TemporaryDirectory() as tmp:
        vendors_dir = Path(tmp) / "vendors"
        vendors_dir.mkdir()
        _expect_config_error(
            "cf-vendor", vendors_dir,
            "category_filter: coral\n",
            "cf-vendor", "category_filter", "mapping",
        )


def test_top_level_non_mapping_raises():
    """CTK-102 — a vendor YAML whose top level isn't a mapping (bare list /
    scalar) would AttributeError on the first config.get downstream with
    error_class='other'; must raise ConfigError at load instead.
    /code-review F1 fold: FALSY non-mappings ([], false) used to slip
    through the `or {}` collapse and silently pass — only None (empty file)
    coalesces now, so falsy non-mappings raise like truthy ones."""
    with tempfile.TemporaryDirectory() as tmp:
        vendors_dir = Path(tmp) / "vendors"
        vendors_dir.mkdir()
        _expect_config_error(
            "list-vendor", vendors_dir,
            "- a\n- b\n",
            "list-vendor", "top-level mapping",
        )
        _expect_config_error(
            "falsy-vendor", vendors_dir,
            "[]\n",
            "falsy-vendor", "top-level mapping",
        )
        _expect_config_error(
            "falsy-vendor", vendors_dir,
            "false\n",
            "falsy-vendor", "top-level mapping",
        )


def test_valid_multi_axis_passes_through():
    """CTK-102 pass-through — a well-formed multi-axis config parses
    unchanged. The fixture deliberately exercises the three valid-unset /
    edge shapes alongside populated axes: a present-but-null axis
    (`tag_denylist:` — /code-review F8, the `value is None` branch), an
    empty-list axis (battlecorals / jf carry one today), and the
    ARID-style padded title entry (raw substring comparator; padding legal
    per the F2-F4 comparator rules)."""
    with tempfile.TemporaryDirectory() as tmp:
        vendors_dir = Path(tmp) / "vendors"
        vendors_dir.mkdir()
        (vendors_dir / "ok-vendor.yaml").write_text(
            "slug: ok-vendor\n"
            "category_filter:\n"
            "  product_type_allowlist:\n"
            '    - ""\n'
            "    - CORAL\n"
            "  tag_allowlist:\n"
            "    - Coral\n"
            "  tag_denylist:\n"
            "  title_denylist:\n"
            "    - Chaeto\n"
            '    - "ARID "\n'
            "  title_denylist_prefix:\n"
            '    - "WS - "\n',
            encoding="utf-8",
        )
        result = _run_load_yaml_with_vendors_dir("ok-vendor", vendors_dir)
        cf = result["category_filter"]
        assert cf["product_type_allowlist"] == ["", "CORAL"]
        assert cf["tag_allowlist"] == ["Coral"]
        assert cf["tag_denylist"] is None, (
            f"present-but-null axis must pass through as None; got: "
            f"{cf['tag_denylist']!r}"
        )
        assert cf["title_denylist"] == ["Chaeto", "ARID "]
        assert cf["title_denylist_prefix"] == ["WS - "]
        # Empty-list axis is likewise valid-unset (battlecorals / jf shape).
        (vendors_dir / "ok-vendor-2.yaml").write_text(
            "category_filter:\n  tag_denylist: []\n",
            encoding="utf-8",
        )
        result2 = _run_load_yaml_with_vendors_dir("ok-vendor-2", vendors_dir)
        assert result2["category_filter"]["tag_denylist"] == []


def test_all_live_vendor_yamls_load_clean():
    """CTK-102 SC-3 — every live vendor YAML in scrapers/vendors/ loads
    clean under the new validation (no stub: real run.__file__ path
    resolution against the real repo). This is the load-bearing no-op pin:
    the loader change must not reject any current fleet config, and a
    future YAML edit that introduces a malformed axis fails HERE before it
    fails in a cron window.

    /code-review F7 fold: this glob sweep is the CANONICAL fleet-enumeration
    pin (the prior slug-list copy in test_parse_shopify_filter_axes.py is
    trimmed to defer here); it absorbs that test's slug-key assertion."""
    vendors_dir = Path(run.__file__).parent.parent / "vendors"
    yaml_files = sorted(vendors_dir.glob("*.yaml"))
    assert len(yaml_files) >= 11, (
        f"expected the 11-vendor fleet in {vendors_dir}; found {len(yaml_files)}"
    )
    for yaml_file in yaml_files:
        cfg = run._load_yaml(yaml_file.stem)  # raises ConfigError on rejection
        assert "slug" in cfg, f"{yaml_file.name} missing 'slug' field"


# ─── Test runner ──────────────────────────────────────────────────────────────
TESTS = [
    test_missing_file_raises_config_error,
    test_empty_file_returns_empty_dict,
    test_present_file_returns_parsed_dict,
    test_blank_entry_on_denylist_axis_raises,
    test_comparator_padding_rules,
    test_scalar_axis_raises,
    test_non_string_entry_raises,
    test_product_type_allowlist_blank_entry_allowed,
    test_category_filter_non_mapping_raises,
    test_top_level_non_mapping_raises,
    test_valid_multi_axis_passes_through,
    test_all_live_vendor_yamls_load_clean,
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
