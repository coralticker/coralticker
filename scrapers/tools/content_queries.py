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

# Mirrored-image host — the single LIGHT source for the IG image gate, shared by
# the ig_select spotlight selector (Candidate-level) AND the content-card
# eligibility filter below (row-level). The mirror WRITER's source of truth is
# images.py:_PUBLIC_HOST (which drags boto3 + Pillow), so both import-light
# selectors derive from this ONE name instead of an inlined literal (CTK-159 Q2).
# Drift-guarded by test_ig_select asserting equality with images._PUBLIC_HOST.
# Lives here (not ig_select) so this shared layer can use it without importing
# ig_select — ig_select imports FROM here, so the reverse would be circular.
MIRROR_HOST = "https://images.coralticker.com"

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
# D-4 card data-row field contract — LOCKED /brand-manager canon (revised 2026-06-16).
# F7/F8/F9 inherit exactly TWO fields in fixed order via format_data_row:
#   Price.    plain string, or the price-drop-new struck-old/forest-new pair.
#   Listed.   relative-time. Restocks use Listed., never Back.
# No Vendor. field (rides the lead), no Ref. field (dormant).
#
# Lineage. was DROPPED in v1: named_corals has origin_vendor (free-text) but NO
# year column, so it could only render origin-only — which duplicates the vendor
# prefix already in the coral name / lead. LATENT three-field path: lineage_value
# + build_card_fields's origin/year params survive so a future year column
# reinstates Price. — Lineage. {origin} · {year} — Listed. uniformly (the mid-dot
# sits INSIDE the value, near-black mono via card CSS, never a field separator).
# ---------------------------------------------------------------------------


def lineage_value(origin: str | None, year=None) -> str | None:
    """The Lineage. value with graceful degrade. Both parts -> "origin · year";
    one part -> that part; neither -> None (caller omits the field). The mid-dot
    is U+00B7 with surrounding spaces, byte-matching the /designer frame + web."""
    parts = [p for p in (origin, str(year) if year is not None else None) if p]
    if not parts:
        return None
    return " · ".join(parts)


def plain_price_value(price) -> str:
    """Price. value for a non-drop card (F7 arrival/restock, F9 listing)."""
    return _format_price(price)


def drop_price_value(old_price, new_price) -> dict:
    """Price. value for a drop card (F8): the price-drop-new struck-old/forest-new
    pair. format_data_row + the card adapter render it identically (INV-01)."""
    return {"kind": "price-drop-new", "oldValue": _format_price(old_price), "newValue": _format_price(new_price)}


def _drop_baseline(row: dict):
    """The 'old' price for a drop display — the SAME baseline drop_fraction ranks
    on: CT-observed prior_price, else the vendor markdown compare_at_price. Using
    prior_price blindly renders a null 'price on request' as the struck value on a
    markdown-arm drop (prior_price IS NULL there)."""
    return row.get("prior_price") if row.get("prior_price") is not None else row.get("compare_at_price")


def superlative_fields(row: dict) -> list[dict]:
    """Build the F8 superlative card's D-4 field list from a select_superlative_drop
    row: a Price. drop pair (struck baseline -> forest current), Lineage. from the
    named coral's origin (year dormant in v1), Listed. from the lead-event time."""
    return build_card_fields(
        price_value=drop_price_value(_drop_baseline(row), row.get("current_price")),
        origin=row.get("named_coral_origin_vendor"),
        year=None,
        listed_at=row.get("event_at"),
    )


def build_card_fields(*, price_value, origin: str | None = None, year=None, listed_at=None) -> list[dict]:
    """Assemble the D-4 v1 field list — TWO fields, Price. — Listed. (fixed order).

    Lineage. is DROPPED in v1 (revised /brand-manager canon 2026-06-16): named_corals
    has no year column, so it could only render origin-only, which duplicates the
    coral name's vendor prefix already in the lead. origin/year stay in the signature
    as the LATENT three-field path — when a year column lands, uncomment the Lineage
    append below and the row reinstates uniformly to Price. — Lineage. {origin} · {year}
    — Listed. (lineage_value already handles the {origin}·{year} degrade).

    price_value is a prebuilt Price. value (plain_price_value or drop_price_value).
    Listed. is a relative-time over listed_at (datetime or ISO str; omitted if None)."""
    fields: list[dict] = [{"label": "Price", "value": price_value}]
    # LATENT (v1 Lineage dropped) — reinstate when named_corals gains a year column:
    #   lineage = lineage_value(origin, year)
    #   if lineage is not None:
    #       fields.append({"label": "Lineage", "value": lineage})
    if listed_at is not None:
        fields.append({"label": "Listed", "value": {"kind": "relative-time", "timestamp": listed_at}})
    return fields


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


# ---------------------------------------------------------------------------
# IG content-card selection filters (CTK-161 content lane; consumed by the
# CTK-164 B-path data cards). These WRAP the data fetchers — they never touch
# get_recent_price_drops itself, which /deals consumes UNFILTERED. Same pattern
# as ig_select's T2 worthiness gate, applied to the content-card row shape.
# ---------------------------------------------------------------------------


def card_image_price_reject(row: dict) -> str | None:
    """The IG image+price hard pre-filter (ig_select T2) as a row-level predicate.
    Returns the drop-reason or None. Image before price so a row failing both
    surfaces the image cause. Derives from MIRROR_HOST (no inlined literal)."""
    image_url = row.get("image_url")
    if image_url is None:
        return "no-image"
    if not image_url.startswith(MIRROR_HOST + "/"):
        return "non-mirror-image"
    if row.get("current_price") is None:
        return "price-on-request"
    return None


def single_card_reject(row: dict) -> str | None:
    """Junk floor for the single-listing CARD formats (F7/F8/F9 inners). Adds
    matched-corals-only to the image+price pre-filter: the Lineage. field needs a
    named coral to render, AND matched-only is what drops the unmatched ALL-CAPS
    gimmick rows that otherwise auto-win a raw biggest-drop (no separate junk list
    — CTK-155 purged the seeds). Reason order: coral -> image -> price."""
    if row.get("named_coral_id") is None:
        return "unmatched"
    return card_image_price_reject(row)


def is_single_card_eligible(row: dict) -> bool:
    """True when the row clears the single-listing-card junk floor."""
    return single_card_reject(row) is None


# Superlative GLITCH-rejection bounds — NOT editorial post-worthiness. The "is
# this drop interesting enough to feature" threshold (min %/$ ) is /brand-manager's
# content canon, landing in parallel; these only reject DATA glitches and gimmick
# rows so a $650 -> $9.99 "deal" placeholder can't auto-win the biggest-drop slot.
# Provisional — loosen/tighten is a data call, not an editorial one.
SUPERLATIVE_GLITCH_DROP_CEILING = 0.90   # >= 90% off is implausible for a real markdown
SUPERLATIVE_MIN_PRICE = 5.0              # a new price under $5 reads as frag-noise / placeholder


def superlative_drop_sane(row: dict) -> bool:
    """Glitch-rejection for the superlative (biggest-drop) format: a positive
    baseline, a new price above the frag-noise floor, and a drop fraction strictly
    inside (0, CEILING). Rejects data errors / gimmick rows — NOT small-but-real
    drops (that editorial floor is /brand-manager's). Pairs with is_single_card_
    eligible: matched-only already removes the unmatched gimmick titles; this
    catches a glitch on a MATCHED row."""
    current = row.get("current_price")
    if current is None or float(current) < SUPERLATIVE_MIN_PRICE:
        return False
    baseline = _drop_baseline(row)   # same prior-or-compare_at pick drop_fraction ranks on
    if baseline is None or float(baseline) <= 0:
        return False
    frac = drop_fraction(row.get("prior_price"), current, row.get("compare_at_price"))
    return 0.0 < frac < SUPERLATIVE_GLITCH_DROP_CEILING


# Superlative POST-WORTHINESS gate — /brand-manager content canon (2026-06-16),
# layered ON TOP of the glitch-rejection bounds. The editorial "is this drop
# interesting enough to feature" call: the drop must be big enough AND the coral
# substantial enough. Provisional pending Jon. Price basis = current (post-drop)
# price — a coral worth spotlighting is still a >= $100 piece after the markdown,
# not a cheap frag with a big percentage. If nothing clears, F8 is a clean no-post
# (skip the week), never a forced weak superlative.
MIN_DROP_FRACTION = 0.25   # >= 25% off to be worth featuring
MIN_CORAL_PRICE = 100.0    # post-drop price floor for "substantial enough to spotlight"


def superlative_post_worthy(row: dict) -> bool:
    """/brand-manager editorial gate (distinct from the glitch-rejection in
    superlative_drop_sane): the drop clears MIN_DROP_FRACTION and the post-drop
    price clears MIN_CORAL_PRICE. Both provisional pending Jon."""
    current = row.get("current_price")
    if current is None or float(current) < MIN_CORAL_PRICE:
        return False
    frac = drop_fraction(row.get("prior_price"), current, row.get("compare_at_price"))
    return frac >= MIN_DROP_FRACTION


def select_superlative_drop(conn, window_days: int = 7) -> dict | None:
    """F8 superlative content selector: the biggest single-listing price drop
    among CARD-eligible rows (matched + image + price) that pass BOTH the glitch-
    rejection bounds (superlative_drop_sane) AND the /brand-manager post-worthiness
    gate (superlative_post_worthy), over the window. Wraps fetch_recent_price_drops;
    does NOT touch get_recent_price_drops (/deals reads that unfiltered).

    Returns the winning row, or None — None is a clean no-post for the week (no
    forced weak superlative), the caller skips F8, NOT an error."""
    rows = fetch_recent_price_drops(conn, window_days)
    eligible = [
        r for r in rows
        if is_single_card_eligible(r) and superlative_drop_sane(r) and superlative_post_worthy(r)
    ]
    if not eligible:
        return None
    return max(
        eligible,
        key=lambda r: drop_fraction(r.get("prior_price"), r.get("current_price"), r.get("compare_at_price")),
    )


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
