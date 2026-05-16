"""Neon Postgres connection + scraper_runs lifecycle helpers. Keeps the
run.py orchestrator free of driver-specific calls so a future driver swap
lands in one file. CTK-043 cut-1: rewrote from supabase-py (PostgREST) to
psycopg 3 against NEON_DATABASE_URL after the 2026-05-15 Supabase org-level
402 forced the data-plane move.

Connection shape: psycopg 3 with autocommit=True + dict_row row_factory.
autocommit matches the per-statement write pattern the scrapers had under
PostgREST (no multi-statement transactions in Phase 1; Phase B's per-row
UPDATE on fail-soft also wants autocommit so a single UPDATE doesn't sit
in an open tx if the next row raises). dict_row preserves the supabase-py
".data is list-of-dicts" shape that diff.py / matcher.py / the canary test
already assume, so the cut is mechanical for callers.

Public API (parameter name client→conn for clarity; positional callers
unaffected):
    get_conn() -> psycopg.Connection
    fetch_vendor(conn, slug) -> dict
    fetch_existing_listings(conn, vendor_id) -> dict[str, dict]
    get_7d_median_seen(conn, vendor_id) -> float
    start_scraper_run(conn, vendor_id, git_sha) -> int
    finish_scraper_run(conn, run_id, status, error_class, error_message,
                       counters, html_hash, http_status_last) -> None
    finish_phase_b(conn, run_id) -> None
    cleanup_stale_runs(conn, vendor_id, git_sha) -> int
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

from scrapers.common.diff import Counters

# Load NEON_DATABASE_URL from .env at repo root for local scripts (tests,
# ad-hoc db queries). No-op if .env is absent — CI uses GitHub Actions
# secrets via workflow YAML's env: block and never has a .env on disk. See
# .env.example for the expected file shape.
load_dotenv()

log = logging.getLogger(__name__)


def get_conn() -> psycopg.Connection:
    """Open a Neon Postgres connection. autocommit=True + dict_row factory
    match the per-statement / list-of-dicts shape callers assumed under
    supabase-py per CTK-043 cut-1 design.

    Callers are responsible for closing — run.py's orchestrator doesn't
    today (process exits at the end of each invocation, OS cleans up) and
    the tests close inside their own teardown. Phase B's fail-soft loop
    catches per-row exceptions without rolling anything back because
    autocommit committed each row independently.
    """
    conninfo = os.environ["NEON_DATABASE_URL"]
    return psycopg.connect(conninfo, autocommit=True, row_factory=dict_row)


def fetch_vendor(conn, slug: str) -> dict:
    """Stage 1 (Config) — load vendors row by slug. Raises if not present;
    matches plan task 'Verify Pacific East vendors row present from CTK-028
    seed' as a runtime smoke. Hardcoded vendor_id elsewhere is a comment;
    the row is the source of truth."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, slug, display_name, base_url, platform, scrape_method, "
            "cadence_label, image_strategy, active "
            "FROM vendors WHERE slug = %s",
            (slug,),
        )
        rows = cur.fetchall()
    if not rows:
        raise RuntimeError(f"vendors row not found for slug={slug!r}; check supabase/seed.sql / CTK-028")
    if not rows[0]["active"]:
        raise RuntimeError(f"vendor {slug!r} is inactive (vendors.active=false); skipping per arch §1.3")
    return rows[0]


def fetch_existing_listings(conn, vendor_id: int) -> dict[str, dict]:
    """Bulk-load all vendor_listings for vendor at stage 5 start. Returned as
    dict keyed by product_url for O(1) per-item lookup in diff.classify +
    diff.persist_phase_a (the Phase B image-mirror queue check needs to know
    which existing rows have image_url IS NULL for catch-up after a prior
    partial-mirror run).

    CTK-033 + CTK-034 invariants ported to psycopg:
    Chunk via LIMIT 1000 OFFSET N loop with ORDER BY id (primary-key index,
    immune to driver-internal scan-state non-determinism). Loop terminates on
    first short page; 50-iteration ceiling (50,000-row hard cap) bounds
    runaway pagination if a chunk under-fills spuriously. Loud-failure
    posture per arch §2.4 — chunk SELECT exceptions bubble up; no try/except.
    Count-mismatch assertion at loop exit is the loud-failure hook for any
    future regression of the same bug class.

    Note vs. the supabase-py predecessor: psycopg doesn't have a
    PostgREST-style 1000-row response cap, so a single SELECT without LIMIT
    would also work. The chunk loop is preserved to retain the loud-failure
    invariant + parity with the canary test fixtures (the count-mismatch
    sanity check at loop exit is the load-bearing regression hook).
    """
    page_size = 1000
    iteration_ceiling = 50
    rows: list[dict] = []
    iteration = 0
    while iteration < iteration_ceiling:
        offset = iteration * page_size
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, product_url, current_price, in_stock, image_url "
                "FROM vendor_listings "
                "WHERE vendor_id = %s "
                "ORDER BY id "
                "LIMIT %s OFFSET %s",
                (vendor_id, page_size, offset),
            )
            chunk = cur.fetchall()
        rows.extend(chunk)
        iteration += 1
        if len(chunk) < page_size:
            break
    else:
        log.warning(
            "fetch_existing_listings hit %d-iteration ceiling for vendor_id=%d "
            "(%d rows fetched); catalog may exceed %d-row hard cap",
            iteration_ceiling, vendor_id, len(rows), iteration_ceiling * page_size,
        )
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) AS c FROM vendor_listings WHERE vendor_id = %s",
            (vendor_id,),
        )
        expected = cur.fetchone()["c"]
    if len(rows) != expected:
        raise RuntimeError(
            f"fetch_existing_listings coverage gap for vendor_id={vendor_id}: "
            f"chunked SELECT returned {len(rows)} rows but catalog count={expected}; "
            f"pagination dropped rows (CTK-034 chunk-ordering regression)"
        )
    return {r["product_url"]: r for r in rows}


def get_7d_median_seen(conn, vendor_id: int) -> float:
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
    with conn.cursor() as cur:
        cur.execute(
            "SELECT listings_seen FROM scraper_runs "
            "WHERE vendor_id = %s AND status = 'success' AND started_at >= %s",
            (vendor_id, cutoff),
        )
        rows = cur.fetchall()
    seen_values = sorted(int(r["listings_seen"]) for r in rows)
    if not seen_values:
        return 0.0
    n = len(seen_values)
    if n % 2 == 1:
        return float(seen_values[n // 2])
    return (seen_values[n // 2 - 1] + seen_values[n // 2]) / 2.0


def start_scraper_run(conn, vendor_id: int, git_sha: str) -> int:
    """Insert a scraper_runs row at stage 1 with status='running'. Returns
    the bigserial id used by price_history.scraper_run_id and by the post-step
    timeout-cleanup hook (arch §2.4 timeout-cleanup choice (a) — `if: always()`)."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO scraper_runs (vendor_id, status, git_sha) "
            "VALUES (%s, 'running', %s) RETURNING id",
            (vendor_id, git_sha),
        )
        row = cur.fetchone()
    return int(row["id"])


def finish_scraper_run(
    conn,
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
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE scraper_runs SET "
            "status = %s, finished_at = %s, "
            "listings_seen = %s, listings_new = %s, listings_price_changed = %s, "
            "listings_restocked = %s, listings_oos = %s, "
            "error_class = %s, error_message = %s, "
            "http_status_last = %s, html_hash = %s "
            "WHERE id = %s",
            (
                status,
                datetime.now(timezone.utc).isoformat(),
                counters.seen,
                counters.new,
                counters.price_changed,
                counters.restocked,
                counters.oos,
                error_class,
                (error_message[:1000] if error_message else None),  # column is text; keep it bounded
                http_status_last,
                html_hash,
                run_id,
            ),
        )


def finish_phase_b(conn, run_id: int) -> None:
    """CTK-038 — write `phase_b_finished_at` after Phase B reaches its
    post-mirror code path. Called from run.py AFTER the nested
    `if mirror_queue:` block (so zero-NEW steady-state rows also get a
    non-NULL timestamp) and BEFORE `return 0`. NULL strictly means
    pre-CTK-038 OR Phase-B-cancelled (hard-cancel at workflow timeout
    never reaches this call).

    Fail-soft per CTK-038 plan §Constraints: Phase B has already completed
    by the time we're writing the timestamp; failing the timestamp write
    doesn't undo the mirror work, and re-raising would mask Phase B
    success in the process exit code. Network blip / connection drop logs
    a warning and returns; the row stays NULL and looks like a hard-cancel
    in observability — acceptable trade-off vs. flipping a successful run
    to failed on a cosmetic write."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE scraper_runs SET phase_b_finished_at = %s WHERE id = %s",
                (datetime.now(timezone.utc).isoformat(), run_id),
            )
    except Exception as e:  # noqa: BLE001 — fail-soft per CTK-038 plan
        log.warning("finish_phase_b write failed for run_id=%d (non-fatal): %s", run_id, e)


def cleanup_stale_runs(conn, vendor_id: int, git_sha: str) -> int:
    """Arch §2.4 timeout-cleanup choice (a) — `if: always()` post-step calls
    this to flip any still-`running` rows for this vendor + git_sha to
    failed/timeout. Catches GH Actions hard-kill at the 10-min cap that
    bypasses the run.py finally-block. Returns count flipped."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE scraper_runs SET "
            "status = 'failed', "
            "error_class = 'timeout', "
            "error_message = %s, "
            "finished_at = %s "
            "WHERE vendor_id = %s AND status = 'running' AND git_sha = %s",
            (
                "GH Actions hard-killed run; cleanup applied via if: always()",
                datetime.now(timezone.utc).isoformat(),
                vendor_id,
                git_sha,
            ),
        )
        return cur.rowcount
