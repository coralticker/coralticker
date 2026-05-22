"""Named-coral matcher — arch §3.2 + §3.4 + §3.5 + §3.10 (CTK-025).

Inline, in-memory matcher run between scrape stages 5 (Diff) and 6a (Phase A
persist). Loads active `named_corals` + `aliases` once per scrape; each
listing's match is a pure Python operation (no per-listing DB queries per
arch §3.2). Exception path is fail-soft — the orchestrator catches and
records null match fields + appends to scraper_runs.error_message;
status='partial'; scrape continues.

Public API:
    load_match_cache(client) -> MatchCache
    match_listing(cache, normalized_title, originator_prefix) -> MatchResult

Cascade (arch §3.4, first hit wins):
    1. canonical-exact         normalized_title == nc.normalized_name
    2. canonical-prefix        normalized_title startswith nc.normalized_name + ' '
    3. canonical-implicit-prefix  with vendor's originator_prefix synthesized
    4. alias-hit               alias_text in normalized_title; auto-link
    5. cluster:<label>         alias_text in normalized_title; flag-review
                               (named_coral_id=null, match_confidence='manual')
    6. fuzzy-0.NN              pg_trgm-equivalent (trigram Jaccard) >= 0.7
    7. null                    no match

Category-2 guard (arch §3.5) applies at every stage that returns a
named_coral_id (stages 1, 2, 3, 4, 6). Stage 5 (cluster) returns null
named_coral_id so no guard is needed there. Guard rejects matches whose
title does not start with the implied prefix (canonical_name's first word,
lowercased) — "Miyagi Tort" without "UC " falls through to the next stage
rather than auto-linking.

============================================================================
F3 fold (CTK-025 lead-review-2026-05-04-pre-implementation §F3) —
calibration knobs that ship with default values; do NOT tune in CTK-025.
Calibration is CTK-002 (Phase 3 gate).
    (i)   PG_TRGM_BASE_THRESHOLD = 0.7   (arch §3.4 stage 6)
    (ii)  PG_TRGM_TIE_BREAKER_MARGIN = 0.05  (arch §3.4 stage 6 tie-breaker)
    (iii) §3.10 first lever on FP breach: raise PG_TRGM_BASE_THRESHOLD to 0.75
          — DO NOT pre-apply; logged here as the calibration-time lever only.
    (iv)  Cluster-flag confidence assignment is fixed at match_confidence='manual'
          + named_coral_id=null per arch §3.4 stage 5; not a tunable knob.

If a build-time edge case suggests bumping any of (i)-(iii), the right move
is to file a CTK-002 calibration note, not to edit this file.
============================================================================

============================================================================
F4 fold (CTK-025 lead-review-2026-05-04-pre-implementation §F4) — cache
load timing contract.

load_match_cache(client) is called by run.py AFTER stage 1 (Config) and
BEFORE stage 2 (Fetch). Rationale:
    (a) Supabase client is established in stage 1; loading the cache there
        means the load itself participates in the 60-min workflow timeout
        boundary.
    (b) Cache-load failure surfaces as a clean stage-2-prerequisite error
        — same code path as a pre-fetch DB connectivity issue.
    (c) Empty-cache no-op (Phase 1: seed not loaded yet) is the same code
        path as a populated-cache (Phase 3+); test coverage is uniform
        across pre-seed and post-seed states.

Loading later (just before stage 5) saves a few seconds on scrapes that
have no decisions, but the special case isn't worth it.
============================================================================
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

import psycopg

log = logging.getLogger(__name__)


# F3 calibration knobs — default values, do NOT tune in CTK-025.
PG_TRGM_BASE_THRESHOLD = 0.7
PG_TRGM_TIE_BREAKER_MARGIN = 0.05


@dataclass
class NamedCoral:
    id: int
    canonical_name: str
    normalized_name: str
    requires_vendor_prefix: bool
    category: int  # 1 (stable lineage) or 2 (semi-stable, requires vendor prefix)
    trigrams: set[str] = field(default_factory=set)  # pre-computed at load_match_cache; consumed by stage-6 trigram Jaccard


@dataclass
class Alias:
    alias_text: str  # already normalized at seed time per arch §3.3 discipline
    named_coral_id: int | None
    cluster_label: str | None
    match_behavior: str  # 'auto-link' or 'flag-review'


@dataclass
class MatchCache:
    """In-memory snapshot loaded once per scrape per arch §3.2.

    canonical_index keys on normalized_name for O(1) stage-1 lookup.
    auto_link_aliases / flag_review_aliases pre-bucketed for stage 4 / 5
    iteration without per-stage filter overhead.
    nc_by_id supports stage-4 alias->named_coral resolution for the
    category-2 guard application.
    named_corals_by_length_desc is the named_corals list pre-sorted by
    -len(normalized_name) so stages 2 + 3 iterate longest-name-first
    (sub-prefix-collision avoidance) without a per-listing re-sort.
    """
    named_corals: list[NamedCoral] = field(default_factory=list)
    canonical_index: dict[str, NamedCoral] = field(default_factory=dict)
    nc_by_id: dict[int, NamedCoral] = field(default_factory=dict)
    auto_link_aliases: list[Alias] = field(default_factory=list)
    flag_review_aliases: list[Alias] = field(default_factory=list)
    named_corals_by_length_desc: list[NamedCoral] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Self-enforce the load-time invariants so test callers that build
        # MatchCache by hand don't have to repeat load_match_cache's wiring:
        #   - named_corals_by_length_desc must equal named_corals sorted by
        #     -len(normalized_name) (consumed by stages 2 + 3).
        #   - each NamedCoral.trigrams must hold the pre-computed trigram set
        #     (consumed by stage 6 fuzzy fallback).
        # load_match_cache populates both before construction, so this
        # post-init is a no-op on the production path.
        if self.named_corals and not self.named_corals_by_length_desc:
            self.named_corals_by_length_desc = sorted(
                self.named_corals, key=lambda c: -len(c.normalized_name),
            )
        for nc in self.named_corals:
            if not nc.trigrams:
                nc.trigrams = _trigrams(nc.normalized_name)


@dataclass
class MatchResult:
    """The four matcher fields persisted on vendor_listings (arch §3.1).
    matched_at is ISO-8601 UTC string when any non-null cascade hit fires
    (stages 1-6); None on stage-7 no-match. Caller writes them in the
    Phase A UPSERT alongside the diff fields per arch §3.2.
    """
    named_coral_id: int | None
    match_confidence: str | None  # 'exact' | 'alias' | 'fuzzy' | 'manual' | None
    match_method: str | None
    matched_at: str | None


_NULL_RESULT = MatchResult(None, None, None, None)


def load_match_cache(conn: psycopg.Connection) -> MatchCache:
    """Load active named_corals + aliases once at scrape start.

    Empty cache is the Phase 1 expected state (seed loads at Phase 3 per
    CTK-002). The matcher's no-op behavior on an empty cache is the same
    code path as on a populated cache — every cascade stage misses and
    stage 7 returns null fields.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, canonical_name, normalized_name, requires_vendor_prefix, category "
            "FROM named_corals WHERE active = TRUE"
        )
        nc_rows = cur.fetchall()
    nc_list = [
        NamedCoral(
            id=int(r["id"]),
            canonical_name=r["canonical_name"],
            normalized_name=r["normalized_name"],
            requires_vendor_prefix=bool(r["requires_vendor_prefix"]),
            category=int(r["category"]),
            trigrams=_trigrams(r["normalized_name"]),
        )
        for r in nc_rows
    ]
    canonical_index = {nc.normalized_name: nc for nc in nc_list}
    nc_by_id = {nc.id: nc for nc in nc_list}
    # Longest-name-first ordering for stages 2 + 3 prefix matching — pre-sort
    # once at load time so per-listing cascade iteration doesn't re-sort.
    named_corals_by_length_desc = sorted(nc_list, key=lambda c: -len(c.normalized_name))

    with conn.cursor() as cur:
        cur.execute(
            "SELECT alias_text, named_coral_id, cluster_label, match_behavior FROM aliases"
        )
        al_rows = cur.fetchall()
    auto_link: list[Alias] = []
    flag_review: list[Alias] = []
    for r in al_rows:
        a = Alias(
            alias_text=r["alias_text"],
            named_coral_id=(int(r["named_coral_id"]) if r["named_coral_id"] is not None else None),
            cluster_label=r["cluster_label"],
            match_behavior=r["match_behavior"],
        )
        if a.match_behavior == "auto-link":
            auto_link.append(a)
        elif a.match_behavior == "flag-review":
            flag_review.append(a)

    log.info(
        "match cache loaded: %d named_corals, %d auto-link aliases, %d flag-review aliases",
        len(nc_list), len(auto_link), len(flag_review),
    )
    return MatchCache(
        named_corals=nc_list,
        canonical_index=canonical_index,
        nc_by_id=nc_by_id,
        auto_link_aliases=auto_link,
        flag_review_aliases=flag_review,
        named_corals_by_length_desc=named_corals_by_length_desc,
    )


def match_listing(
    cache: MatchCache,
    normalized_title: str,
    originator_prefix: str | None = None,
) -> MatchResult:
    """Run the §3.4 cascade. Returns a MatchResult; caller persists the
    four fields on the vendor_listings row.

    Per arch §3.2: caller invokes this only on listings that are new or
    whose raw_title changed since last scrape — unchanged listings keep
    their existing match.
    """
    if not normalized_title:
        return _NULL_RESULT

    # Stage 1 — canonical-exact
    nc = cache.canonical_index.get(normalized_title)
    if nc is not None and _category_2_passes(nc, normalized_title):
        return _hit(nc.id, "exact", "canonical-exact")

    # Stage 2 — canonical-prefix (longest-name-first to avoid sub-prefix collisions)
    for nc in cache.named_corals_by_length_desc:
        if normalized_title.startswith(nc.normalized_name + " "):
            if _category_2_passes(nc, normalized_title):
                return _hit(nc.id, "exact", "canonical-prefix")

    # Stage 3 — canonical-implicit-prefix (originator-prefix synthesis)
    if originator_prefix:
        synthesized = f"{originator_prefix} {normalized_title}"
        nc = cache.canonical_index.get(synthesized)
        if nc is not None and _category_2_passes(nc, synthesized):
            return _hit(nc.id, "exact", "canonical-implicit-prefix")
        for nc in cache.named_corals_by_length_desc:
            if synthesized.startswith(nc.normalized_name + " "):
                if _category_2_passes(nc, synthesized):
                    return _hit(nc.id, "exact", "canonical-implicit-prefix")

    # Stage 4 — alias auto-link
    for al in cache.auto_link_aliases:
        if al.alias_text and al.alias_text in normalized_title:
            nc = cache.nc_by_id.get(al.named_coral_id) if al.named_coral_id is not None else None
            if nc is None:
                continue
            if _category_2_passes(nc, normalized_title):
                return _hit(nc.id, "alias", "alias-hit")

    # Stage 5 — cluster flag-review (no category-2 guard; named_coral_id stays null)
    for al in cache.flag_review_aliases:
        if al.alias_text and al.alias_text in normalized_title:
            return MatchResult(
                named_coral_id=None,
                match_confidence="manual",
                match_method=f"cluster:{al.cluster_label}",
                matched_at=_now_iso(),
            )

    # Stage 6 — fuzzy fallback (pg_trgm-equivalent trigram Jaccard). Compute
    # the listing's trigrams once; each named_coral's trigrams pre-computed
    # at load_match_cache time.
    title_trigrams = _trigrams(normalized_title)
    scored = [
        (_trigram_similarity(title_trigrams, nc.trigrams), nc)
        for nc in cache.named_corals
    ]
    scored.sort(key=lambda x: x[0], reverse=True)
    if scored and scored[0][0] >= PG_TRGM_BASE_THRESHOLD:
        best_score, best_nc = scored[0]
        # Tie-breaker per arch §3.4: if 2nd best is within 0.05, demote to no-match.
        runner_score = scored[1][0] if len(scored) > 1 else 0.0
        if (best_score - runner_score) >= PG_TRGM_TIE_BREAKER_MARGIN:
            if _category_2_passes(best_nc, normalized_title):
                return _hit(best_nc.id, "fuzzy", f"fuzzy-{best_score:.2f}")

    # Stage 7 — no match
    return _NULL_RESULT


def _category_2_passes(nc: NamedCoral, normalized_title: str) -> bool:
    """Arch §3.5 guard. Category-1 entries skip the guard.
    Category-2 entries require the implied prefix (canonical_name's first
    word, lowercased) at the start of the title.
    """
    if not nc.requires_vendor_prefix:
        return True
    parts = nc.canonical_name.split()
    if not parts:
        return True
    implied_prefix = parts[0].lower()
    return normalized_title.startswith(implied_prefix + " ")


def _hit(named_coral_id: int, confidence: str, method: str) -> MatchResult:
    return MatchResult(
        named_coral_id=named_coral_id,
        match_confidence=confidence,
        match_method=method,
        matched_at=_now_iso(),
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _trigram_similarity(ta: set[str], tb: set[str]) -> float:
    """pg_trgm-equivalent similarity score in [0.0, 1.0]. Pure-Python
    trigram Jaccard: |ta intersect tb| / |ta union tb|. Callers supply
    pre-computed trigram sets — the listing-side set is computed once per
    listing in match_listing; the named_coral-side set is computed once
    per scrape in load_match_cache and lives on NamedCoral.trigrams.

    pg_trgm extracts trigrams from each word with leading/trailing space
    padding; _trigrams() mirrors that with two leading spaces and one
    trailing space on the full string. Close enough for the cascade
    scaffold; CTK-002 calibration validates against actual pg_trgm
    before Phase 3 launch.
    """
    if not ta and not tb:
        return 0.0
    union = ta | tb
    if not union:
        return 0.0
    return len(ta & tb) / len(union)


def _trigrams(s: str) -> set[str]:
    if not s:
        return set()
    padded = "  " + s + " "
    return {padded[i : i + 3] for i in range(len(padded) - 2)}
