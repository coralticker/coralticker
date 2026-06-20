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


def drop_dollars(prior_price, current_price, compare_at_price) -> float:
    """Absolute dollar drop for the medal — baseline (CT-observed prior_price, else
    the vendor markdown compare_at_price; the SAME baseline drop_fraction picks)
    minus current_price, floored at 0. Returns 0.0 when neither reference is usable.
    The CTK-159 spotlight v1 scores the absolute dollars (a $100 markdown on a $500
    coral outranks a $10 markdown on a $20 frag), not the percent — see ig_select.

    DELIBERATE baseline divergence (CTK-170 fold #5, confirm-intended — NOT a bug):
    the prior_price-FIRST order means a CT-observed dip is taken as the baseline even
    when compare_at_price is a LARGER vendor markdown, so a small CT drop can mask a
    bigger MSRP markdown in the scored dollars. That is the intended medal definition:
    the CT-observed price IS the medal — the same baseline drop_fraction ranks on and
    _drop_baseline renders, so the scored magnitude, the ranked fraction, and the
    struck-price display all agree on ONE baseline. Preferring the larger of the two
    would re-define the medal (a CTK-047 medal-definition change, out of scope here)."""
    for baseline in (prior_price, compare_at_price):
        if baseline is None or current_price is None:
            continue
        baseline = float(baseline)
        if baseline <= 0:
            continue
        return max(0.0, baseline - float(current_price))
    return 0.0


@dataclass(frozen=True)
class MedalMagnitude:
    """One listing's price-drop medal magnitude, both shapes: `fraction` (drop as a
    0..1 fraction, the CTK-047 percent) and `dollars` (the absolute dollar drop). The
    CTK-159 spotlight score uses `dollars` (v1, pure absolute); `fraction` is carried
    alongside for display / future use."""
    fraction: float
    dollars: float


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
# Field selection is CANON (D-5 — /brand-manager 2026-06-17, branding-guide.md
# §"IG data-post copy" listing-line field contract; Q3 cleared). Price-leading on
# every format and surface — channel parity with the web <DataRow> + email digest,
# not a digest coincidence: a reader finds Price. in the same slot everywhere. The
# `Vendor.` field is COMPARATIVE-ONLY — the cross-vendor formats render
# `Price. — Vendor.` (vendor is the load-bearing fact, no single-vendor lead to
# ride); non-comparative formats (F7/F8/F9, the most-restocked drill-in) carry NO
# Vendor. field (vendor rides the lead) and render `Price. — Listed.` via
# build_card_fields. The DataRowField[] SHAPE stays locked under INV-01; the field
# CHOICE layers on top and is now equally locked.
# ---------------------------------------------------------------------------


def _format_price(value) -> str:
    """Provisional price string for a listing line. Mirrors the email digest's
    formatPrice ($X.XX, 2 decimals); 'price on request' for a null price (the
    auction parse-time shape, never a fake buy price). Cross-vendor crowned rows
    always carry a price (eligibility), so the null branch is for reuse safety."""
    if value is None:
        return "price on request"
    return f"${float(value):.2f}"


def _displayed_price(value):
    """The numeric value _format_price renders — rounded to the SAME 2 decimals via
    the same `.2f` rounding (so it is byte-faithful to the displayed price, not just
    for already-2dp inputs). None passes through. Used by superlative_pct so the
    headline % is computed off the displayed pair, never the raw input."""
    return None if value is None else float(f"{float(value):.2f}")


def cross_vendor_cheapest_line(row: dict) -> list[dict]:
    """The DataRowField[] listing line for one cross-vendor-cheapest crowned row
    (the "Cheapest [coral] across N vendors" format — COMPARATIVE). Price then
    Vendor per D-5 canon: Price leads (channel parity), and `Vendor.` is the
    comparative-only field — the cross-vendor formats are the ONLY ones carrying
    it (the vendor is the row's load-bearing fact and there is no single-vendor
    lead to ride). The coral NAME and the "across N vendors" wrap are aggregate
    copy (outside INV-01, owned by /copy-writer); this builder emits only the
    INV-01-bound listing line."""
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


def superlative_pct(row: dict) -> int:
    """The F8 headline drop percent, computed from the SAME 2-decimal values the
    rendered Price. pair shows: baseline + current are rounded through _displayed_price
    (the _format_price `.2f` rounding drop_price_value renders with) BEFORE the ratio,
    then rounded to a whole percent. So the headline % and the on-card receipt can
    never disagree — true by construction, not only for already-2dp inputs — which is
    the /brand-manager F8 %-parity gate (the % computes from the rendered pair, e.g.
    $650 -> $455 = 30%, never a separately rounded value). Baseline selection +
    fraction reuse drop_fraction (the same shape the ranker crowns on)."""
    return round(drop_fraction(
        _displayed_price(row.get("prior_price")),
        _displayed_price(row.get("current_price")),
        _displayed_price(row.get("compare_at_price")),
    ) * 100)


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


def fetch_medal_magnitudes(conn, window_days: int) -> dict[int, MedalMagnitude]:
    """CTK-047 medal magnitude per listing via the canonical medal surface
    get_recent_price_drops(). Already carries INV-05 on both arms — no residual to
    re-assert. Returns {listing_id: MedalMagnitude} carrying BOTH the drop fraction
    and the absolute dollar drop; when a listing appears under more than one arm,
    keeps the arm with the larger DOLLAR drop (the spotlight score's magnitude — so
    the carried fraction is the one belonging to that same arm, no cross-arm mix).
    (ig_select's score path consumes this; the content single-drop FORMAT consumes
    fetch_recent_price_drops for the render-ready rows.)"""
    out: dict[int, MedalMagnitude] = {}
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM get_recent_price_drops(%s)", (window_days,))
        for r in cur.fetchall():
            prior, current, compare = r.get("prior_price"), r.get("current_price"), r.get("compare_at_price")
            mag = MedalMagnitude(
                fraction=drop_fraction(prior, current, compare),
                dollars=drop_dollars(prior, current, compare),
            )
            lid = r["id"]
            if mag.dollars > out.get(lid, MedalMagnitude(0.0, 0.0)).dollars:
                out[lid] = mag
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
    """Junk floor for IMAGE-BEARING single-listing card formats: matched-corals-
    only ON TOP of the image+price pre-filter. matched-only drops the unmatched
    ALL-CAPS gimmick rows that otherwise auto-win a raw biggest-drop (no separate
    junk list — CTK-155 purged the seeds); it stands on its own as the gimmick
    floor. Reason order: coral -> image -> price.

    NOT the surface-B floor: F7/F8/F9 render no vendor photo and gate on
    is_surface_b_card_eligible (matched + price, no image) — surface-B is photo-
    less (branding-guide.md L187: the data is the hook). This predicate is retained
    for any future photo-on-card format that genuinely needs a mirror image. (The
    earlier 'Lineage. field needs a named coral' rationale is stale — Lineage. is
    dropped in v1; matched-only carries the floor regardless.)"""
    if row.get("named_coral_id") is None:
        return "unmatched"
    return card_image_price_reject(row)


def is_single_card_eligible(row: dict) -> bool:
    """True when the row clears the IMAGE-BEARING single-card junk floor.

    Deliberately retained though it has no live caller post-2026-06-17 (F7/F8/F9
    moved to is_surface_b_card_eligible): this is the documented image-bearing
    floor a future photo-on-card format reinstates, and the contrast it draws is
    what is_surface_b_card_eligible's docstring points at. Not orphaned — kept."""
    return single_card_reject(row) is None


def is_surface_b_card_eligible(row: dict) -> bool:
    """Junk floor for the photo-less surface-B card inners (F7/F8/F9): matched
    (named_coral_id) + priced (current_price is not None). NO image requirement —
    the surface-B owned card carries no vendor photo (branding-guide.md L187: the
    data is the hook), so the mirror-image arm of single_card_reject would gate on
    a photo the card never renders. matched-only drops the unmatched ALL-CAPS
    gimmick rows (CTK-155 purged the seeds); price is the rendered Price. field.

    Distinct from is_single_card_eligible (the image-BEARING card predicate,
    retained for a future photo-on-card format) and from card_image_price_reject
    (the A-path / ig_select image gate, where the photo IS the post)."""
    return row.get("named_coral_id") is not None and row.get("current_price") is not None


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
    among CARD-eligible rows (matched + price; surface-B is photo-less, so no image
    gate — shares is_surface_b_card_eligible with F7/F9) that pass BOTH the glitch-
    rejection bounds (superlative_drop_sane) AND the /brand-manager post-worthiness
    gate (superlative_post_worthy), over the window. Wraps fetch_recent_price_drops;
    does NOT touch get_recent_price_drops (/deals reads that unfiltered).

    Returns the winning row, or None — None is a clean no-post for the week (no
    forced weak superlative), the caller skips F8, NOT an error."""
    rows = fetch_recent_price_drops(conn, window_days)
    eligible = [
        r for r in rows
        if is_surface_b_card_eligible(r) and superlative_drop_sane(r) and superlative_post_worthy(r)
    ]
    if not eligible:
        return None
    return max(
        eligible,
        key=lambda r: drop_fraction(r.get("prior_price"), r.get("current_price"), r.get("compare_at_price")),
    )


def fetch_velocity(conn, window_days: int | None = None) -> list[dict]:
    """Velocity (listed-and-gone) rows via get_velocity_listings(). One row per
    still-OOS, matched, non-auction listing whose full first lifecycle we OBSERVED,
    carrying the timestamps the render derives its window from plus the coral/vendor
    identity fields:
      - first_seen_at / last_in_stock_at / first_oos_at — the observed lifecycle.
      - prior_run_finished_at — the last successful scrape that COMPLETED before the
        first in-stock sighting. The render's window anchor: window = first_oos_at -
        prior_run_finished_at, rounded UP (the widest HONEST upper bound — the piece
        could have been listed any time after that run found the catalog without it).

    The SQL excludes cold-start listings (no successful scrape finished before the
    first in-stock observation — we never watched them appear, so their lifespan is
    fictional) — a claim-honesty correctness gate, not a tunable; that exclusion is
    now the prior_run_finished_at IS NOT NULL filter (migration 0046). It also gates
    out auctions (auction_end_time / is_auction) — an auction's OOS is its clock, not
    demand, so it carries no velocity claim. window_days is an optional recency
    selector on the gone-event (NULL = all); it is NOT a scrape interval — no cadence
    config is threaded, the render is self-contained per row.

    Claim-neutral by construction: the rows say WHEN, never WHY. Cause-neutral
    templating ("gone" / "didn't last", never "sold out") is the render's job
    (no sellout-vs-delist discriminator exists)."""
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM get_velocity_listings(%s)", (window_days,))
        return cur.fetchall()


def _velocity_window(row: dict):
    """The observed lifespan upper bound for a velocity row: first_oos_at -
    prior_run_finished_at (a timedelta). The selector scores on this raw delta
    (smallest = went fastest); the render rounds it UP to a cadence-keyed unit. None
    when either anchor is missing — defensive only: the SQL guarantees both non-NULL
    (prior_run_finished_at IS NOT NULL is the cold-start gate)."""
    anchor = row.get("prior_run_finished_at")
    gone = row.get("first_oos_at")
    if anchor is None or gone is None:
        return None
    return gone - anchor


def select_velocity(conn, window_days: int | None = None) -> dict | None:
    """Velocity single-stat selector: among watched-appear-and-gone listings, the one
    that went FASTEST — the smallest observed lifespan window (_velocity_window:
    first_oos_at - prior_run_finished_at). Smallest window = the strongest honest "it
    didn't last" story. Pure data/scoring; no render (the render — unit bucketing,
    per-vendor cadence floor, cause-neutral copy — is Wave 2, gated on the /designer
    velocity frame).

    Returns the winning row (the fetch_velocity dict, carrying the identity fields +
    timestamps + prior_run_finished_at the render derives {window} from), or None —
    None is a clean no-post (no velocity-worthy piece this window), the caller skips
    velocity, NOT an error. Mirrors select_superlative_drop's no-forced-weak-post shape.

    Tie-break on id for determinism (a batch scrape can produce equal windows).

    window_days scopes the gone-event recency (NULL = all); NOT a scrape interval.

    No MAX-window post-worthiness floor yet: on a quiet window this returns the
    fastest available even if that is days, not hours. A max-window gate (the velocity
    analogue of F8's provisional MIN_DROP_FRACTION) is a /brand-manager editorial
    call; it slots in here as a pre-filter on `scored` without changing the min-pick.
    Flagged to /lead-backend -> /brand-manager."""
    rows = fetch_velocity(conn, window_days)
    scored = [r for r in rows if _velocity_window(r) is not None]
    if not scored:
        return None
    return min(scored, key=lambda r: (_velocity_window(r), r["id"]))


# ---------------------------------------------------------------------------
# Surface-B card content selectors — F7 (arrivals/restock carousel) + F9
# (lineage spotlight). Each returns the render-ready shape data_card.render_f7_
# arrivals / render_f9_lineage consume. Every inner field list routes through
# build_card_fields (INV-01 — the card adapter pins to data_row via the parity
# test); inner eligibility is is_surface_b_card_eligible (matched + price, no
# image — the photo-less surface-B floor).
#
# HONEST-COUNT (load-bearing, branding-guide §"IG data-post copy" rev2 L182/L231):
# the cover stat names the TRUE full-population count; the carousel shows a capped
# (<= sample_cap) sample. The cover count is NEVER len(items) — a sample relabeled
# "all N" is the lie this split exists to prevent.
# ---------------------------------------------------------------------------

# F7 lead-event arms + their render mappings. The event verb set is closed (no new
# verb minted — branding-guide §"IG data-post copy" Zone A); 'just-listed' renders
# 'listed', 'back-in-stock' renders 'back in stock'.
_F7_ARRIVAL_EVENT = "just-listed"
_F7_RESTOCK_EVENT = "back-in-stock"
_F7_EVENT_PHRASE = {_F7_ARRIVAL_EVENT: "listed", _F7_RESTOCK_EVENT: "back in stock"}


def _f7_composition(rows: list[dict]) -> str:
    """The cover-copy variant key, derived from the `event` column over the FULL
    population (not the sample): all just-listed -> all-arrivals, all back-in-stock
    -> all-restocks, both present -> mixed. Empty population defaults to
    all-arrivals (true_count is 0 there; the caller skips the post)."""
    events = {r["event"] for r in rows}
    has_arrival = _F7_ARRIVAL_EVENT in events
    has_restock = _F7_RESTOCK_EVENT in events
    if has_arrival and has_restock:
        return "mixed"
    if has_restock:
        return "all-restocks"
    return "all-arrivals"


def _card_item(row: dict, *, event_phrase: str | None = None) -> dict:
    """One surface-B inner card item — the SINGLE shape F7 and F9 inners share, so
    both provably render the same Price. — Listed. row via build_card_fields
    (INV-01). name is the canonical coral name (matched-only by eligibility, so it
    is present). event_phrase is carried only for F7 (just-listed / back-in-stock);
    F9's lead is always 'listed' and its render hardcodes it, so the key is omitted
    there (no event_phrase) rather than carrying a redundant value."""
    item = {
        "name": row["named_coral_canonical_name"],
        "vendor": row["vendor_display_name"],
        "fields": build_card_fields(
            price_value=plain_price_value(row.get("current_price")),
            listed_at=row.get("event_at"),
        ),
    }
    if event_phrase is not None:
        item["event_phrase"] = event_phrase
    return item


def count_new_arrivals(conn, window_hours: int = 168) -> int:
    """Live count of just-listed arrivals over the window (default a week) — the
    count-up card's headline N (CTK-164 PB-2; branding-guide §"IG data-card motion"
    + the F7-cover "{count} new arrivals this week." copy). The FULL uncapped
    lead-event population (row_limit NULL, so a busy week is never truncated),
    just-listed only — the same population basis as select_f7_arrivals' true_count,
    narrowed to arrivals to match the "new arrivals this week." copy exactly."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) AS n FROM get_listing_lead_event(%s, %s, %s, %s)",
            (None, window_hours, [_F7_ARRIVAL_EVENT], None),
        )
        return cur.fetchone()["n"]


def select_f7_arrivals(conn, window_hours: int = 168, sample_cap: int = 9):
    """F7 arrivals/back-in-stock carousel selector. Returns
    (true_count, composition, items):
      - true_count  — the FULL count of arrival + restock lead-events over the
        window (len of the UNCAPPED get_listing_lead_event population — row_limit
        NULL, so a busy week is never silently truncated at the default 100). This
        is the honest cover count, NOT len(items).
      - composition — all-arrivals / all-restocks / mixed, over that full
        population (drives the cover copy variant).
      - items       — <= sample_cap is_surface_b_card_eligible inners, ONE per coral
        (most-recent), vendor-spread-ordered for breadth (a variety of corals AND
        vendors — not one shop's feed), each via _card_item.

    The window is a lead-event-precedence query (one row per listing, its lead
    event), event_filter-scoped to just-listed + back-in-stock — auctions are
    already gated out across all arms (CTK-042, migration 0039)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM get_listing_lead_event(%s, %s, %s, %s)",
            (None, window_hours, [_F7_ARRIVAL_EVENT, _F7_RESTOCK_EVENT], None),
        )
        rows = cur.fetchall()
    true_count = len(rows)
    composition = _f7_composition(rows)
    eligible = [r for r in rows if is_surface_b_card_eligible(r)]
    # Deterministic recency order: get_listing_lead_event orders event_at DESC with no
    # final tiebreak, so equal-event_at rows could flip run-to-run (the CTK-161 retro #2
    # shape). (event_at, id) DESC is a total order — pins the per-coral pick + the order.
    eligible.sort(key=lambda r: (r["event_at"], r["id"]), reverse=True)
    # One card per CORAL (the breadth sweetspot — a variety of corals AND vendors). Two
    # listings of the same coral, even at DIFFERENT vendors, render as near-identical
    # cards, so dedupe to the most-recent per coral (the sort above). The cover count is
    # UNCHANGED — true_count stays the full lead-event population (the honest-count
    # split); only the displayed sample dedupes.
    # LOAD-BEARING ORDER (don't drop the sort or reorder these passes): by_coral keeps
    # the FIRST row per coral, which == most-recent only because `eligible` is sorted
    # recency-DESC above; and by_coral.values() below relies on dict insertion order
    # (Python 3.7+) being that same recency order for the vendor-spread.
    by_coral: dict = {}
    for r in eligible:
        by_coral.setdefault(r["named_coral_id"], r)   # first per coral == most-recent
    # Vendor-spread: surface a fresh vendor for each top card before repeating one, so
    # the reel reads as breadth (corals AND shops), not one shop's feed. One-per-vendor
    # first (recency), same-vendor extras deferred to the tail.
    ordered: list[dict] = []
    deferred: list[dict] = []
    used_vendors: set = set()
    for r in by_coral.values():                        # recency order (dict preserves insertion)
        if r["vendor_id"] in used_vendors:
            deferred.append(r)
        else:
            ordered.append(r)
            used_vendors.add(r["vendor_id"])
    ordered += deferred
    items = [_card_item(r, event_phrase=_F7_EVENT_PHRASE[r["event"]]) for r in ordered[:sample_cap]]
    return true_count, composition, items


def select_f9_lineage(conn, sample_cap: int = 9):
    """F9 lineage-spotlight selector over get_cross_vendor_carriers(). Returns
    (coral, vendor_count, items), or None when no coral qualifies (the caller
    falls back to an A-path spotlight or an F7 inner).

    Pick: among corals carried in-stock at >= 2 distinct vendors, walk widest-
    spread-first (tie-break most-recent carrier, then coral id — deterministic) and
    take the FIRST that yields >= 1 renderable (priced) inner. The widest coral can
    be all price-on-request — that is not a reason to drop to None when a narrower
    >= 2-vendor coral is renderable (the runner-up-starvation fix). None only when
    NO >= 2-vendor coral has any priced inner.

    vendor_count is the chosen coral's TRUE distinct carrying-vendor count — image-
    blind AND price-blind (the cover is an availability claim, "at N vendors right
    now"; a price-on-request carrier still carries the coral). The inner SAMPLE is
    narrower: is_surface_b_card_eligible (priced) listings, ONE per vendor (most
    recent), recency-ordered, <= sample_cap. So vendor_count >= len(items) by
    construction — the deflated sample never relabels the cover count."""
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM get_cross_vendor_carriers()")
        rows = cur.fetchall()
    if not rows:
        return None

    by_coral: dict[int, list[dict]] = {}
    for r in rows:
        by_coral.setdefault(r["named_coral_id"], []).append(r)

    # TRUE distinct carrying vendors per coral (image-blind + price-blind) + the
    # most-recent carrier event_at per coral (the deterministic tiebreak), both
    # precomputed once so the candidate sort key is a dict lookup, not a re-scan.
    spread = {cid: len({r["vendor_id"] for r in group}) for cid, group in by_coral.items()}
    recent = {cid: max(r["event_at"] for r in group) for cid, group in by_coral.items()}
    candidates = sorted(
        (cid for cid, n in spread.items() if n >= 2),
        key=lambda cid: (spread[cid], recent[cid], cid),
        reverse=True,
    )

    for cid in candidates:
        group = by_coral[cid]
        # Inner sample: priced (card-eligible), one listing per vendor (most
        # recent), recency-ordered, capped. eligible is event_at-DESC, so iterating
        # it and keeping the first row per vendor inserts vendors into by_vendor in
        # newest-first order — the dict values are already event_at-DESC, no re-sort.
        eligible = sorted(
            (r for r in group if is_surface_b_card_eligible(r)),
            key=lambda r: (r["event_at"], r["id"]), reverse=True,
        )
        by_vendor: dict = {}
        for r in eligible:
            by_vendor.setdefault(r["vendor_id"], r)
        ordered = list(by_vendor.values())[:sample_cap]
        if ordered:
            items = [_card_item(r) for r in ordered]
            return group[0]["named_coral_canonical_name"], spread[cid], items
    return None
