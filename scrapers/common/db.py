"""Supabase client + scraper_runs lifecycle helpers. Keeps the run.py
orchestrator free of SDK-specific calls so a future driver swap (raw psycopg,
Postgrest direct, etc.) lands in one file.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

from supabase import Client, create_client

from scrapers.common.diff import Counters

log = logging.getLogger(__name__)


def get_client() -> Client:
    """Service-role client. Bypasses RLS — never use the anon key for scraper
    writes per arch §1.3 bucket-bootstrap RLS posture."""
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_KEY"]
    return create_client(url, key)


def fetch_vendor(client: Client, slug: str) -> dict:
    """Stage 1 (Config) — load vendors row by slug. Raises if not present;
    matches plan task 'Verify Pacific East vendors row present from CTK-028
    seed' as a runtime smoke. Hardcoded vendor_id elsewhere is a comment;
    the row is the source of truth."""
    rows = (
        client.table("vendors")
        .select("id,slug,display_name,base_url,platform,scrape_method,cadence_label,image_strategy,active")
        .eq("slug", slug)
        .execute()
        .data
        or []
    )
    if not rows:
        raise RuntimeError(f"vendors row not found for slug={slug!r}; check supabase/seed.sql / CTK-028")
    if not rows[0]["active"]:
        raise RuntimeError(f"vendor {slug!r} is inactive (vendors.active=false); skipping per arch §1.3")
    return rows[0]


def fetch_existing_listings(client: Client, vendor_id: int) -> dict[str, dict]:
    """Bulk-load all vendor_listings for vendor at stage 5 start. Returned as
    dict keyed by product_url for O(1) per-item lookup in diff.classify."""
    rows = (
        client.table("vendor_listings")
        .select("id,product_url,current_price,in_stock")
        .eq("vendor_id", vendor_id)
        .execute()
        .data
        or []
    )
    return {r["product_url"]: r for r in rows}


def get_7d_median_seen(client: Client, vendor_id: int) -> float:
    """Silent-canary 7d_median half per arch §2.4. Returns the median of
    listings_seen across the last 7 days of SUCCESS runs for this vendor.

    Phase 1 first-7-days behavior (F4 fold): with no successful history yet,
    this returns 0 — making max(5, 0.2 * 0) collapse to the floor of 5.
    Per F4: silent canary 7d_median half is a no-op until day 8 of validation;
    floor-of-5 is the only canary signal in week 1; Slack `if: failure()` is
    the load-bearing alert in that window. Pattern carries to CTK-025/026/027
    first-7-day windows.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    rows = (
        client.table("scraper_runs")
        .select("listings_seen")
        .eq("vendor_id", vendor_id)
        .eq("status", "success")
        .gte("started_at", cutoff)
        .execute()
        .data
        or []
    )
    seen_values = sorted(int(r["listings_seen"]) for r in rows)
    if not seen_values:
        return 0.0
    n = len(seen_values)
    if n % 2 == 1:
        return float(seen_values[n // 2])
    return (seen_values[n // 2 - 1] + seen_values[n // 2]) / 2.0


def start_scraper_run(client: Client, vendor_id: int, git_sha: str) -> int:
    """Insert a scraper_runs row at stage 1 with status='running'. Returns
    the bigserial id used by price_history.scraper_run_id and by the post-step
    timeout-cleanup hook (arch §2.4 timeout-cleanup choice (a) — `if: always()`)."""
    row = (
        client.table("scraper_runs")
        .insert({
            "vendor_id": vendor_id,
            "status": "running",
            "git_sha": git_sha,
        })
        .execute()
        .data
    )
    return int(row[0]["id"])


def finish_scraper_run(
    client: Client,
    run_id: int,
    status: str,
    error_class: str | None,
    error_message: str | None,
    counters: Counters,
    html_hash: str | None,
    http_status_last: int | None,
) -> None:
    """Stage 7 (Log) — finalize the row. Called from run.py finally-block so
    every code path that opens a run also closes it."""
    payload = {
        "status": status,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "listings_seen": counters.seen,
        "listings_new": counters.new,
        "listings_price_changed": counters.price_changed,
        "listings_restocked": counters.restocked,
        "listings_oos": counters.oos,
        "error_class": error_class,
        "error_message": (error_message[:1000] if error_message else None),  # column is text; keep it bounded
        "http_status_last": http_status_last,
        "html_hash": html_hash,
    }
    client.table("scraper_runs").update(payload).eq("id", run_id).execute()


def cleanup_stale_runs(client: Client, vendor_id: int, git_sha: str) -> int:
    """Arch §2.4 timeout-cleanup choice (a) — `if: always()` post-step calls
    this to flip any still-`running` rows for this vendor + git_sha to
    failed/timeout. Catches GH Actions hard-kill at the 10-min cap that
    bypasses the run.py finally-block. Returns count flipped."""
    rows = (
        client.table("scraper_runs")
        .update({
            "status": "failed",
            "error_class": "timeout",
            "error_message": "GH Actions hard-killed run; cleanup applied via if: always()",
            "finished_at": datetime.now(timezone.utc).isoformat(),
        })
        .eq("vendor_id", vendor_id)
        .eq("status", "running")
        .eq("git_sha", git_sha)
        .execute()
        .data
        or []
    )
    return len(rows)
