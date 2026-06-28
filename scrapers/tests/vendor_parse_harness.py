"""scrapers/tests/vendor_parse_harness.py — CTK-208: shared scaffolding for the
per-vendor Shopify parse-test suites.

Every vendor parse-test repeated the same scaffolding: _load_fixture, the
_tag_denylist_norm / _keep / _normalize production-call wrappers, _by_title, the
`try: import pytest` fixture shim, the script-mode main() runner, and the two common
tests (the html_hash first-product-keys sentinel + the CTK-115 yaml_mirror_parity
drift guard). Only the bespoke regressions (EXPECTED_KEPT, DROPPED_TITLES, the
survival/coverage tests) differed. This module holds the shared half so a NEW vendor
test reduces to: a VendorParseConfig + the fixture + that vendor's own regressions.

A migrated vendor file:
    from scrapers.tests.vendor_parse_harness import (
        VendorParseConfig, load_fixture, make_keep, make_normalize, by_title,
        check_html_hash_first_product_keys, check_yaml_mirror_parity, run_main,
    )
    CONFIG = VendorParseConfig(...)
    _keep = make_keep(CONFIG)
    _normalize = make_normalize(CONFIG)
    # `products` fixture + the two common test wrappers + bespoke regressions below.

GUARD (CTK-208 directive #2): the parameterized yaml_mirror_parity reads the expected
category_filter key-set AND the expected-absent axis keys from the per-vendor config —
nothing RUTR/no-allowlist-specific is hardcoded here. A future vendor WITH a real
product_type_allowlist adopts this harness by setting expected_filter_keys /
expected_absent_axes on its CONFIG; it never edits this file.
"""

from __future__ import annotations

import hashlib
import json
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

import yaml

from scrapers.common.parse_shopify import (
    _normalize_product,
    _normalize_tag,
    _should_keep,
)


@dataclass(frozen=True)
class VendorParseConfig:
    """Per-vendor parse-test configuration. The bespoke regressions live in the
    vendor file; everything the shared scaffolding needs lives here."""

    fixture_path: Path
    yaml_path: Path
    base_url: str
    image_strategy: str
    originator_prefix: str | None
    auction_detection: dict | None
    # The category_filter the test models — kept byte-exact with the vendor YAML;
    # also the source the _keep wrapper feeds _should_keep.
    category_filter: dict
    in_stock_only: bool = False
    # html_hash sentinel (arch §2.6 Shopify first-product-keys anchor).
    expected_first_product_keys: list[str] = field(default_factory=list)
    html_hash_sentinel: str = ""
    # yaml_mirror_parity (CTK-115) — per-vendor, NOT hardcoded:
    #   expected_filter_keys : the exact key-set the YAML category_filter must carry.
    #   expected_absent_axes : axes that must NOT appear (e.g. a no-allowlist vendor
    #                          lists {"product_type_allowlist","tag_allowlist"}; an
    #                          allowlist vendor lists a smaller/empty set).
    expected_filter_keys: frozenset[str] = frozenset()
    expected_absent_axes: frozenset[str] = frozenset()
    expect_in_stock_only_absent: bool = True
    expect_auction_detection_none: bool = True


def load_fixture(config: VendorParseConfig) -> list[dict]:
    with config.fixture_path.open("r", encoding="utf-8") as f:
        return json.load(f)["products"]


def tag_denylist_norm(config: VendorParseConfig) -> set[str]:
    """Mirror the production hoist in fetch_and_parse: normalize the YAML
    tag_denylist into the set _should_keep consumes. Empty for the no-tag_denylist
    vendors — the tag axis is structurally inert there. Kept for production-call
    parity."""
    return {_normalize_tag(e) for e in (config.category_filter.get("tag_denylist") or [])}


def make_keep(config: VendorParseConfig) -> Callable[[dict], bool]:
    """Return the _keep wrapper — _should_keep called exactly as production does:
    category_filter + in_stock_only + the normalized tag_denylist.

    Tripwire (CTK-208 /code-review): _should_keep has no auction-override path today,
    so a config with auction_detection set would compute a keep-count this wrapper
    can't make match production once a _should_keep_with_auction_override path is wired.
    Fail loudly here rather than let a future auction vendor's count silently diverge."""
    assert config.auction_detection is None, (
        "make_keep does not model auction_detection — _should_keep has no auction "
        "override path yet. Wire that path + update this wrapper before adopting the "
        "harness for an auction vendor (config.auction_detection must be None for now)."
    )

    def _keep(p: dict) -> bool:
        return _should_keep(p, config.category_filter, config.in_stock_only,
                            tag_denylist_norm(config))
    return _keep


def make_normalize(config: VendorParseConfig) -> Callable[[dict], dict]:
    """Return the _normalize wrapper — _normalize_product with the vendor's
    base_url / image_strategy / originator_prefix / auction_detection."""
    def _normalize(p: dict) -> dict:
        return _normalize_product(
            p, config.base_url, config.image_strategy,
            config.originator_prefix, config.auction_detection,
        )
    return _normalize


def by_title(products: list[dict], title: str) -> dict:
    for p in products:
        if p["title"] == title:
            return p
    raise KeyError(f"fixture missing product titled {title!r}")


# ── Common test 1: html_hash sentinel (arch §2.6 Shopify variant) ────────────
def check_html_hash_first_product_keys(products: list[dict], config: VendorParseConfig) -> None:
    """Hash the sorted key set of the first product. Sentinel flips only when keys
    add/remove. Parameterized on config.expected_first_product_keys + sentinel."""
    first = products[0]
    keys = sorted(first.keys())
    assert keys == config.expected_first_product_keys, (
        f"first-product key set drift — expected {config.expected_first_product_keys}, got {keys}"
    )
    sha = hashlib.sha256(",".join(keys).encode("utf-8")).hexdigest()
    assert sha == config.html_hash_sentinel, (
        f"first-product-keys html_hash sentinel drift — got {sha}"
    )


# ── Common test 2: yaml_mirror_parity (CTK-115 drift guard) ──────────────────
def check_yaml_mirror_parity(config: VendorParseConfig) -> None:
    """The in-test category_filter must equal the vendor YAML byte-exact, the YAML's
    filter-axis key-set must equal config.expected_filter_keys, every axis in
    config.expected_absent_axes must be absent, and (when configured) in_stock_only
    must be absent + auction_detection None.

    The key-set assertion is load-bearing: the test models exactly the axes in
    config.category_filter with config.in_stock_only. If a maintainer adds an axis
    the config doesn't model, the locked-fixture keep count would no longer reflect
    production and the suite would stay green against diverged behavior — so this
    fails loudly the moment the YAML's axis-set drifts."""
    cfg = yaml.safe_load(config.yaml_path.read_text(encoding="utf-8"))
    yaml_filter = cfg["category_filter"]

    for key, want in config.category_filter.items():
        assert yaml_filter.get(key) == want, (
            f"{key} drift between {config.yaml_path.name} and the test mirror"
        )
    assert set(yaml_filter.keys()) == set(config.expected_filter_keys), (
        f"{config.yaml_path.name} category_filter grew/changed an axis the test mirror "
        f"doesn't model: YAML={sorted(yaml_filter.keys())} vs "
        f"expected={sorted(config.expected_filter_keys)} — extend the CONFIG + the bespoke tests"
    )
    for axis in config.expected_absent_axes:
        assert axis not in yaml_filter, (
            f"{config.yaml_path.name} grew a {axis} the CONFIG declares must be absent — "
            f"re-walk + re-decide before adopting it (it can silently change the catalog)"
        )
    if config.expect_in_stock_only_absent:
        assert "in_stock_only" not in cfg, (
            f"{config.yaml_path.name} set in_stock_only — the _keep wrapper uses "
            f"config.in_stock_only={config.in_stock_only}; thread it through the CONFIG"
        )
    if config.expect_auction_detection_none:
        assert cfg.get("auction_detection") is None, (
            f"{config.yaml_path.name} grew an auction_detection block — INV-05 disposition "
            f"changed; re-confirm the walk + update the CONFIG"
        )


def run_main(config: VendorParseConfig, tests: Iterable[Callable],
             no_param: Iterable[Callable] = ()) -> int:
    """Script-mode runner (`python -m scrapers.tests.test_<vendor>_parse`). Prints
    PASS/FAIL per test + an n/N summary; returns 1 on any failure. `no_param` tests
    are called with no args (e.g. yaml_mirror_parity); the rest get `products`."""
    products = load_fixture(config)
    no_param_set = set(no_param)
    tests = list(tests)
    failed = 0
    for t in tests:
        try:
            t() if t in no_param_set else t(products)
            print(f"PASS  {t.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL  {t.__name__}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0
