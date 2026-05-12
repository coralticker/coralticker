"""CTK-039 failure-mode smoke (Acceptance #7) — DO NOT MERGE.

Deliberate failing assert validates that CI renders RED (not green-with-skip)
when a no-DB test fails. The branch + PR carrying this file are throwaway;
revert via `gh pr close --delete-branch` after smoke completes.

Smoke covers two false-green surfaces the --collect-only count assertion
alone doesn't catch:
  - GH Actions UI rendering pytest exit code 1 as a red job (not green +
    "tests skipped" green-tinted state)
  - Marker filter `-m "not requires_db"` not silently swallowing failures
    that lack the requires_db marker
"""

from __future__ import annotations


def test_ctk039_smoke_intentional_fail():
    """Smoke. Asserts 1 == 2 to force CI red. Remove this entire file before
    closing the smoke PR; do not let this commit reach main."""
    assert 1 == 2, "CTK-039 smoke: deliberate failure to test CI red-rendering"
