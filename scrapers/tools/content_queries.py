"""CTK-161 D-1/D-4 — owned-data content engine: the shared cross-vendor query
layer (Python side).

The design-once unit is the set of Postgres functions in migration 0041 (D-1 —
the only single-implementation point the Python content tools and the TS site can
both share). This module is the thin Python fetch layer on top: it wraps those
functions, carries the per-format COMPARATIVE flag (D-2), holds the cross-vendor
eligibility predicate shared by the SQL guard and the pure ranker, and builds the
DataRowField[] listing-line contract (D-4) that every consumer renders against.

What lives here vs. elsewhere (D-1/D-4 boundary):
  - The LAYER returns data: SQL-function rows + the DataRowField[] listing-line
    shape + the comparative flag. Consumers (ig_select / blog / TikTok) RENDER.
  - Selection/curation (ig_select's IG-spotlight scorer) stays in ig_select.py —
    it's IG-specific selection, not shared content-data.
  - The auto-publish gate (comparative == false only) lives in the Slice-B
    adapter ig_spotlight.py, NOT here — the query layer computes every format
    ungated (D-2).

Extracted from ig_select.py at the CTK-161 refactor: fetch_cross_vendor_cheapest,
fetch_medal_magnitudes, the pure cross_vendor_cheapest_ids ranker, and
drop_fraction moved here; ig_select.py re-imports them. The cross-vendor ranking
itself promoted to SQL (get_cross_vendor_cheapest) so the TS site gets the same
implementation; the pure ranker is KEPT as the executable reference spec of the
crowning contract (guarded by a golden + a DB parity test).

Pure helpers (is_cross_vendor_eligible, cross_vendor_cheapest_ids, drop_fraction,
the descriptors, the listing-line builders) are DB-free and unit-driven. The
fetch_* wrappers are the I/O shell (read-only; never close the caller's conn).
"""

from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Cross-vendor eligibility predicate — shared by the SQL guard and the ranker.
# ---------------------------------------------------------------------------


def is_cross_vendor_eligible(row: dict) -> bool:
    """The cross-vendor cheapest eligibility predicate (the INV-05 residual D-3
    triple + a named coral): a row may be crowned "cheapest" only if it names a
    coral, is in stock, is NOT an auction (auction_end_time IS NULL — INV-05
    residual), and carries a price.

    Asserted in TWO places as defense in depth (plan open-item 2): the pure
    ranker cross_vendor_cheapest_ids applies it BEFORE ranking, and
    fetch_cross_vendor_cheapest re-asserts it over the SQL function's returned
    rows so a regressed SQL predicate (an auction / OOS / unpriced / unnamed row
    sneaking into "cheapest") fails loudly instead of shipping a bad post. One
    predicate, two enforcement points."""
    return (
        row.get("named_coral_id") is not None
        and row.get("in_stock") is True
        and row.get("auction_end_time") is None
        and row.get("current_price") is not None
    )


def cross_vendor_cheapest_ids(rows: list[dict]) -> set[int]:
    """Pure ranker: from named-coral listing rows, return the ids that are the
    cheapest of their named_coral across >= 2 DISTINCT vendors. Applies
    is_cross_vendor_eligible per row first, so the eligibility triple holds even
    if handed an unfiltered set.

    Genuine price ties yield >1 cheapest id (both ARE the cheapest). Prices
    (Decimal) compare directly — exact, so a cent-for-cent tie is detected
    without float-rounding hazard.

    Post-CTK-161 the production ranking is the SQL function get_cross_vendor_cheapest;
    this pure function is KEPT as the executable reference spec — pinned by a
    committed golden (test_content_queries) and cross-checked against the SQL
    function over a live-seeded fixture (test_cross_vendor_ranking_parity). It is
    NOT dead code: it is the spec the SQL is held to."""
    eligible = [r for r in rows if is_cross_vendor_eligible(r)]
    by_coral: dict[int, list[dict]] = {}
    for r in eligible:
        by_coral.setdefault(r["named_coral_id"], []).append(r)

    out: set[int] = set()
    for group in by_coral.values():
        if len({r["vendor_id"] for r in group}) < 2:
            continue
        cheapest = min(r["current_price"] for r in group)
        out.update(r["id"] for r in group if r["current_price"] == cheapest)
    return out


def drop_fraction(prior_price, current_price, compare_at_price) -> float:
    """Medal magnitude as a fraction in [0, 1]. Prefers the CT-observed drop
    (prior_price, get_recent_price_drops arm 1); falls back to the vendor
    markdown reference (compare_at_price, arm 2, where prior_price is NULL).
    Returns 0.0 when neither reference is usable (no positive baseline)."""
    for baseline in (prior_price, compare_at_price):
        if baseline is None or current_price is None:
            continue
        baseline = float(baseline)
        if baseline <= 0:
            continue
        frac = (baseline - float(current_price)) / baseline
        return max(0.0, min(1.0, frac))
    return 0.0


# ---------------------------------------------------------------------------
# Format descriptors — the per-format COMPARATIVE flag (D-2).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FormatDescriptor:
    """One content format. `comparative` is the D-2 publish gate: a format is
    comparative when its render names a vendor's price RELATIVE TO another
    vendor's (a who's-cheapest ranking). The auto-publish adapter
    (ig_spotlight.auto_publishable) reads this flag; the query layer never does
    (it computes every format ungated). The cross-vendor COMPUTATION is shared
    and ungated — only the RENDER that names who's cheapest is gated."""
    key: str
    label: str
    comparative: bool


# Velocity (listed-and-gone) is non-comparative and publish-now-safe as of
# 2026-06-16 (branding-guide.md §"Velocity claim resolution- + cause-honesty") —
# windowed, cause-neutral language only; the query stays claim-neutral (it exposes
# raw timestamps, the render derives the window). The five built formats + the two
# comparative ones:
CONTENT_FORMATS: dict[str, FormatDescriptor] = {
    # Non-comparative — publish-now-safe. Report activity without pitting vendors
    # against each other on price.
    "aggregate-activity": FormatDescriptor(
        "aggregate-activity", "Aggregate activity", comparative=False),
    "most-restocked": FormatDescriptor(
        "most-restocked", "Most restocked of the week", comparative=False),
    "single-listing-drop": FormatDescriptor(
        "single-listing-drop", "Single-listing price drop", comparative=False),
    "velocity": FormatDescriptor(
        "velocity", "Velocity (listed and gone)", comparative=False),
    # Comparative — built but PUBLISH-GATED. Render names which shop is cheapest.
    "cheapest-across-vendors": FormatDescriptor(
        "cheapest-across-vendors", "Cheapest across N vendors", comparative=True),
    "market-report": FormatDescriptor(
        "market-report", "Market report", comparative=True),
}


# ---------------------------------------------------------------------------
# Listing-line contract (D-4) — row -> DataRowField[].
#
# PROVISIONAL field selection (Q3 — locked 2026-06-15): the exact labels and
# field order for each content format are /brand-manager's content-class voice
# canon (CTK-161 parallel brand lane), unresolved at this layer. The order below
# mirrors the email digest's Price-first shape (lib/email/digest.ts:buildFields)
# as a defensible default; it is NOT canon. The DataRowField[] SHAPE (the
# contract every consumer renders against) is locked; the field CHOICE layers on
# top and may change when the brand canon lands. Tagged provisional so a future
# reader doesn't mistake the digest-mirror for a brand decision.
# ---------------------------------------------------------------------------


def _format_price(value) -> str:
    """Provisional price string for a listing line. Mirrors the email digest's
    formatPrice ($X.XX, 2 decimals); 'price on request' for a null price (the
    auction parse-time shape, never a fake buy price). Cross-vendor crowned rows
    always carry a price (eligibility), so the null branch is for reuse safety."""
    if value is None:
        return "price on request"
    return f"${float(value):.2f}"


def cross_vendor_cheapest_line(row: dict) -> list[dict]:
    """The DataRowField[] listing line for one cross-vendor-cheapest crowned row
    (the "Cheapest [coral] across N vendors" format — COMPARATIVE). Provisional
    per Q3: Price then Vendor, mirroring the digest's Price-first order. The coral
    NAME and the "across N vendors" wrap are aggregate copy (outside INV-01, owned
    by /copy-writer); this builder emits only the INV-01-bound listing line."""
    return [
        {"label": "Price", "value": _format_price(row.get("current_price"))},
        {"label": "Vendor", "value": row.get("vendor_display_name") or ""},
    ]


# ---------------------------------------------------------------------------
# I/O shell — fetch wrappers over the migration-0041 functions + the reused
# get_recent_price_drops. Read-only; the caller owns the conn lifecycle.
# ---------------------------------------------------------------------------


def fetch_cross_vendor_cheapest(conn) -> list[dict]:
    """Cross-vendor cheapest crowned listing rows, via the SQL function
    get_cross_vendor_cheapest() (the ranking promoted to SQL — D-1). Returns the
    render-ready rows (list[dict]); ig_select derives its id-set from these.

    DEFENSE IN DEPTH (plan open-item 2): the SQL WHERE asserts the eligibility
    triple; re-assert it per returned row with is_cross_vendor_eligible so a
    regressed SQL predicate fails loudly HERE — an auction / OOS / unpriced /
    unnamed row crowned "cheapest" is a bad-post hazard, not a row to paper over.
    This is the predicate guard (NOT a re-rank: re-ranking the crowned-rows-only
    subset would collapse the >= 2-vendor gate to ties-only and silently drop
    single-cheapest crowns — the regression CTK-161 Q1 caught)."""
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM get_cross_vendor_cheapest()")
        rows = cur.fetchall()
    leaked = [r for r in rows if not is_cross_vendor_eligible(r)]
    if leaked:
        raise ValueError(
            f"get_cross_vendor_cheapest() returned {len(leaked)} row(s) failing the "
            f"cross-vendor eligibility triple (named + in_stock + non-auction + priced): "
            f"ids {sorted(r['id'] for r in leaked)}. SQL predicate regression."
        )
    return rows


def fetch_medal_magnitudes(conn, window_days: int) -> dict[int, float]:
    """CTK-047 medal magnitude per listing via the canonical medal surface
    get_recent_price_drops(). Already carries INV-05 on both arms — no residual to
    re-assert. Returns {listing_id: drop_fraction}; the max fraction per listing
    if a row appears under more than one arm. (ig_select's score path consumes
    this; the content single-drop FORMAT consumes fetch_recent_price_drops for the
    render-ready rows.)"""
    out: dict[int, float] = {}
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM get_recent_price_drops(%s)", (window_days,))
        for r in cur.fetchall():
            frac = drop_fraction(r.get("prior_price"), r.get("current_price"), r.get("compare_at_price"))
            lid = r["id"]
            if frac > out.get(lid, 0.0):
                out[lid] = frac
    return out


def fetch_recent_price_drops(conn, window_days: int = 30) -> list[dict]:
    """Render-ready single-listing price-drop rows via get_recent_price_drops(
    p_window_days) (D-2 single-listing-drop format — reuses the existing function,
    no new one). Returns the full rows so the content render has the coral name,
    vendor, price, and prior_price for "this coral dropped N% this month". The
    30-day default matches the "this month" framing; provisional pending the
    content-class cadence canon (Q3), caller-overridable."""
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM get_recent_price_drops(%s)", (window_days,))
        return cur.fetchall()


def fetch_aggregate_activity(conn, window_hours: int = 24) -> dict:
    """Aggregate-activity counts via get_aggregate_activity() — lead-event count +
    distinct-vendor count over the window ("47 drops across 11 shops today").
    Always exactly one row (0/0 on an empty window)."""
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM get_aggregate_activity(%s)", (window_hours,))
        return cur.fetchone()


def fetch_most_restocked(conn, window_hours: int = 168, limit: int = 10) -> list[dict]:
    """Most-restocked ranking via get_most_restocked() — back-in-stock lead-events
    grouped by named_coral over the window, ranked by count. Matched-only
    population (a coral you can't name can't rank — D-2)."""
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM get_most_restocked(%s, %s)", (window_hours, limit))
        return cur.fetchall()


def fetch_velocity(conn, window_days: int | None = None) -> list[dict]:
    """Velocity (listed-and-gone) rows via get_velocity_listings(). One row per
    still-OOS, matched listing whose full first lifecycle we OBSERVED, carrying the
    three raw timestamps the render derives its window from (first_seen_at,
    last_in_stock_at, first_oos_at) plus the coral/vendor identity fields.

    The SQL excludes cold-start listings (no successful scrape finished before the
    first in-stock observation — we never watched them appear, so their lifespan is
    fictional) — a claim-honesty correctness gate, not a tunable. window_days is an
    optional recency selector on the gone-event (NULL = all); it is NOT a scrape
    interval — no cadence config is threaded, the render is self-contained per row.

    Claim-neutral by construction: the rows say WHEN, never WHY. Cause-neutral
    templating ("gone" / "didn't last", never "sold out") is the render's job
    (no sellout-vs-delist discriminator exists)."""
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM get_velocity_listings(%s)", (window_days,))
        return cur.fetchall()
