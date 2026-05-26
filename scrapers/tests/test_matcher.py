"""scrapers/tests/test_matcher.py — cascade smoke + cat-2 guard + cache-load
failure path + trigram-similarity sanity.

Runnable as: python -m scrapers.tests.test_matcher
or          python scrapers/tests/test_matcher.py

No pytest dependency — uses plain `assert`. Fail-fast on first regression
within a test; run-all + summary at end. Synthetic fixtures only; no DB
connection; no hosted-Supabase touch.

Coverage per /lead-review CTK-025 strategic-pass §F1 + /lead-backend
review-results CTK-025 Session 1 sweep §F-C — extends the inline cascade
smoke from Session 1 to durable on-disk evidence:

  Stage 1 canonical-exact                                 (Session 1 carry)
  Stage 2 canonical-prefix                                (CTK-025 Session 2 ← Fold 3)
  Stage 2 sub-prefix collision (longest-name-first sort)  (CTK-025 Session 2 ← Fold 3)
  Stage 3 canonical-implicit-prefix                       (Session 1 carry)
  Stage 4 alias auto-link                                 (CTK-025 Session 2 ← Fold 3)
  Stage 4 cat-2 bypass + canonical-stage scope guard      (CTK-030 v1 B3 Path A fold)
  Stage 5 cluster flag-review                             (CTK-025 Session 2 ← Fold 3)
  Stage 6 fuzzy fallback (sub-threshold returns null)     (Session 1 carry)
  Stage 7 no match (empty cache + unrelated listing)      (Session 1 carry)
  Category-2 guard reject + pass                          (Session 1 carry)
  load_match_cache exception propagates (NOT fail-soft)   (CTK-025 Session 2 ← Fold 3)
  Trigram similarity sanity (identical / disjoint / empty)
"""

from __future__ import annotations

import sys

import psycopg

from scrapers.common import matcher
from scrapers.common.matcher import (
    Alias,
    MatchCache,
    MatchResult,
    NamedCoral,
    load_match_cache,
    match_listing,
)


# ─── Stage 1: canonical-exact ─────────────────────────────────────────────────
def test_stage_1_canonical_exact():
    nc = NamedCoral(
        id=42, canonical_name="WWC Dragon Soul Torch",
        normalized_name="wwc dragon soul torch",
        requires_vendor_prefix=False, category=1,
    )
    cache = MatchCache(
        named_corals=[nc],
        canonical_index={nc.normalized_name: nc},
        nc_by_id={nc.id: nc},
    )
    result = match_listing(cache, "wwc dragon soul torch")
    assert result.named_coral_id == 42
    assert result.match_confidence == "exact"
    assert result.match_method == "canonical-exact"
    assert result.matched_at is not None


# ─── Stage 2: canonical-prefix ────────────────────────────────────────────────
def test_stage_2_canonical_prefix_match():
    """Listing 'wwc dragon soul torch ultra-rare wysiwyg' starts with the
    canonical 'wwc dragon soul torch ' — stage 2 hit."""
    nc = NamedCoral(
        id=43, canonical_name="WWC Dragon Soul Torch",
        normalized_name="wwc dragon soul torch",
        requires_vendor_prefix=False, category=1,
    )
    cache = MatchCache(
        named_corals=[nc],
        canonical_index={nc.normalized_name: nc},
        nc_by_id={nc.id: nc},
    )
    result = match_listing(cache, "wwc dragon soul torch ultra-rare wysiwyg")
    assert result.named_coral_id == 43
    assert result.match_confidence == "exact"
    assert result.match_method == "canonical-prefix"


def test_stage_2_canonical_prefix_miss_short_listing():
    """Listing 'wwc dragon' is not a prefix-match for 'wwc dragon soul torch '
    (the canonical-name + space wouldn't fit as a prefix). Falls through to
    stage 3-7; no hit; null return."""
    nc = NamedCoral(
        id=43, canonical_name="WWC Dragon Soul Torch",
        normalized_name="wwc dragon soul torch",
        requires_vendor_prefix=False, category=1,
    )
    cache = MatchCache(
        named_corals=[nc],
        canonical_index={nc.normalized_name: nc},
        nc_by_id={nc.id: nc},
    )
    result = match_listing(cache, "wwc dragon")
    assert result.named_coral_id is None
    assert result.match_method is None


def test_stage_2_longest_first_sub_prefix_disambiguation():
    """When two named_corals share a prefix path, the longer name wins at
    stage 2 — prevents the shorter sub-prefix from claiming the listing.
    matcher.py:214 sorts longest-name-first explicitly for this reason."""
    nc_short = NamedCoral(
        id=10, canonical_name="WWC Dragon",
        normalized_name="wwc dragon",
        requires_vendor_prefix=False, category=1,
    )
    nc_long = NamedCoral(
        id=20, canonical_name="WWC Dragon Soul Torch",
        normalized_name="wwc dragon soul torch",
        requires_vendor_prefix=False, category=1,
    )
    cache = MatchCache(
        named_corals=[nc_short, nc_long],
        canonical_index={
            nc_short.normalized_name: nc_short,
            nc_long.normalized_name: nc_long,
        },
        nc_by_id={nc_short.id: nc_short, nc_long.id: nc_long},
    )
    result = match_listing(cache, "wwc dragon soul torch ultra-rare wysiwyg")
    assert result.named_coral_id == 20, (
        f"longest-name-first should pick id=20 over id=10; got {result.named_coral_id}"
    )
    assert result.match_method == "canonical-prefix"


# ─── Stage 3: canonical-implicit-prefix (originator-prefix synthesis) ─────────
def test_stage_3_implicit_prefix_canonical_exact():
    """WWC's 'Dragon Soul Torch' (no prefix) + originator_prefix='wwc'
    synthesizes 'wwc dragon soul torch' → matches canonical-exact at the
    synthesized layer."""
    nc = NamedCoral(
        id=42, canonical_name="WWC Dragon Soul Torch",
        normalized_name="wwc dragon soul torch",
        requires_vendor_prefix=False, category=1,
    )
    cache = MatchCache(
        named_corals=[nc],
        canonical_index={nc.normalized_name: nc},
        nc_by_id={nc.id: nc},
    )
    result = match_listing(cache, "dragon soul torch", originator_prefix="wwc")
    assert result.named_coral_id == 42
    assert result.match_method == "canonical-implicit-prefix"


def test_stage_3_implicit_prefix_skip_when_no_originator():
    """Without originator_prefix, stage 3 is a no-op. Asserts via match_method
    that stage 3 did not fire — downstream stages (4-6) may still match the
    listing through other pathways (e.g. fuzzy similarity); the test isolates
    stage 3 behavior by checking the trace string."""
    nc = NamedCoral(
        id=42, canonical_name="WWC Dragon Soul Torch",
        normalized_name="wwc dragon soul torch",
        requires_vendor_prefix=False, category=1,
    )
    cache = MatchCache(
        named_corals=[nc],
        canonical_index={nc.normalized_name: nc},
        nc_by_id={nc.id: nc},
    )
    result = match_listing(cache, "dragon soul torch", originator_prefix=None)
    assert result.match_method != "canonical-implicit-prefix", (
        f"stage 3 must be skipped without originator_prefix; got method={result.match_method}"
    )


# ─── Stage 4: alias auto-link ─────────────────────────────────────────────────
def test_stage_4_alias_auto_link_match():
    """Alias text 'hypnotic aussie lord' substring-matches the listing →
    auto-link to named_coral_id=42 with match_confidence='alias'."""
    nc = NamedCoral(
        id=42, canonical_name="WWC Hypnotic Aussie Lord",
        normalized_name="wwc hypnotic aussie lord",
        requires_vendor_prefix=False, category=1,
    )
    al = Alias(
        alias_text="hypnotic aussie lord",
        named_coral_id=42,
        cluster_label=None,
        match_behavior="auto-link",
    )
    cache = MatchCache(
        named_corals=[nc],
        canonical_index={nc.normalized_name: nc},
        nc_by_id={nc.id: nc},
        auto_link_aliases=[al],
    )
    result = match_listing(cache, "hypnotic aussie lord wysiwyg")
    assert result.named_coral_id == 42
    assert result.match_confidence == "alias"
    assert result.match_method == "alias-hit"


def test_stage_4_alias_auto_link_miss_no_alias_text():
    """Listing without alias substring falls through to stages 5/6/7."""
    nc = NamedCoral(
        id=42, canonical_name="WWC Hypnotic Aussie Lord",
        normalized_name="wwc hypnotic aussie lord",
        requires_vendor_prefix=False, category=1,
    )
    al = Alias(
        alias_text="hypnotic aussie lord",
        named_coral_id=42,
        cluster_label=None,
        match_behavior="auto-link",
    )
    cache = MatchCache(
        named_corals=[nc],
        canonical_index={nc.normalized_name: nc},
        nc_by_id={nc.id: nc},
        auto_link_aliases=[al],
    )
    result = match_listing(cache, "pacific east acanthophyllia")
    assert result.named_coral_id is None
    assert result.match_method is None


# ─── Stage 4 cat-2 bypass — CTK-030 v1 B3 Path A ─────────────────────────────
def test_stage_4_alias_bypasses_cat2_guard():
    """Per /lead-architect ruling 2026-05-25 (CTK-030 v1 B3 Q-A): stage-4
    auto-link bypasses the cat-2 guard. An explicit alias row is the
    curator-vetted disambiguation; gating it on requires_vendor_prefix
    defeated the cross-vendor matching the seed was curated for.

    Regression-discriminator for the matcher edit at matcher.py stage-4
    loop. Pre-edit: this case returned None (the guard demoted the hit
    because 'hellfire torch' doesn't start with 'wwc '). Post-edit:
    returns the named_coral_id via alias-hit. A future refactor that
    re-introduces the guard at stage 4 fails here first.

    Mirrors the live CTK-030 prod case: bare 'hellfire torch' (a
    documented rebrand of the WWC Dragon Soul Torch lineage per
    `.claude/research/named-coral-launch-seed.md`) listed at any vendor
    matches named_coral_id=3 via alias-hit."""
    nc = NamedCoral(
        id=3, canonical_name="WWC Dragon Soul Torch",
        normalized_name="wwc dragon soul torch",
        requires_vendor_prefix=True, category=1,
    )
    al = Alias(
        alias_text="hellfire torch",
        named_coral_id=3,
        cluster_label=None,
        match_behavior="auto-link",
    )
    cache = MatchCache(
        named_corals=[nc],
        canonical_index={nc.normalized_name: nc},
        nc_by_id={nc.id: nc},
        auto_link_aliases=[al],
    )
    result = match_listing(cache, "hellfire torch wysiwyg")
    assert result.named_coral_id == 3, (
        f"stage-4 cat-2 bypass should hit nc.id=3; got id={result.named_coral_id} "
        f"method={result.match_method}"
    )
    assert result.match_confidence == "alias"
    assert result.match_method == "alias-hit"


def test_stage_4_bypass_does_not_leak_to_canonical_stages():
    """Bypass is scoped to stage 4 only — stages 1/2/3/6 still apply the
    cat-2 guard per /lead-architect ruling 2026-05-25. Same cat-2 nc
    with an alias present in the cache, but the listing matches the
    canonical-name pattern (bare 'dragon soul torch', no 'wwc ' prefix)
    rather than the alias. Stage 4 doesn't fire (no alias substring
    match); stages 2/3/6 all still guard against the missing prefix.
    Discriminates accidental widening of the bypass into other cascade
    stages."""
    nc = NamedCoral(
        id=3, canonical_name="WWC Dragon Soul Torch",
        normalized_name="wwc dragon soul torch",
        requires_vendor_prefix=True, category=1,
    )
    al = Alias(
        alias_text="hellfire torch",  # present but does NOT match the listing under test
        named_coral_id=3,
        cluster_label=None,
        match_behavior="auto-link",
    )
    cache = MatchCache(
        named_corals=[nc],
        canonical_index={nc.normalized_name: nc},
        nc_by_id={nc.id: nc},
        auto_link_aliases=[al],
    )
    result = match_listing(cache, "dragon soul torch wysiwyg")
    assert result.named_coral_id is None, (
        f"stage-4 bypass must NOT widen to canonical stages; got id={result.named_coral_id} "
        f"method={result.match_method}"
    )


# ─── Stage 5: cluster flag-review ─────────────────────────────────────────────
def test_stage_5_cluster_flag_review():
    """Cluster alias 'homewrecker' substring-matches → returns
    MatchResult(named_coral_id=None, match_confidence='manual',
    match_method='cluster:holy_grail_torch'). No named_coral_id set;
    routes to admin queue per arch §3.4 stage 5 + §3.7."""
    al = Alias(
        alias_text="homewrecker",
        named_coral_id=None,
        cluster_label="holy_grail_torch",
        match_behavior="flag-review",
    )
    cache = MatchCache(flag_review_aliases=[al])
    result = match_listing(cache, "homewrecker frag wysiwyg")
    assert result.named_coral_id is None, (
        "cluster flag must NOT auto-link to a named_coral_id"
    )
    assert result.match_confidence == "manual"
    assert result.match_method == "cluster:holy_grail_torch"
    assert result.matched_at is not None, (
        "cluster hit should still set matched_at (notifier filters out via "
        "named_coral_id IS NOT NULL)"
    )


# ─── Stage 6: fuzzy fallback ──────────────────────────────────────────────────
def test_stage_6_fuzzy_below_threshold():
    """At PG_TRGM_BASE_THRESHOLD=0.7, 'wwc dragon souls torches' vs
    'wwc dragon soul torch' Jaccard sim is ~0.679 — below threshold,
    returns null. F3 anti-scope-creep: do not tune to 0.65 in CTK-025;
    calibration is CTK-002."""
    nc = NamedCoral(
        id=42, canonical_name="WWC Dragon Soul Torch",
        normalized_name="wwc dragon soul torch",
        requires_vendor_prefix=False, category=1,
    )
    cache = MatchCache(
        named_corals=[nc],
        canonical_index={nc.normalized_name: nc},
        nc_by_id={nc.id: nc},
    )
    result = match_listing(cache, "wwc dragon souls torches", originator_prefix="wwc")
    assert result.named_coral_id is None


# ─── Stage 7: no match ────────────────────────────────────────────────────────
def test_stage_7_no_match_empty_cache():
    """Empty cache (Phase 1 pre-seed expected state) returns null fields
    end-to-end. Same code path as populated-but-no-hit cache."""
    result = match_listing(MatchCache(), "wwc dragon soul torch", originator_prefix="wwc")
    assert result == MatchResult(None, None, None, None)


def test_stage_7_no_match_unrelated_listing():
    nc = NamedCoral(
        id=42, canonical_name="WWC Dragon Soul Torch",
        normalized_name="wwc dragon soul torch",
        requires_vendor_prefix=False, category=1,
    )
    cache = MatchCache(
        named_corals=[nc],
        canonical_index={nc.normalized_name: nc},
        nc_by_id={nc.id: nc},
    )
    result = match_listing(cache, "pacific east acanthophyllia")
    assert result == MatchResult(None, None, None, None)


# ─── Category-2 guard ─────────────────────────────────────────────────────────
def test_cat2_guard_rejects_bare_title():
    """Category-2 'UC Miyagi Tort' rejects bare 'miyagi tort' — falls
    through (no implicit prefix to save it; the guard's required prefix
    is canonical_name's first word, lowercased = 'uc')."""
    nc = NamedCoral(
        id=99, canonical_name="UC Miyagi Tort",
        normalized_name="uc miyagi tort",
        requires_vendor_prefix=True, category=2,
    )
    cache = MatchCache(
        named_corals=[nc],
        canonical_index={nc.normalized_name: nc},
        nc_by_id={nc.id: nc},
    )
    result = match_listing(cache, "miyagi tort")
    assert result.named_coral_id is None


def test_cat2_guard_passes_with_prefix():
    nc = NamedCoral(
        id=99, canonical_name="UC Miyagi Tort",
        normalized_name="uc miyagi tort",
        requires_vendor_prefix=True, category=2,
    )
    cache = MatchCache(
        named_corals=[nc],
        canonical_index={nc.normalized_name: nc},
        nc_by_id={nc.id: nc},
    )
    result = match_listing(cache, "uc miyagi tort")
    assert result.named_coral_id == 99
    assert result.match_method == "canonical-exact"


# ─── load_match_cache exception propagation ──────────────────────────────────
def test_load_match_cache_propagates_exception():
    """Per arch §3.2 + F4 contract documented in matcher.py module docstring:
    cache-load failure is a connectivity issue, NOT a per-listing matcher
    exception. load_match_cache MUST propagate exceptions to the orchestrator
    rather than wrapping in fail-soft. The orchestrator's stage-2-prerequisite
    error path then surfaces a clean failure with error_class='other' and
    halts the scrape.

    CTK-045 Session 1 2026-05-18: _FailingClient mock reshaped from supabase-py
    PostgREST surface to psycopg's cursor.execute path. psycopg.Error matches
    production failure mode (Neon connectivity drops surface as
    psycopg.OperationalError, subclass of psycopg.Error)."""

    class _FailingCursor:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, *a, **k):
            raise psycopg.Error("synthetic Neon connectivity failure")

    class _FailingConn:
        def cursor(self):
            return _FailingCursor()

    raised = False
    try:
        load_match_cache(_FailingConn())
    except psycopg.Error as e:
        raised = True
        assert "synthetic Neon connectivity failure" in str(e)
    assert raised, (
        "load_match_cache must propagate connectivity exceptions, not swallow them. "
        "Per F4 contract: fail-soft applies per-listing in match_listing(), NOT to cache-load."
    )


# ─── Trigram similarity sanity ────────────────────────────────────────────────
# CTK-063 Session 1 commit 3: _trigram_similarity now consumes pre-computed
# trigram sets (built once per scrape via _trigrams + cached on NamedCoral.trigrams).
# Wrap with _trigrams() at the call site; the Jaccard semantics under test are
# unchanged.
def test_trigram_similarity_identical():
    assert matcher._trigram_similarity(
        matcher._trigrams("wwc dragon"), matcher._trigrams("wwc dragon"),
    ) == 1.0


def test_trigram_similarity_disjoint():
    sim = matcher._trigram_similarity(
        matcher._trigrams("wwc dragon"), matcher._trigrams("pacific east"),
    )
    assert sim < 0.2, f"disjoint strings should have low similarity; got {sim}"


def test_trigram_similarity_empty_strings():
    assert matcher._trigram_similarity(
        matcher._trigrams(""), matcher._trigrams(""),
    ) == 0.0
    assert matcher._trigram_similarity(
        matcher._trigrams("wwc"), matcher._trigrams(""),
    ) == 0.0


# ─── Test runner ──────────────────────────────────────────────────────────────
TESTS = [
    test_stage_1_canonical_exact,
    test_stage_2_canonical_prefix_match,
    test_stage_2_canonical_prefix_miss_short_listing,
    test_stage_2_longest_first_sub_prefix_disambiguation,
    test_stage_3_implicit_prefix_canonical_exact,
    test_stage_3_implicit_prefix_skip_when_no_originator,
    test_stage_4_alias_auto_link_match,
    test_stage_4_alias_auto_link_miss_no_alias_text,
    test_stage_4_alias_bypasses_cat2_guard,
    test_stage_4_bypass_does_not_leak_to_canonical_stages,
    test_stage_5_cluster_flag_review,
    test_stage_6_fuzzy_below_threshold,
    test_stage_7_no_match_empty_cache,
    test_stage_7_no_match_unrelated_listing,
    test_cat2_guard_rejects_bare_title,
    test_cat2_guard_passes_with_prefix,
    test_load_match_cache_propagates_exception,
    test_trigram_similarity_identical,
    test_trigram_similarity_disjoint,
    test_trigram_similarity_empty_strings,
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
        except Exception as e:  # noqa: BLE001 — surface the unexpected exception type
            print(f"  ERROR {fn.__name__}: {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed (total {len(TESTS)})")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
