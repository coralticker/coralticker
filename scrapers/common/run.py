"""Scraper orchestrator. Runs the arch §2.1 7-stage lifecycle:
  1. Config        — load vendors row + per-vendor YAML
  1b. Match cache  — load_match_cache (per CTK-025 F4: after stage 1, before
                     stage 2 — client established, cache participates in 60-min
                     timeout boundary, empty-cache no-op same path as populated)
  2. Fetch         — paged HTTP via http.py
  3. Parse         — dispatch by platform (shopify → parse_shopify)
  4. Normalize     — folded into the parser per arch §2.1 (stage 4 happens at
                     yield-time inside parse_shopify._normalize_product)
  5. Diff          — diff.classify against bulk-loaded existing rows
  5.5 Match        — matcher.match_listing per new decision, fail-soft per
                     arch §3.2 (exception → null match fields + append to
                     scraper_runs.error_message + status='partial' + continue).
                     CTK-025 scaffold scope: matcher runs on 'new' decisions
                     only; title-changed-on-existing deferred to CTK-002
                     calibration era when seed loads (see Outstanding for
                     /lead-backend in results.md Session 1).
  6. Persist       — diff.persist + image-mirror inline per CTK-019 #55
  7. Log           — db.finish_scraper_run with html_hash + canary

Run as: python -m scrapers.common.run <slug>

Exits non-zero on failure so GH Actions `if: failure()` triggers the §6.3
Slack alert. The `if: always()` post-step calls `cleanup` to flip any
still-`running` rows on hard-kill timeout per arch §2.4.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import traceback
from pathlib import Path

import yaml

from scrapers.common import db, diff, matcher, parse_bigcommerce, parse_shopify
from scrapers.common.diff import Counters
from scrapers.common.errors import ConfigError
from scrapers.vendors import tidal_gardens

log = logging.getLogger(__name__)


def _load_yaml(slug: str) -> dict:
    """Per-vendor YAML lives at scrapers/vendors/<slug>.yaml. A missing file
    raises ConfigError (loud-failure per arch §3 invocation contract): the
    YAML/slug mismatch class (CTK-093: `unique_corals.yaml` underscored vs.
    DB slug `unique-corals` hyphenated) silently dropped `originator_prefix`
    on every UC scrape until the rename landed. A present-but-empty file
    stays valid — `yaml.safe_load(...) or {}` collapses null content to
    {} so per-key defaults still apply."""
    yaml_path = Path(__file__).parent.parent / "vendors" / f"{slug}.yaml"
    if not yaml_path.exists():
        raise ConfigError(f"no vendor YAML at {yaml_path}")
    return yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}


def _apply_cohort_gate(
    per_item_decisions: list,
    cohort_oos_decisions: list,
    counters: Counters,
    *,
    canary_tripped: bool,
    matcher_error_count: int,
    cohort_unsafe_partial: bool,
) -> tuple[list, bool]:
    """CTK-094 fold #12 (/code-review F12 test-coverage extraction) — pure
    function that applies the Stage 5.7 cohort-OOS gate. Returns (decisions,
    cohort_safe) tuple; `counters.oos` is mutated in-place on the cohort-fire
    path (+= len(cohort_oos_decisions)).

    Gate predicate: cohort decisions fire only when the run is going to be
    treated as fully-successful — no canary trip, no matcher exceptions, no
    partial-category degradation. Any one of these signals disables cohort
    OOS persistence for this run (cohort decisions dropped; per-item rows
    persist normally; status determined separately downstream).

    Extracted from inline run.py code so the gate logic can be unit-tested
    independently of the orchestrator's db + parser dependencies. The three
    boolean inputs are exactly the partial-success signals run.py computes
    before this call; counters is the per-item Counters that flows to
    finish_scraper_run.

    listings_seen semantic preserved: counters.seen stays at the per-item
    count regardless of cohort outcome (per fold #1). Only counters.oos
    increments on cohort fire — the synthetic OOS decisions contribute to
    listings_oos but NOT listings_seen, which would otherwise inflate the
    get_7d_median_seen baseline.
    """
    cohort_safe = (
        not canary_tripped
        and matcher_error_count == 0
        and not cohort_unsafe_partial
    )
    if cohort_safe and cohort_oos_decisions:
        decisions = per_item_decisions + cohort_oos_decisions
        counters.oos += len(cohort_oos_decisions)
    else:
        decisions = per_item_decisions
    return decisions, cohort_safe


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )


def run(slug: str) -> int:
    """Returns process exit code — 0 on success, 1 on failure/partial. The
    GH Actions `if: failure()` Slack step (per CTK-024 plan L41 + arch §6.3)
    fires on non-zero exit."""
    _setup_logging()
    git_sha = os.getenv("GITHUB_SHA", "local")
    conn = db.get_conn()

    # Stage 1 — Config (vendors row only). YAML load + match-cache load move
    # inside the try block below so a ConfigError / connectivity failure routes
    # to the L213 handler (scraper_runs row finalized with error_class='config'
    # or 'other', Slack alert fires). Pre-CTK-093 shape ran _load_yaml + match
    # cache load + originator_prefix lookup before start_scraper_run, so a raise
    # escaped uncaught — no run row, no normal alert path.
    vendor_row = db.fetch_vendor(conn, slug)
    run_id = db.start_scraper_run(conn, vendor_row["id"], git_sha)
    log.info("scraper_runs.id=%d started for vendor=%s sha=%s", run_id, slug, git_sha)

    status = "failed"
    error_class: str | None = None
    error_message: str | None = None
    html_hash: str | None = None
    http_status_last: int | None = None
    counters = Counters()
    status_finalized = False
    mirror_queue: list = []
    matcher_error_count = 0
    matcher_error_first: str | None = None
    # CTK-094 §4.2 + §5.2 — initialized outside the try-block so the failure-
    # path finish_scraper_run call (at the finally clause) can pass them
    # uniformly. Parser-side population happens at Stage 2-4; pre-parser
    # failures (ConfigError on YAML load, db.fetch_vendor error) leave them
    # as their initial defaults and the column writes NULL / '{}' accordingly.
    pages_fetched: int | None = None
    per_category_counts: dict = {}

    try:
        # Stage 1 (cont.) — YAML config load. CTK-093: _load_yaml raises
        # ConfigError on missing file (caught at L213 below). YAML overrides
        # vendors-row per arch §2.3.
        yaml_config = _load_yaml(slug)
        config = {**vendor_row, **yaml_config}

        # Stage 1b — Match cache (per CTK-025 F4 contract documented in matcher.py).
        # Empty cache on Phase 1 (seed loads at CTK-002 / Phase 3) — no-op for now;
        # same code path lights up at seed-load. Cache-load failure surfaces as a
        # clean stage-2-prerequisite error; not wrapped in fail-soft because a
        # match-cache load failure is a connectivity issue, not a per-listing
        # exception.
        match_cache = matcher.load_match_cache(conn)
        originator_prefix = config.get("originator_prefix")

        # Stages 2-4 — Fetch + Parse + Normalize (parser yields normalized items).
        # CTK-094 fold #5: cohort_unsafe_partial flag — set to True when
        # parse_bigcommerce raises PartialCategoryWarning (silent-zero category
        # drift, theme-override class). Disables cohort-OOS gate at Stage 5.7
        # so the cohort branch doesn't mass-flip previously-in_stock products
        # from the silently-empty path to OOS. Healthy categories still
        # persist normally; status stays 'success' (or 'partial' on matcher
        # exceptions); the WARN log surfaces the affected paths for operator
        # triage.
        cohort_unsafe_partial = False
        # CTK-094 Session 5 fold #2 (/code-review F2): set when parser raises
        # SchemaChangeError carrying a partial ParseResult (marker-broken
        # escalation from parse_bigcommerce). Forces status='partial' at the
        # success-path status branch so healthy-categories' items persist while
        # the marker-broken signal surfaces via error_class='html_schema_change'
        # + error_message. Distinct from cohort_unsafe_partial (cohort gate
        # disable) — the two flags coexist on a marker-broken-escalation run.
        marker_broken_force_partial = False
        platform = vendor_row["platform"]
        try:
            if platform == "shopify":
                result = parse_shopify.fetch_and_parse(config)
            elif platform == "bigcommerce":
                # CTK-090 decision register row #66 — BigCommerce Stencil platform
                # class. Shared parser raises the same SchemaChangeError /
                # BlockedError / FetchError shapes as parse_shopify (imported
                # directly in parse_bigcommerce); no new except clauses needed.
                result = parse_bigcommerce.fetch_and_parse(config)
            elif platform == "magento":
                # CTK-087 — Magento platform class (third after shopify +
                # bigcommerce). Single-file vendor module (no shared parse_magento.py
                # until a second Magento vendor lands, per arch §2.8 rule-of-three).
                # Raises the same SchemaChangeError / BlockedError / FetchError
                # shapes as parse_shopify (imported in tidal_gardens); no new except
                # clauses needed.
                result = tidal_gardens.fetch_and_parse(config)
            else:
                raise RuntimeError(f"platform {platform!r} not implemented (v1 = shopify + bigcommerce + magento)")
        except parse_bigcommerce.PartialCategoryWarning as e:
            log.warning(
                "partial-category WARN — cohort-OOS gate disabled for this run; affected paths: %s",
                e.partial_paths,
            )
            result = e.result
            cohort_unsafe_partial = True
            # CTK-094 Session 4 fold #2 (/code-review F2): persist the
            # partial-bucket signal to scraper_runs.error_message via the
            # canary_msg / completeness_msg accumulator pattern. Status
            # stays 'success' on the healthy categories — the per-vendor
            # PartialCategoryWarning catch sets cohort_unsafe_partial +
            # error_class='other' (Session 5 fold #4) + accumulates
            # error_message, but does NOT escalate status (only the sibling
            # marker-broken catch below sets marker_broken_force_partial
            # → status='partial'). CTK-097 alerting queries filtering by
            # `error_class IS NOT NULL` surface this row at status='success'
            # — error_message carries the marker-side observability so ops
            # queries surface partial-bucket drift events rather than
            # relying on transient WARN logs.
            partial_msg = (
                f"partial-category WARN: {', '.join(e.partial_paths)}"
            )
            error_message = (
                f"{error_message}; {partial_msg}" if error_message else partial_msg
            )
            # CTK-094 Session 5 fold #4 (/code-review F4): set error_class so
            # CTK-097 alerting + ops queries filtering by `error_class IS NOT
            # NULL` surface the partial-bucket event. Re-uses the existing
            # 'other' enum value (matches the matcher-branch idiom at L286)
            # — no migration needed. CHECK constraint extension to a dedicated
            # 'partial_category' value parked to open-items for a future
            # migration that adds it as a first-class enum.
            error_class = error_class or "other"
        except parse_shopify.SchemaChangeError as e:
            # CTK-094 Session 5 fold #2 (/code-review F2): marker-broken
            # escalation carries a partial ParseResult so healthy-categories'
            # items persist. Re-raise when no result (the normal SchemaChange
            # path — schema drift detected mid-parse before items existed; the
            # outer-except handler at L420 catches that and finalizes with no
            # persist). Carrier-present path mirrors PartialCategoryWarning:
            # extract result + accumulate to error_message + force status to
            # 'partial' via marker_broken_force_partial; cohort_unsafe_partial
            # also set because mass-marker-broken implies cohort gate must
            # disable for this run.
            if getattr(e, "result", None) is None:
                raise
            log.error(
                "marker-broken escalation with partial result — persisting healthy-categories' items: %s",
                e,
            )
            result = e.result
            cohort_unsafe_partial = True
            marker_broken_force_partial = True
            marker_broken_msg = str(e)
            error_message = (
                f"{error_message}; {marker_broken_msg}" if error_message else marker_broken_msg
            )
            error_class = "html_schema_change"

        items = result.items
        html_hash = result.html_hash
        http_status_last = result.http_status_last
        # CTK-094 §4.2 + §5.2 — parser-side observability surfaces. Defaulted
        # at the ParseResult dataclass so a pre-CTK-094 parser still satisfies
        # the contract; populated by the three CTK-094 parser edits.
        pages_fetched = result.pages_fetched
        per_category_counts = result.per_category_counts
        # CTK-094 fold #4 (/code-review F4): URLs the parser actively
        # rejected via YAML filter. diff.classify excludes these from the
        # cohort-OOS absent-set so parser-filter rejection (vendor re-
        # categorized item to a non-allowlisted bucket) doesn't conflate
        # with vendor-sold-out.
        filtered_urls = result.filtered_urls
        log.info(
            "parsed %d items; html_hash=%s; pages_fetched=%s; filtered_urls=%d",
            len(items), html_hash, pages_fetched, len(filtered_urls),
        )

        # Stage 5 — Diff. CTK-094 D-1: tuple return splits per-item decisions
        # (always landed) from cohort-OOS decisions (gated on canary outcome
        # per §3 short-circuit). cohort_oos_at_persist resolves off the
        # YAML-merged config (per arch §2.3 YAML-wins-over-vendors-row).
        existing_by_url = db.fetch_existing_listings(conn, vendor_row["id"])
        cohort_oos_at_persist = bool(config.get("cohort_oos_at_persist", False))
        per_item_decisions, cohort_oos_decisions = diff.classify(
            items,
            existing_by_url,
            cohort_oos_at_persist=cohort_oos_at_persist,
            filtered_urls=filtered_urls,
        )
        counters = diff.counters_from(per_item_decisions)
        log.info(
            "diff (per-item): seen=%d new=%d price_changed=%d restocked=%d oos=%d; cohort_oos_pending=%d",
            counters.seen, counters.new, counters.price_changed, counters.restocked, counters.oos,
            len(cohort_oos_decisions),
        )

        # Stage 5.5 — Match (per arch §3.2 + §3.4, between stages 5 and 6a).
        # Fail-soft per arch §3.2: a per-listing matcher exception writes null
        # match fields, accumulates into scraper_runs.error_message, flips the
        # run to status='partial', and continues — never aborts the scrape.
        # CTK-025 scaffold scope: matcher runs on 'new' decisions only.
        # 'price_changed'/'restocked'/'oos' rows preserve existing match fields
        # (UPSERT payload omits match columns when ItemDecision.match_result
        # is None — PostgREST preserves columns absent from the payload).
        # Title-changed-on-existing rows are a deferred gap (see results.md
        # Outstanding Questions for /lead-backend); CTK-002 calibration era
        # is the natural moment to extend.
        # CTK-094: iterate per_item_decisions only — cohort-OOS synthetic
        # decisions are decision="oos" so they'd skip the d.decision != "new"
        # guard anyway, but the cohort list doesn't exist as `decisions` until
        # Stage 5.7 gate runs below. Iterate the per-item list directly.
        for d in per_item_decisions:
            if d.decision != "new":
                continue
            try:
                d.match_result = matcher.match_listing(
                    match_cache, d.item.get("normalized_title", ""), originator_prefix,
                )
            except Exception as e:  # noqa: BLE001 — fail-soft per arch §3.2
                d.match_result = matcher.MatchResult(None, None, None, None)
                matcher_error_count += 1
                if matcher_error_first is None:
                    matcher_error_first = f"matcher: {type(e).__name__}: {e}"
                log.warning("matcher exception on %s: %s", d.item.get("product_url"), e)

        if matcher_error_count > 0:
            # Append to error_message (truncated to 1000 chars in db.finish_scraper_run).
            # CTK-094 Session 5 fold #1 (/code-review F1): conditional accumulator
            # matching the three sibling branches (partial-category L213, completeness
            # L367, canary L386). Pre-Session-5 this was a plain assignment that would
            # overwrite a prior partial_msg from the PartialCategoryWarning catch when
            # both fired on the same run — the exact observability gap fold #2 was
            # designed to close.
            error_class = error_class or "other"
            matcher_msg = (
                f"{matcher_error_count} matcher exception(s); first: {matcher_error_first}"
            )
            error_message = (
                f"{error_message}; {matcher_msg}" if error_message else matcher_msg
            )

        # Stage 5.6 (CTK-094) — Canary check moved BEFORE persist_phase_a so
        # cohort-OOS decisions can be gated on the canary outcome per §3
        # short-circuit: cohort-OOS MUST NOT land on non-success runs
        # (SchemaChangeError / canary-tripped / config-error). The per-item
        # decisions persist regardless of canary outcome (today's semantic
        # preserved — data parsed is data written). Only the synthetic cohort-
        # OOS decisions hold behind the gate.
        median_7d = db.get_7d_median_seen(conn, vendor_row["id"])
        # CTK-094 D-2 (i): YAML opt-out of the median-ratio canary. POTO sets
        # canary:false (volatile 21-164 buyable count false-trips median).
        # Floor-of-5 still applies — outright-empty / total-failure detection
        # survives. canary value present but truthy (or absent) → default ON.
        canary_enabled = config.get("canary", True) is not False
        if canary_enabled:
            threshold = max(5.0, 0.2 * median_7d)
        else:
            # CTK-094 Session 4 fold #4 (/code-review F4): per-vendor floor
            # override on canary:false vendors. POTO sets canary_floor: 15
            # because its normal buyable count is 21-164 (CTK-088 fold #2),
            # so default floor-of-5 leaves the 5-20 parser-bug band uncovered.
            # CTK-094 Session 5 fold #3 (/code-review F3): defensive coalesce
            # — `config.get('canary_floor') or 5.0` short-circuits on None /
            # 0 / empty-string before reaching float(), preventing the
            # TypeError that `float(None)` would raise on blank YAML
            # (`canary_floor:` / `canary_floor: ~` / `canary_floor: null`).
            # The poto.yaml comment documents blank-canary_floor as
            # "absent" equivalent — this defensive coalesce makes that
            # documented semantic actually true.
            canary_floor = float(config.get("canary_floor") or 5.0)
            # CTK-094 Session 5 fold #5 (/code-review F5): range validation
            # — defends against negative-typo (e.g., `canary_floor: -15`
            # silently disables the canary because `counters.seen < -15` is
            # always False) + extreme-value (e.g., `canary_floor: 100000`
            # silently always-trips). Routes to existing 'config' error_class
            # via the ConfigError handler at L462. Upper bound 10000 is well
            # above any plausible vendor catalog size — Phase 1-3 vendors
            # cap at ~6,000 items; 10000 leaves headroom while still
            # catching off-by-orders-of-magnitude typos.
            if not 0 < canary_floor < 10000:
                raise ConfigError(
                    f"canary_floor must be in (0, 10000); got {canary_floor}"
                )
            threshold = canary_floor
        canary_tripped = counters.seen < threshold
        canary_msg: str | None = None
        if canary_tripped:
            canary_msg = (
                f"silent canary tripped: listings_seen={counters.seen} < "
                f"{'max(5, 0.2 * ' + f'7d_median={median_7d:.1f})' if canary_enabled else f'floor={threshold:.1f}'} "
                f"= {threshold:.1f}"
            )
            log.error(canary_msg)

        # Stage 5.7 (CTK-094) — Cohort-OOS gate. Per §3: cohort decisions
        # only land when status will be 'success' (no canary trip AND no
        # matcher exceptions yet). matcher_error_count above is the partial-
        # status signal; canary_tripped is the failed-status signal. Either
        # one drops the cohort decisions. SchemaChangeError / BlockedError /
        # FetchError / ConfigError all raise before reaching this point —
        # the except-block handlers below take over and persist_phase_a
        # never runs, so cohort-OOS decisions can't slip through there.
        decisions, cohort_safe = _apply_cohort_gate(
            per_item_decisions,
            cohort_oos_decisions,
            counters,
            canary_tripped=canary_tripped,
            matcher_error_count=matcher_error_count,
            cohort_unsafe_partial=cohort_unsafe_partial,
        )
        if cohort_safe and cohort_oos_decisions:
            log.info(
                "cohort_oos: gate passed — appending %d absent-set OOS decisions; "
                "listings_seen=%d (per-item only) listings_oos=%d (per-item + cohort)",
                len(cohort_oos_decisions), counters.seen, counters.oos,
            )
        elif cohort_oos_decisions:
            log.info(
                "cohort_oos: gate failed — dropping %d decisions "
                "(canary_tripped=%s matcher_errors=%d cohort_unsafe_partial=%s)",
                len(cohort_oos_decisions), canary_tripped,
                matcher_error_count, cohort_unsafe_partial,
            )

        # Stage 5.8 (CTK-094 §4.2) — completeness signal. Soft WARN when
        # pages_fetched falls below 50% of the per-vendor 7d median (NOT
        # max_pages ratio; max_pages is a runaway ceiling, not an expected
        # count). Observability-only — does NOT flip status. Fires only when
        # the canary is silent (no double-signal) AND median exists (no
        # first-7-days false-fire). Accumulates into error_message so the
        # transient log lands on the persistent row.
        if pages_fetched is not None and not canary_tripped:
            median_pages_7d = db.get_7d_median_pages_fetched(conn, vendor_row["id"])
            if median_pages_7d > 0 and pages_fetched < 0.5 * median_pages_7d:
                completeness_msg = (
                    f"completeness signal: pages_fetched={pages_fetched} < "
                    f"0.5 * 7d_median_pages={median_pages_7d:.1f}"
                )
                log.warning(completeness_msg)
                error_message = (
                    f"{error_message}; {completeness_msg}" if error_message else completeness_msg
                )

        # Stage 6 Phase A — synchronous, fast. Bulk UPSERT vendor_listings +
        # touch + price_history INSERT. Returns Phase B image-mirror queue.
        # Per CTK-024 Session 2 fix: image-fetch I/O is no longer inline with
        # the persist loop — Phase B handles it best-effort after status is
        # finalized so a mirror-loop timeout no longer loses scrape data
        # (CTK-019 #55: 'image-only failure does NOT fail the listing row').
        # CTK-094: `decisions` includes cohort-OOS entries when cohort_safe.
        mirror_queue = diff.persist_phase_a(conn, vendor_row, decisions, existing_by_url, run_id)

        # Status assignment uses canary outcome computed above (CTK-094
        # reorder). Per-item decisions wrote regardless of canary; status
        # reflects the canary result + matcher exceptions + marker-broken
        # escalation (Session 5 fold #2). Canary supersedes — a partial-result
        # marker-broken run that ALSO trips canary lands status='failed' so
        # the louder signal wins.
        if canary_tripped:
            status = "failed"
            # CTK-094 Session 6 fold #3 (/code-review F3): preserve a prior
            # error_class from the in-try catches (marker-broken catch sets
            # 'html_schema_change' at L258) when both fire on the same run.
            # Plain assignment would clobber the louder marker-broken signal
            # with 'block' on canary trip — CTK-097 alerting queries filtering
            # by error_class='html_schema_change' would then miss the row
            # despite the marker-broken cause being in error_message free-text.
            # `error_class or 'block'` keeps 'block' as the canary default when
            # error_class is None (the typical canary-only run) while
            # preserving an in-try-catch-set value when one exists.
            error_class = error_class or "block"
            error_message = (
                f"{error_message}; {canary_msg}" if error_message else canary_msg
            )
        elif marker_broken_force_partial:
            # CTK-094 Session 5 fold #2 (/code-review F2): marker-broken
            # escalation persisted healthy-categories' items via the in-try
            # SchemaChangeError-with-result catch. Status='partial' so CTK-097
            # alerting + ops queries surface the row; error_class already set
            # to 'html_schema_change' at the catch site; error_message already
            # accumulated.
            status = "partial"
        elif matcher_error_count > 0:
            # Arch §3.2: matcher exceptions flip status to 'partial' (data
            # persisted with null match fields, error_message accumulated).
            status = "partial"
        else:
            status = "success"

        # Finalize scraper_runs row NOW — before Phase B starts. Phase B is
        # best-effort; a workflow-timeout hard-kill mid-Phase-B leaves the run
        # marked success (cleanup hook is a no-op for finished rows). The
        # `if: always()` cleanup step still flips any other still-`running`
        # rows that pre-date this run.
        db.finish_scraper_run(
            conn, run_id, status, error_class, error_message,
            counters, html_hash, http_status_last,
            per_category_counts=per_category_counts,
            pages_fetched=pages_fetched,
        )
        status_finalized = True
        log.info("scraper_runs.id=%d finalized status=%s before Phase B", run_id, status)

    except ConfigError as e:
        # User-side YAML / vendors-row mistake — distinct from vendor-side
        # HTML drift. Route to error_class='config' so on-call investigates
        # the config, not the vendor surface (CTK-090 Session 4
        # /code-review finding #13).
        status = "failed"
        error_class = "config"
        error_message = str(e)
        log.error("config error: %s", e)

    except parse_shopify.SchemaChangeError as e:
        # Best-effort partial: any items already persisted stay; mark partial
        # so §6 sees the alert without losing the data per arch §2.4.
        status = "partial"
        error_class = "html_schema_change"
        error_message = str(e)
        log.error("schema change: %s", e)

    except parse_shopify.BlockedError as e:
        status = "failed"
        error_class = "block"
        error_message = str(e)
        log.error("blocked: %s", e)

    except parse_shopify.FetchError as e:
        # http.fetch typed error — error_class is one of arch §2.4:
        # http_429 / http_5xx / network / other.
        status = "failed"
        error_class = e.error_class if e.error_class in ("http_429", "http_5xx", "network") else "other"
        error_message = str(e)
        log.error("fetch error (%s): %s", error_class, e)

    except RuntimeError as e:
        # Other RuntimeErrors land as 'other' — e.g., unknown-platform stub or
        # any future RuntimeError raised inside the stage 2-6 try block.
        status = "failed"
        error_class = "other"
        error_message = str(e)
        log.error("runtime error: %s", e)

    except Exception as e:  # noqa: BLE001 — last-resort catch-all to ensure scraper_runs closes
        status = "failed"
        error_class = "other"
        error_message = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
        log.exception("unhandled exception")

    finally:
        if not status_finalized:
            # Phase A didn't reach finalization — failure path. Close the row
            # with whatever status the except-clause computed.
            db.finish_scraper_run(
                conn, run_id, status, error_class, error_message,
                counters, html_hash, http_status_last,
                per_category_counts=per_category_counts,
                pages_fetched=pages_fetched,
            )
            log.info("scraper_runs.id=%d finished status=%s error_class=%s", run_id, status, error_class)

    # Phase B — best-effort image mirror loop, AFTER status finalized. Only
    # runs on success (no point mirroring images for a blocked / partial run).
    # Per-row failures are caught + logged inside persist_phase_b; never raise.
    # Phase B skipped on partial-status (matcher exception path included). Existing
    # rows with NULL `image_url` re-queue on next scrape's Phase B catch-up — the
    # 1-hour mirror delay is acceptable until Phase 3 (matcher partials are
    # impossible with empty cache pre-seed-load; Phase 3 frequency materializing
    # is the revisit trigger). Per /lead-backend review-results CTK-025
    # 2026-05-04 Q3 disposition.
    # CTK-038 structural refactor — parent `if status_finalized and status == "success":`
    # block + nested `if mirror_queue:` guards persist_phase_b. db.finish_phase_b
    # lifts to parent-block level AFTER the nested block (so zero-NEW steady-state
    # rows with empty mirror_queue also get a non-NULL phase_b_finished_at) and
    # BEFORE return 0. NULL strictly means pre-CTK-038 OR Phase-B-cancelled
    # (hard-cancel at workflow timeout never reaches this call). Helper is
    # fail-soft (logs warning + returns on exception per CTK-038 plan §Constraints).
    if status_finalized and status == "success":
        if mirror_queue:
            try:
                persist_phase_b_succeeded, persist_phase_b_failed = diff.persist_phase_b(conn, vendor_row, mirror_queue)
                log.info(
                    "Phase B summary: %d/%d mirrors succeeded for run_id=%d",
                    persist_phase_b_succeeded, persist_phase_b_succeeded + persist_phase_b_failed, run_id,
                )
            except Exception as e:  # noqa: BLE001 — Phase B never fails the run; log + return success
                log.warning("Phase B aborted unexpectedly (non-fatal, status stays success): %s", e)
        db.finish_phase_b(conn, run_id)

    return 0 if status == "success" else 1


def cleanup(slug: str) -> int:
    """Arch §2.4 timeout-cleanup choice (a) — called from workflow `if: always()`
    post-step. Flips any still-`running` rows for this vendor + this git_sha
    to failed/timeout. Idempotent + safe to call after a clean run (no rows
    match the WHERE clause).
    """
    _setup_logging()
    git_sha = os.getenv("GITHUB_SHA", "local")
    conn = db.get_conn()
    try:
        vendor_row = db.fetch_vendor(conn, slug)
    except RuntimeError as e:
        log.warning("cleanup skipped: %s", e)
        return 0
    flipped = db.cleanup_stale_runs(conn, vendor_row["id"], git_sha)
    if flipped:
        log.warning("cleanup flipped %d still-running rows to failed/timeout", flipped)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="CoralTicker scraper orchestrator")
    parser.add_argument("slug", help="vendor slug (e.g. pacific_east)")
    parser.add_argument("--cleanup", action="store_true", help="post-step timeout cleanup hook only")
    args = parser.parse_args()
    if args.cleanup:
        return cleanup(args.slug)
    return run(args.slug)


if __name__ == "__main__":
    sys.exit(main())
