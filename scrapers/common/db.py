"""Neon Postgres connection + scraper_runs lifecycle helpers. Keeps the
run.py orchestrator free of driver-specific calls so a future driver swap
lands in one file. CTK-043 cut-1: rewrote from supabase-py (PostgREST) to
psycopg 3 against NEON_DATABASE_URL after the 2026-05-15 Supabase org-level
402 forced the data-plane move.

Connection shape: psycopg 3 with autocommit=True + dict_row row_factory.
autocommit matches the per-statement write pattern the scrapers had under
PostgREST (Phase B's per-row UPDATE on fail-soft wants autocommit so a
single UPDATE doesn't sit in an open tx if the next row raises). dict_row
preserves the supabase-py ".data is list-of-dicts" shape that diff.py /
matcher.py / the canary test already assume, so the cut is mechanical for
callers. One explicit transaction exists (CTK-116 D-2): persist_phase_a
wraps its write blocks in `with conn.transaction():` so a mid-persist
exception rolls back to zero data-plane footprint — psycopg issues
BEGIN/COMMIT around the block and autocommit resumes after exit.

Public API (parameter name client→conn for clarity; positional callers
unaffected):
    get_conn() -> psycopg.Connection
    fetch_vendor(conn, slug) -> dict
    fetch_existing_listings(conn, vendor_id) -> dict[str, dict]
    get_7d_median_seen(conn, vendor_id) -> float
    get_7d_median_pages_fetched(conn, vendor_id) -> float
    start_scraper_run(conn, vendor_id, git_sha) -> int
    finish_scraper_run(conn, run_id, status, error_class, error_message,
                       counters, html_hash, http_status_last,
                       per_category_counts=None) -> None
    finish_phase_b(conn, run_id) -> None
    cleanup_stale_runs(conn, vendor_id, git_sha) -> int
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone

import psycopg
from dotenv import load_dotenv
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row

from scrapers.common.diff import Counters

# Load NEON_DATABASE_URL from .env at repo root for local scripts (tests,
# ad-hoc db queries). No-op if .env is absent — CI uses GitHub Actions
# secrets via workflow YAML's env: block and never has a .env on disk. See
# .env.example for the expected file shape.
load_dotenv()

log = logging.getLogger(__name__)

# Placeholder substituted for any NEON_DATABASE_URL component that surfaces in
# a connect-error message. CTK-118 Fix #1.
_CONNINFO_PLACEHOLDER = "<redacted:NEON_DATABASE_URL>"

# conninfo keys whose values are NOT sensitive — kept verbatim so the scrubbed
# message stays useful for debugging. Everything else parsed out of the
# conninfo is redacted (denylist-by-default / allowlist-the-safe). Erring
# toward redaction is deliberate (over-redact-safe per CTK-118 plan §Fix #1):
# a missed sensitive key leaks, a wrongly-redacted safe key is only cosmetic.
# CTK-118 /code-review F1.
_NONSENSITIVE_CONNINFO_KEYS = frozenset(
    {"sslmode", "port", "connect_timeout", "application_name", "channel_binding"}
)


def _scrub_conninfo(msg: str, conninfo: str) -> str:
    """Redact NEON_DATABASE_URL detail from a psycopg connect-error message
    (CTK-118 Fix #1).

    The 06-04 incident: a malformed rotated secret reached psycopg.connect,
    which raised with a *transformed* form of the conninfo (URL reformatted
    into `host=... user=... password=...`). GitHub Actions secret masking
    matches on the literal secret value and missed the transformed substring,
    so connection detail printed in a public Actions log. A literal
    `.replace(conninfo, ...)` has the same blind spot. Scrub by component:
    parse the conninfo offline and redact each sensitive *value* wherever it
    appears in the message, not just the literal URL.

    Redaction is denylist-by-default: every value parsed from the conninfo is
    redacted EXCEPT the small _NONSENSITIVE_CONNINFO_KEYS allowlist. A prior
    host/user/password-only allowlist (CTK-118 /code-review F1) leaked the Neon
    endpoint id, which the non-SNI/pooler URL carries as `options=endpoint=ep-x`
    — full-host redaction never matches the bare `ep-x` inside `options`, and
    dbname/port survived too. The `options` value is decomposed so the bare
    endpoint id is redacted, not just the whole `endpoint=ep-x` token.

    Fully defensive — this runs inside an except block, so it must never
    raise (a scrub that throws would replace a leak with a crash that masks
    the original error). conninfo_to_dict itself raises ProgrammingError on a
    malformed conninfo (the F2 case), so on any failure we discard the whole
    message and return a static redacted line — we cannot trust which spans
    of an unparseable message are sensitive.
    """
    try:
        scrubbed = msg
        # 1. Whole-string redaction of the literal conninfo if it survived
        #    verbatim in the message.
        if conninfo and conninfo in scrubbed:
            scrubbed = scrubbed.replace(conninfo, _CONNINFO_PLACEHOLDER)
        # 2. Component redaction — psycopg's transformed echo reformats the
        #    URL, so the components leak even when the literal URL does not.
        #    conninfo_to_dict is offline (no connection attempt).
        parts = conninfo_to_dict(conninfo)
        tokens: set[str] = set()
        for key, value in parts.items():
            if not value or key in _NONSENSITIVE_CONNINFO_KEYS:
                continue
            value = str(value)
            tokens.add(value)
            # `options` is compound (e.g. "endpoint=ep-x" / "-c endpoint=ep-x").
            # Redacting the whole value misses a bare `ep-x` echoed elsewhere,
            # so pull the endpoint id out as its own token.
            if key == "options":
                m = re.search(r"endpoint=([^\s&]+)", value)
                if m:
                    tokens.add(m.group(1))
        # Redact longest-first so a short token can't fragment a longer one
        # before it is matched.
        for token in sorted(tokens, key=len, reverse=True):
            scrubbed = scrubbed.replace(token, _CONNINFO_PLACEHOLDER)
        return scrubbed
    except Exception:  # noqa: BLE001 — scrub must never raise out of except
        return "conninfo unparseable; value redacted"


def get_conn() -> psycopg.Connection:
    """Open a Neon Postgres connection. autocommit=True + dict_row factory
    match the per-statement / list-of-dicts shape callers assumed under
    supabase-py per CTK-043 cut-1 design.

    Callers are responsible for closing — run.py's orchestrator doesn't
    today (process exits at the end of each invocation, OS cleans up) and
    the tests close inside their own teardown. Phase B's fail-soft loop
    catches per-row exceptions without rolling anything back because
    autocommit committed each row independently.

    CTK-118 Fix #1: connect errors are scrubbed before re-raise.
    OperationalError / ProgrammingError carry connection-detail / conninfo
    text in their message; psycopg's echo is value-derived, not literal, so
    GH Actions masking can miss it. We re-raise the SAME exception type with a
    component-redacted message so callers' `except OperationalError` /
    loud-failure routing is unchanged. `from None` suppresses the chained
    original — its message would re-leak the un-scrubbed text into the
    traceback. (KeyError on an unset NEON_DATABASE_URL is left to propagate:
    it names only the missing variable, never a value, and is fail-closed.)
    """
    conninfo = os.environ["NEON_DATABASE_URL"]
    try:
        return psycopg.connect(conninfo, autocommit=True, row_factory=dict_row)
    except (psycopg.OperationalError, psycopg.ProgrammingError) as e:
        raise type(e)(_scrub_conninfo(str(e), conninfo)) from None


class TestDatabaseNotConfigured(RuntimeError):
    """TEST_DATABASE_URL is unset. The live-DB test harness fails closed rather
    than fall back to NEON_DATABASE_URL (prod) — that silent fallback is exactly
    how CTK-213's ~2,500 test rows landed in the live catalog. Pytest converts
    this into a clean SKIP (preserving CTK-208 bare-`pytest scrapers/tests/`
    = 0-errors); script-mode main() catches it, prints the reason, and exits
    nonzero (exit-0 would be the "silently passed without touching a DB" trap)."""


class TestDatabasePointsAtProd(RuntimeError):
    """TEST_DATABASE_URL resolves to the SAME DSN as NEON_DATABASE_URL. Raised
    loud in EVERY mode — pytest and script-mode alike — and never converted to a
    skip. A test target equal to prod is the corruption path CTK-215 exists to
    close; failing closed here, including in CI, is the whole point."""


def get_test_conn() -> psycopg.Connection:
    """Open a connection to the dedicated TEST database (a long-lived Neon
    branch), for the requires_db / live-DB test suites (CTK-215). Fails closed:

      - TEST_DATABASE_URL unset        -> TestDatabaseNotConfigured (pytest SKIP
                                          / script-mode nonzero-with-message)
      - TEST_DATABASE_URL == prod DSN  -> TestDatabasePointsAtProd (loud, every
                                          mode; never a skip)

    The collision check is full-DSN string equality, NOT host comparison: a Neon
    branch shares the prod host (only the endpoint id / branch differs), so a
    host-compare would pass the branch AND fail to catch a prod-pointed test
    target. Compare the exact connection strings — if they match byte-for-byte,
    the test target IS prod. (A param-reordered-but-equivalent DSN isn't caught;
    the realistic footgun is an identical copy-paste of the prod URL into
    TEST_DATABASE_URL, which this does catch.)

    get_conn() (the prod path) is intentionally untouched and unaware of this
    function — production code never resolves TEST_DATABASE_URL. CTK-118
    _scrub_conninfo is preserved on the connect-error re-raise, identical to
    get_conn(), so a malformed TEST DSN can't leak into an Actions log."""
    test_url = os.environ.get("TEST_DATABASE_URL")
    if not test_url:
        raise TestDatabaseNotConfigured(
            "TEST_DATABASE_URL is not set; refusing to run live-DB tests against "
            "NEON_DATABASE_URL (prod). Set TEST_DATABASE_URL to a dedicated Neon "
            "branch DSN (see CTK-215)."
        )
    prod_url = os.environ.get("NEON_DATABASE_URL")
    if prod_url is not None and test_url == prod_url:
        raise TestDatabasePointsAtProd(
            "TEST_DATABASE_URL equals NEON_DATABASE_URL (prod); refusing to run "
            "the test harness against the live catalog. Point TEST_DATABASE_URL "
            "at a dedicated Neon branch, not prod (see CTK-215)."
        )
    try:
        return psycopg.connect(test_url, autocommit=True, row_factory=dict_row)
    except (psycopg.OperationalError, psycopg.ProgrammingError) as e:
        raise type(e)(_scrub_conninfo(str(e), test_url)) from None


def fetch_vendor(conn: psycopg.Connection, slug: str) -> dict:
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


def fetch_existing_listings(conn: psycopg.Connection, vendor_id: int) -> dict[str, dict]:
    """Bulk-load all vendor_listings for vendor at stage 5 start. Returned as
    dict keyed by product_url for O(1) per-item lookup in diff.classify +
    diff.persist_phase_a (the Phase B image-mirror queue check needs to know
    which existing rows have image_url IS NULL for catch-up after a prior
    partial-mirror run).

    CTK-124 F8: compare_at_price added to the SELECT so persist_phase_a can
    detect the DB-observed NULL <-> non-NULL transition and write/clear
    vendor_listings.markdown_started_at (migration 0033) on both the UPSERT
    and unchanged-touch paths. The transition test is presence-based against
    THIS db-side value vs. the parsed item's — not against the prior item.

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
                "SELECT id, product_url, current_price, in_stock, image_url, compare_at_price "
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
        # while-else fires only on iteration-ceiling reach (no break taken).
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


def get_7d_median_seen(conn: psycopg.Connection, vendor_id: int) -> float:
    """Silent-canary 7d_median half per arch §2.4. Returns the median of
    listings_seen across the last 7 days for this vendor.

    Phase 1 first-7-days behavior (F4 fold): with no successful history yet,
    this returns 0 — making max(5, 0.2 * 0) collapse to the floor of 5.
    Per F4: silent canary 7d_median half is a no-op until day 8 of validation;
    floor-of-5 is the only canary signal in week 1; Slack `if: failure()` is
    the load-bearing alert in that window. Pattern carries to CTK-025/026/027
    first-7-day windows.

    CTK-094 §4.3 ratchet exclusion: counts status='success' AND ALSO counts
    canary-only false-fails (status='failed' AND error_class='block' AND
    error_message contains 'silent canary tripped:'). Without this, a single
    false-canary-trip excludes the run's listings_seen from the next median
    computation — biasing the median upward and making the next low-buyable
    window more likely to trip. Real block events (Cloudflare / WAF /
    network) stay excluded because their error_message lacks the canary
    substring; their listings_seen value is unreliable. The canary-self-fail
    listings_seen value IS reliable (the parse succeeded; only the count
    crossed the threshold), so including it dilutes the median back toward
    the actual catalog volatility.

    CTK-094 fold #2 (/code-review F2): LIKE is contains-match
    ('%silent canary tripped:%%'), NOT prefix-match. run.py L290-295 builds
    error_message via `f'{error_message}; {canary_msg}' if error_message
    else canary_msg` — when matcher_error_count>0 already set error_message
    at L201-204, the canary text gets APPENDED as suffix. A prefix-match
    LIKE 'silent canary tripped:%' would fail on combined matcher+canary
    runs, excluding them from the median and defeating the ratchet fix in
    the exact scenario it was meant to handle. Contains-match catches both
    canary-first and matcher-first concatenation orders.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT listings_seen FROM scraper_runs "
            "WHERE vendor_id = %s AND started_at >= %s "
            "AND ("
            "  status = 'success' "
            "  OR ("
            "    status = 'failed' AND error_class = 'block' "
            "    AND error_message LIKE '%%silent canary tripped:%%'"
            "  )"
            ")",
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


def get_7d_median_pages_fetched(conn: psycopg.Connection, vendor_id: int) -> float:
    """CTK-094 §4.2 completeness signal — returns the 7-day median of
    pages_fetched across SUCCESS runs for this vendor. Used by run.py to
    emit a soft WARN when the current run's pages_fetched falls below a
    configurable fraction of the historical baseline (catches under-scrape
    classes like TG Finding-1's toolbar-drift truncation that the
    listings_seen canary alone can miss — the count-canary watches the
    item-count tail; this watches the page-count tail).

    Per-vendor median (not fleet) because pages_fetched varies wildly across
    vendors (PE Shopify ~1-2 pages on /products.json, AquaSD BC Stencil
    ~10-15 across 21 category_paths, TG Magento ~7-10 across 7 paths). A
    per-vendor floor is the only meaningful baseline.

    Phase 1 first-7-days behavior mirrors get_7d_median_seen: no history
    yet → returns 0 → run.py guards against the zero-baseline case (no WARN
    until a real median lands). Pre-CTK-094 rows have NULL pages_fetched
    (column lands at this migration); SELECT filters NULL out so the
    rollout window stays clean.

    CTK-094 fold #8 (/code-review F8): mirrors get_7d_median_seen's §4.3
    ratchet exclusion — counts canary-self-fail runs alongside
    status='success'. A canary false-fail run's pages_fetched is reliable
    (parse ran to completion; only the count check tripped at canary). Not
    including those rows would bias the pages-median upward on the same
    ratchet pattern §4.3 just fixed for listings_seen — making the §4.2
    completeness signal harder to trip after a canary false-fire.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT pages_fetched FROM scraper_runs "
            "WHERE vendor_id = %s AND started_at >= %s "
            "AND pages_fetched IS NOT NULL "
            "AND ("
            "  status = 'success' "
            "  OR ("
            "    status = 'failed' AND error_class = 'block' "
            "    AND error_message LIKE '%%silent canary tripped:%%'"
            "  )"
            ")",
            (vendor_id, cutoff),
        )
        rows = cur.fetchall()
    values = sorted(int(r["pages_fetched"]) for r in rows)
    if not values:
        return 0.0
    n = len(values)
    if n % 2 == 1:
        return float(values[n // 2])
    return (values[n // 2 - 1] + values[n // 2]) / 2.0


def get_recent_cohort_absent_hashes(
    conn: psycopg.Connection, vendor_id: int, run_id: int, limit: int
) -> list[str | None]:
    """CTK-137 T-3 — the last `limit` (= K-1) runs' cohort_absent_set_hash for
    this vendor, newest first, EXCLUDING the in-flight run_id (its own hash
    isn't written until finish_scraper_run, so it must not be in the lookback).

    Used by the stateful-convergence K-stable check: convergence fires only
    when these K-1 prior hashes ALL equal the current run's computed hash.
    Returns each row's hash as-is (str or None) — a NULL (failed/blocked fetch
    that never computed a cohort absent-set, or a pre-CTK-137 row) is returned
    as None so the caller's equality test breaks the stable chain on it.

    Fewer than `limit` rows when history is short (new vendor / few runs); the
    caller treats short history as 'not yet K-stable' and does not converge.
    No-op-safe at limit<=0 (K=1 → limit 0): returns []."""
    if limit <= 0:
        return []
    with conn.cursor() as cur:
        cur.execute(
            "SELECT cohort_absent_set_hash FROM scraper_runs "
            "WHERE vendor_id = %s AND id <> %s "
            "ORDER BY started_at DESC "
            "LIMIT %s",
            (vendor_id, run_id, limit),
        )
        return [r["cohort_absent_set_hash"] for r in cur.fetchall()]


def start_scraper_run(conn: psycopg.Connection, vendor_id: int, git_sha: str) -> int:
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
    conn: psycopg.Connection,
    run_id: int,
    status: str,
    error_class: str | None,
    error_message: str | None,
    counters: Counters,
    html_hash: str | None,
    http_status_last: int | None,
    per_category_counts: dict | None = None,
    pages_fetched: int | None = None,
    cohort_absent_set_hash: str | None = None,
    cohort_absent_count: int | None = None,
) -> None:
    """Stage 7 (Log) — finalize the row. Called from run.py finally-block so
    every code path that opens a run also closes it.

    CTK-094 extensions: per_category_counts (default {} for vendors without
    category_cohort_signal:true in YAML; populated by parse_bigcommerce on
    AquaSD) + pages_fetched (default None on pre-CTK-094 / failure-before-
    fetch paths; populated by all three parsers when fetch ran at all).

    CTK-137 extensions: cohort_absent_set_hash (sha256 of the sorted
    product_url set in the run's cohort-OOS absent-set; NULL when no cohort
    decisions were computed) + cohort_absent_count (len of that set at gate
    time). Both feed the stateful-convergence K-stable check via
    get_recent_cohort_absent_hashes. Written on every run.
    """
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE scraper_runs SET "
            "status = %s, finished_at = %s, "
            "listings_seen = %s, listings_new = %s, listings_price_changed = %s, "
            "listings_restocked = %s, listings_oos = %s, "
            "error_class = %s, error_message = %s, "
            "http_status_last = %s, html_hash = %s, "
            "per_category_counts = %s::jsonb, pages_fetched = %s, "
            "cohort_absent_set_hash = %s, cohort_absent_count = %s "
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
                json.dumps(per_category_counts or {}),
                pages_fetched,
                cohort_absent_set_hash,
                cohort_absent_count,
                run_id,
            ),
        )


def finish_phase_b(conn: psycopg.Connection, run_id: int) -> None:
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


def cleanup_stale_runs(conn: psycopg.Connection, vendor_id: int, git_sha: str) -> int:
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
