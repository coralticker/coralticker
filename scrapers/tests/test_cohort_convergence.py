"""scrapers/tests/test_cohort_convergence.py — CTK-137 unit coverage for the
cohort flip-cap stateful-convergence helpers in scrapers.common.run:

  _cohort_absent_set_hash   T-2 absent-set fingerprint (membership, order-stable)
  _resolve_convergence_k    D-3 K knob: default / override / range / non-numeric
  _flip_cap_converged       D-2/D-3 convergence decision (the 8-direction proof)

The convergence decision is a PURE function: the K-1 prior absent-set hashes
are passed in as an argument (db.get_recent_cohort_absent_hashes supplies them
in production), so the whole trigger logic is testable with no DB. The migration
apply is the only DB-touching check and lives outside this suite.

The load-bearing proof (per the directive): convergence fires on a settled real
shift WITHOUT an operator AND never false-converges on a partial fetch. The 8
verify-pass scenarios below cover both directions, including the PE-class
within-page truncation gap (seen-floor) and the html_hash trap (the fingerprint
is over absent-set membership, never the schema sentinel).

No pytest dependency. Runnable as:
  python -m scrapers.tests.test_cohort_convergence
"""

from __future__ import annotations

import sys
import traceback

from scrapers.common.diff import Counters, ItemDecision
from scrapers.common.errors import ConfigError
from scrapers.common.run import (
    _apply_cohort_gate,
    _cohort_absent_set_hash,
    _flip_cap_converged,
    _resolve_convergence_k,
)


def _oos(url: str) -> ItemDecision:
    """A synthetic cohort-OOS decision shaped like diff.classify's output
    (decision='oos', product_url inside .item)."""
    return ItemDecision(item={"product_url": url}, decision="oos", existing_id=1)


def converged(
    *,
    current_hash="H",
    recent=("H", "H"),
    k=3,
    seen_not_degraded=True,
    canary_tripped=False,
    matcher_error_count=0,
    cohort_unsafe_partial=False,
    completeness_degraded=False,
    flip_cap_tripped=True,
) -> bool:
    """Convenience wrapper — defaults are the happy converge case (K=3, two
    matching prior hashes, all discriminators clear). Each test overrides one
    axis to prove it independently blocks/allows convergence."""
    return _flip_cap_converged(
        current_hash,
        list(recent),
        k,
        seen_not_degraded=seen_not_degraded,
        canary_tripped=canary_tripped,
        matcher_error_count=matcher_error_count,
        cohort_unsafe_partial=cohort_unsafe_partial,
        completeness_degraded=completeness_degraded,
        flip_cap_tripped=flip_cap_tripped,
    )


# ---------------------------------------------------------------------------
# T-2 — _cohort_absent_set_hash (fingerprint)
# ---------------------------------------------------------------------------


def test_hash_empty_is_none():
    """No cohort decisions -> None (NULL in the column); the convergence check
    treats NULL history as 'no stable run'."""
    assert _cohort_absent_set_hash([]) is None


def test_hash_is_order_independent():
    """The absent-set is a SET — the same membership in a different iteration
    order must produce the same hash (sorted before sha256)."""
    h1 = _cohort_absent_set_hash([_oos("a"), _oos("b"), _oos("c")])
    h2 = _cohort_absent_set_hash([_oos("c"), _oos("a"), _oos("b")])
    assert h1 == h2


def test_hash_differs_on_different_membership():
    """A different absent-set membership -> different hash (a growing sell-down
    never K-stabilizes). This is the property that keys convergence on
    membership, NOT on the item-count-invariant Shopify html_hash."""
    h1 = _cohort_absent_set_hash([_oos("a"), _oos("b")])
    h2 = _cohort_absent_set_hash([_oos("a"), _oos("b"), _oos("c")])
    assert h1 != h2


# ---------------------------------------------------------------------------
# D-3 — _resolve_convergence_k
# ---------------------------------------------------------------------------


def test_k_default_is_three():
    assert _resolve_convergence_k({}) == 3


def test_k_per_vendor_override():
    assert _resolve_convergence_k({"cohort_convergence_k": 2}) == 2


def test_k_blank_collapses_to_default():
    """`cohort_convergence_k:` / `: ~` / `: 0` collapse to the default via the
    `or None` coalesce — canary_floor / cohort_flip_cap parity."""
    assert _resolve_convergence_k({"cohort_convergence_k": None}) == 3
    assert _resolve_convergence_k({"cohort_convergence_k": ""}) == 3
    assert _resolve_convergence_k({"cohort_convergence_k": 0}) == 3


def test_k_out_of_range_raises_config_error():
    for bad in (-1, 100, 1000):
        raised = False
        try:
            _resolve_convergence_k({"cohort_convergence_k": bad})
        except ConfigError:
            raised = True
        assert raised, f"out-of-range cohort_convergence_k={bad} must raise ConfigError"


def test_k_non_numeric_routes_config_error():
    """SC: a non-numeric typo (cohort_convergence_k: three) routes
    error_class='config', NOT the 'other' catch-all that a bare int() would
    give (the CTK-120 #3 gap, closed for this knob)."""
    raised = False
    try:
        _resolve_convergence_k({"cohort_convergence_k": "three"})
    except ConfigError:
        raised = True
    assert raised, "non-numeric cohort_convergence_k must raise ConfigError (not ValueError)"


# ---------------------------------------------------------------------------
# The 8 verify-pass scenarios — _flip_cap_converged (both directions)
# ---------------------------------------------------------------------------


def test_1_converge_on_stable_shift():
    """K=3, identical absent-set hash across the K-1 prior runs, all
    discriminators clear, seen in-band -> converge. AND the downstream
    consequence: flip_cap_drop is False, so the gate persists the over-cap
    flips (cohort_safe True, counters.oos += absent_count)."""
    assert converged() is True
    # Downstream: a converged trip feeds flip_cap_tripped=False into the gate.
    flip_cap_tripped = True
    flip_cap_converged = converged()
    flip_cap_drop = flip_cap_tripped and not flip_cap_converged
    assert flip_cap_drop is False
    counters = Counters(seen=4589)
    oos = [_oos("a"), _oos("b"), _oos("c")]
    decisions, cohort_safe = _apply_cohort_gate(
        [], oos, counters,
        canary_tripped=False, matcher_error_count=0,
        cohort_unsafe_partial=False, completeness_degraded=False,
        flip_cap_tripped=flip_cap_drop,
    )
    assert cohort_safe is True, "converged trip must let the gate persist cohort decisions"
    assert counters.oos == 3, "converged flips must land in listings_oos"
    assert len(decisions) == 3


def test_2_k_boundary_off_by_one():
    """Pins the off-by-one. K=3 needs K-1=2 matching prior hashes. With only 1
    prior (run K-1) -> no convergence; with 2 (run K) -> converge."""
    assert converged(recent=("H",)) is False        # one short of K-1
    assert converged(recent=("H", "H")) is True      # exactly K-1


def test_3_no_converge_on_unstable_set():
    """Growing sell-down (D-1 active-sale case): the prior hashes differ from
    the current -> never K-stable -> no convergence at any run."""
    assert converged(current_hash="H3", recent=("H2", "H1")) is False
    assert converged(current_hash="H", recent=("H", "G")) is False


def test_4_no_converge_on_page_incomplete():
    """K stable-hash runs but completeness_degraded=True (a never-fetched page
    inflated the absent-set) -> no convergence; decisions stay dropped."""
    assert converged(completeness_degraded=True) is False


def test_5_no_converge_on_within_page_truncation():
    """The PE-class gap: page count complete (completeness_degraded False) but
    listings_seen below SEEN_FLOOR x median -> seen_not_degraded False -> no
    convergence. Caught here for large within-page truncations."""
    assert converged(seen_not_degraded=False) is False


def test_6_no_converge_on_canary_or_matcher():
    """A real failure signal is never overridden by convergence."""
    assert converged(canary_tripped=True) is False
    assert converged(matcher_error_count=1) is False
    assert converged(cohort_unsafe_partial=True) is False


def test_7_self_terminating():
    """After a convergence persists, the next run's absent-set is empty (None
    hash) or changed -> differs from the prior stable hash -> no re-converge."""
    assert converged(current_hash=None) is False               # emptied set
    assert converged(current_hash="NEW", recent=("OLD", "OLD")) is False  # changed set


def test_8_null_history_safety():
    """Pre-CTK-137 (NULL hash) or failed-fetch rows in the lookback are
    returned as None -> never equal the current hash -> no convergence off a
    NULL. A clean/converged run between trips also resets the chain this way."""
    assert converged(recent=("H", None)) is False
    assert converged(recent=(None, None)) is False


def test_not_tripped_never_converges():
    """Convergence is a flip_cap escape valve only — it never fires when the
    cap didn't trip."""
    assert converged(flip_cap_tripped=False) is False


def test_k1_converges_immediately_when_clear():
    """K=1 (needed=0 prior hashes) converges on the first stable trip with the
    discriminators clear — the documented operator-chosen aggressive setting."""
    assert converged(k=1, recent=()) is True
    # still gated by the discriminators even at K=1
    assert converged(k=1, recent=(), completeness_degraded=True) is False


if __name__ == "__main__":
    tests = [
        test_hash_empty_is_none,
        test_hash_is_order_independent,
        test_hash_differs_on_different_membership,
        test_k_default_is_three,
        test_k_per_vendor_override,
        test_k_blank_collapses_to_default,
        test_k_out_of_range_raises_config_error,
        test_k_non_numeric_routes_config_error,
        test_1_converge_on_stable_shift,
        test_2_k_boundary_off_by_one,
        test_3_no_converge_on_unstable_set,
        test_4_no_converge_on_page_incomplete,
        test_5_no_converge_on_within_page_truncation,
        test_6_no_converge_on_canary_or_matcher,
        test_7_self_terminating,
        test_8_null_history_safety,
        test_not_tripped_never_converges,
        test_k1_converges_immediately_when_clear,
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
