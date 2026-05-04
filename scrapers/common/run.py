"""Scraper orchestrator. Runs the arch §2.1 7-stage lifecycle:
  1. Config        — load vendors row + per-vendor YAML
  2. Fetch         — paged HTTP via http.py
  3. Parse         — dispatch by platform (shopify → parse_shopify)
  4. Normalize     — folded into the parser per arch §2.1 (stage 4 happens at
                     yield-time inside parse_shopify._normalize_product)
  5. Diff          — diff.classify against bulk-loaded existing rows
                     (NOTE: matcher hook lands at CTK-025 per arch §3.2 +
                     CTK-023 Call 2; CTK-024 ships matcher-naive, retro-fit
                     adds match_listing(...) here between stages 5 and 6)
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

from scrapers.common import db, diff, parse_shopify
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
    client = db.get_client()

    # Stage 1 — Config
    vendor_row = db.fetch_vendor(client, slug)
    yaml_config = _load_yaml(slug)
    config = {**vendor_row, **yaml_config}  # YAML overrides DB per arch §2.3

    run_id = db.start_scraper_run(client, vendor_row["id"], git_sha)
    log.info("scraper_runs.id=%d started for vendor=%s sha=%s", run_id, slug, git_sha)

    status = "failed"
    error_class: str | None = None
    error_message: str | None = None
    html_hash: str | None = None
    http_status_last: int | None = None
    counters = Counters()
    status_finalized = False
    mirror_queue: list = []

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

        # Stage 5 — Diff (matcher hook lands at CTK-025 retro-fit; not here)
        existing_by_url = db.fetch_existing_listings(client, vendor_row["id"])
        decisions = diff.classify(items, existing_by_url)
        counters = diff.counters_from(decisions)
        log.info(
            "diff: seen=%d new=%d price_changed=%d restocked=%d oos=%d",
            counters.seen, counters.new, counters.price_changed, counters.restocked, counters.oos,
        )

        # Stage 6 Phase A — synchronous, fast. Bulk UPSERT vendor_listings +
        # touch + price_history INSERT. Returns Phase B image-mirror queue.
        # Per CTK-024 Session 2 fix: image-fetch I/O is no longer inline with
        # the persist loop — Phase B handles it best-effort after status is
        # finalized so a mirror-loop timeout no longer loses scrape data
        # (CTK-019 #55: 'image-only failure does NOT fail the listing row').
        mirror_queue = diff.persist_phase_a(client, vendor_row, decisions, existing_by_url, run_id)

        # Silent canary per arch §2.4. F4: no-op until day 8 (median=0 →
        # threshold collapses to floor of 5); floor-of-5 catches outright-empty
        # blocks but week-1 partial failures (5 ≤ seen < eventual 0.2 × median)
        # slip past — Slack `if: failure()` is the load-bearing alert there.
        median_7d = db.get_7d_median_seen(client, vendor_row["id"])
        threshold = max(5.0, 0.2 * median_7d)
        if counters.seen < threshold:
            status = "failed"
            error_class = "block"
            error_message = (
                f"silent canary tripped: listings_seen={counters.seen} < "
                f"max(5, 0.2 * 7d_median={median_7d:.1f}) = {threshold:.1f}"
            )
            log.error(error_message)
        else:
            status = "success"

        # Finalize scraper_runs row NOW — before Phase B starts. Phase B is
        # best-effort; a workflow-timeout hard-kill mid-Phase-B leaves the run
        # marked success (cleanup hook is a no-op for finished rows). The
        # `if: always()` cleanup step still flips any other still-`running`
        # rows that pre-date this run.
        db.finish_scraper_run(
            client, run_id, status, error_class, error_message,
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

    except RuntimeError as e:
        # http.fetch errors come up here with .error_class set per
        # parse_shopify._to_exception. Other RuntimeErrors land as 'other'.
        ec = getattr(e, "error_class", None)
        status = "failed"
        error_class = ec if ec in ("http_429", "http_5xx", "network") else "other"
        error_message = str(e)
        log.error("runtime error (%s): %s", error_class, e)

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
                client, run_id, status, error_class, error_message,
                counters, html_hash, http_status_last,
            )
            log.info("scraper_runs.id=%d finished status=%s error_class=%s", run_id, status, error_class)

    # Phase B — best-effort image mirror loop, AFTER status finalized. Only
    # runs on success (no point mirroring images for a blocked / partial run).
    # Per-row failures are caught + logged inside persist_phase_b; never raise.
    if status_finalized and status == "success" and mirror_queue:
        try:
            persist_phase_b_succeeded, persist_phase_b_failed = diff.persist_phase_b(client, vendor_row, mirror_queue)
            log.info(
                "Phase B summary: %d/%d mirrors succeeded for run_id=%d",
                persist_phase_b_succeeded, persist_phase_b_succeeded + persist_phase_b_failed, run_id,
            )
        except Exception as e:  # noqa: BLE001 — Phase B never fails the run; log + return success
            log.warning("Phase B aborted unexpectedly (non-fatal, status stays success): %s", e)

    return 0 if status == "success" else 1


def cleanup(slug: str) -> int:
    """Arch §2.4 timeout-cleanup choice (a) — called from workflow `if: always()`
    post-step. Flips any still-`running` rows for this vendor + this git_sha
    to failed/timeout. Idempotent + safe to call after a clean run (no rows
    match the WHERE clause).
    """
    _setup_logging()
    git_sha = os.getenv("GITHUB_SHA", "local")
    client = db.get_client()
    try:
        vendor_row = db.fetch_vendor(client, slug)
    except RuntimeError as e:
        log.warning("cleanup skipped: %s", e)
        return 0
    flipped = db.cleanup_stale_runs(client, vendor_row["id"], git_sha)
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
