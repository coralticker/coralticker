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

from scrapers.common import db, diff, matcher, parse_shopify
from scrapers.common.diff import Counters

log = logging.getLogger(__name__)


def _load_yaml(slug: str) -> dict:
    """Per-vendor YAML lives at scrapers/vendors/<slug>.yaml. Returns {} if
    absent — vendor row + sensible defaults are enough for the simplest
    Shopify cases."""
    yaml_path = Path(__file__).parent.parent / "vendors" / f"{slug}.yaml"
    if not yaml_path.exists():
        log.warning("no YAML at %s — using vendors-row defaults", yaml_path)
        return {}
    return yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}


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

    # Stage 1 — Config
    vendor_row = db.fetch_vendor(conn, slug)
    yaml_config = _load_yaml(slug)
    config = {**vendor_row, **yaml_config}  # YAML overrides DB per arch §2.3

    run_id = db.start_scraper_run(conn, vendor_row["id"], git_sha)
    log.info("scraper_runs.id=%d started for vendor=%s sha=%s", run_id, slug, git_sha)

    # Stage 1b — Match cache (per CTK-025 F4 contract documented in matcher.py).
    # Empty cache on Phase 1 (seed loads at CTK-002 / Phase 3) — no-op for now;
    # same code path lights up at seed-load. Cache-load failure surfaces as a
    # clean stage-2-prerequisite error; not wrapped in fail-soft because a
    # match-cache load failure is a connectivity issue, not a per-listing
    # exception.
    match_cache = matcher.load_match_cache(conn)
    originator_prefix = config.get("originator_prefix")

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

    try:
        # Stages 2-4 — Fetch + Parse + Normalize (parser yields normalized items)
        platform = vendor_row["platform"]
        if platform == "shopify":
            result = parse_shopify.fetch_and_parse(config)
        else:
            raise RuntimeError(f"platform {platform!r} not implemented (Phase 1 = shopify only)")

        items = result.items
        html_hash = result.html_hash
        http_status_last = result.http_status_last
        log.info("parsed %d items; html_hash=%s", len(items), html_hash)

        # Stage 5 — Diff
        existing_by_url = db.fetch_existing_listings(conn, vendor_row["id"])
        decisions = diff.classify(items, existing_by_url)
        counters = diff.counters_from(decisions)
        log.info(
            "diff: seen=%d new=%d price_changed=%d restocked=%d oos=%d",
            counters.seen, counters.new, counters.price_changed, counters.restocked, counters.oos,
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
        for d in decisions:
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
            error_class = error_class or "other"
            error_message = (
                f"{matcher_error_count} matcher exception(s); first: {matcher_error_first}"
            )

        # Stage 6 Phase A — synchronous, fast. Bulk UPSERT vendor_listings +
        # touch + price_history INSERT. Returns Phase B image-mirror queue.
        # Per CTK-024 Session 2 fix: image-fetch I/O is no longer inline with
        # the persist loop — Phase B handles it best-effort after status is
        # finalized so a mirror-loop timeout no longer loses scrape data
        # (CTK-019 #55: 'image-only failure does NOT fail the listing row').
        mirror_queue = diff.persist_phase_a(conn, vendor_row, decisions, existing_by_url, run_id)

        # Silent canary per arch §2.4. F4: no-op until day 8 (median=0 →
        # threshold collapses to floor of 5); floor-of-5 catches outright-empty
        # blocks but week-1 partial failures (5 ≤ seen < eventual 0.2 × median)
        # slip past — Slack `if: failure()` is the load-bearing alert there.
        median_7d = db.get_7d_median_seen(conn, vendor_row["id"])
        threshold = max(5.0, 0.2 * median_7d)
        if counters.seen < threshold:
            status = "failed"
            error_class = "block"
            error_message = (
                f"silent canary tripped: listings_seen={counters.seen} < "
                f"max(5, 0.2 * 7d_median={median_7d:.1f}) = {threshold:.1f}"
            )
            log.error(error_message)
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
        )
        status_finalized = True
        log.info("scraper_runs.id=%d finalized status=%s before Phase B", run_id, status)

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
