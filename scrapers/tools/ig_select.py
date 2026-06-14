"""CTK-159 Slice A — Instagram spotlight content selector.

Ranks the day's lead-events for Instagram post-worthiness over the EXISTING
data plane — no new scraping, read-only. Mirrors scrapers/tools/leak_scan.py:
a pure detection/scoring core (no DB, no network — unit-driven) under an I/O
shell (get_conn + argparse).

Pipeline (Slice A — T1/T2/T3):

  T1  candidate base   — get_listing_lead_event(NULL, window_hours, NULL, NULL),
                         the locked candidate query (CTK-159 D-3). NULL row_limit
                         = uncapped (LIMIT ALL). Reusing the function inherits
                         INV-05's arm-scoped auction filter for free: migrations
                         0028/0030 bind `auction_end_time IS NULL` to the
                         price-dropped arm INSIDE the function, so price-drop
                         candidates never carry an auction. just-listed and
                         back-in-stock are auction-orthogonal by design (auctions
                         legitimately just-list and relist). A hand-rolled
                         candidate query would re-open exactly that drift surface.

  T2  hard image gate  — pre-filter, runs BEFORE scoring. IG is image-first AND
                         price-bearing; a postable spotlight needs a real
                         mirrored public image and a showable price. Drops three
                         shapes (image_gate_reject names which fired):
                           no-image          : image_url IS NULL (mirror failed,
                                               written NULL per CTK-019 #55)
                           non-mirror-image  : image_url not under MIRROR_HOST —
                                               a hotlink/raw vendor URL (rot-prone,
                                               not brand-channel-safe). Strict per
                                               CTK-159 Q2; costs nothing today
                                               (whole fleet is image_strategy
                                               'mirror') and future-proofs against
                                               a hotlink vendor leaking a raw URL
                                               into a brand post.
                           price-on-request  : current_price IS NULL (auction /
                                               null-priced — nothing to show;
                                               'price on request' per
                                               lib/format/listing-price.ts).

  T3  scoring          — weighted sort over the gated set; weights are the
                         WEIGHT_* named constants below (compute_score). v1
                         ordering (CTK-159 Q1, /brand-manager re-locks the
                         durable canon in the CTK-157 session before channel-go):
                         cross-vendor "cheapest" > named-coral + big drop >
                         drop-magnitude alone > named-coral / just-listed >
                         recency (tiebreak). Cross-vendor is a WEIGHT, not a hard
                         gate — a strong single-vendor drop still wins on a day
                         nothing crosses vendors. Three signals the tool computes
                         itself on top of T1:
                           - named-coral demand   : named_coral_id present (binary
                                                    v1; matcher covers ~20/91 named
                                                    corals early, so this + the
                                                    cross-vendor term fire rarely
                                                    at first — drop-magnitude is
                                                    the de-facto early driver, by
                                                    design).
                           - price-drop magnitude : CTK-047 medal data via
                                                    get_recent_price_drops(days) —
                                                    the canonical medal surface;
                                                    already carries INV-05 on both
                                                    arms. pct = drop fraction,
                                                    clamped 0..1.
                           - cross-vendor cheapest: lowest current_price among
                                                    in_stock, NON-AUCTION, priced
                                                    listings sharing a
                                                    named_coral_id, where >=2
                                                    DISTINCT vendors carry it.
                                                    INV-05 RESIDUAL (D-3): this
                                                    query runs over the full
                                                    vendor_listings population, NOT
                                                    the gated candidate set, so it
                                                    must INDEPENDENTLY carry all
                                                    three predicates: in_stock =
                                                    true AND auction_end_time IS
                                                    NULL AND current_price IS NOT
                                                    NULL. The auction predicate is
                                                    the INV-05 residual D-3 named;
                                                    in_stock + non-null price are
                                                    the OOS/phantom guards (don't
                                                    crown a sold-out or
                                                    price-on-request row "cheapest").

Output (Slice A): top-1/day (daily) + weekly top-N roundup (weekly-roundup).
The publish-or-notify adapter — image + caption skeleton + metadata + notify —
is Slice B, gated on the CTK-157 caption canon.

Run via:
  python -m scrapers.tools.ig_select [--mode daily|weekly-roundup] [--top-n N]

Reads NEON_DATABASE_URL from .env via scrapers.common.db's load_dotenv().
Exit 0 on a clean run; 1 only on error (loud-failure posture).
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

# Mirrored-image host. Single source of truth is
# scrapers/common/images.py:_PUBLIC_HOST (the mirror WRITER); kept as a local
# const here so the selector's import graph stays light (images.py drags in
# boto3 + Pillow) and the gate predicate derives from ONE name rather than an
# inlined literal (CTK-159 Q2 refinement). A drift-guard unit test asserts this
# equals images._PUBLIC_HOST so a custom-domain change can't silently diverge.
MIRROR_HOST = "https://images.coralticker.com"

# Per-mode observation window. daily = today's events; weekly-roundup = 7d.
WINDOW_HOURS = {"daily": 24, "weekly-roundup": 168}

# Per-mode default selection size. daily picks the single best spotlight;
# weekly-roundup assembles a top-N candidate set (override with --top-n).
DEFAULT_TOP_N = {"daily": 1, "weekly-roundup": 7}

# ---------------------------------------------------------------------------
# IG-worthiness weights (CTK-159 Q1 — v1 DEFAULTS, not the durable canon).
# /brand-manager re-locks these in the CTK-157 session before channel-go; the
# values below encode the v1 ordering and are deliberately NOT tuned against a
# few sparse early days (named-coral + cross-vendor terms fire rarely until the
# matcher expands past ~20/91 corals — Jon guardrail).
#
# Ordering they produce (most→least postable), for a meaningful drop:
#   cross-vendor cheapest  (+100 flat; the unfair-advantage post only we can make)
#   named-coral + big drop (30 + 80*pct; e.g. pct .6 -> 78)
#   drop-magnitude alone   (80*pct;     e.g. pct .6 -> 48)
#   named-coral / just-listed (30 / 0)
#   recency                (<=10; tiebreak only)
# Cross-vendor is additive, not a gate: a strong single-vendor drop (drop term)
# still wins on a day nothing crosses vendors.
WEIGHT_CROSS_VENDOR_CHEAPEST = 100.0
WEIGHT_PRICE_DROP_MAGNITUDE = 80.0   # multiplied by drop fraction (0..1)
WEIGHT_NAMED_CORAL = 30.0            # binary: named_coral_id present
WEIGHT_RECENCY = 10.0               # multiplied by recency factor (0..1)

# Title truncation in the printed line — keep it scannable.
TITLE_TRUNC = 70


# ---------------------------------------------------------------------------
# Pure core — no DB, no network. Tests drive these directly.
# ---------------------------------------------------------------------------


@dataclass
class Candidate:
    """One lead-event row, normalized for selection. Scoring fields land in T3.

    `arm` is the lead event from get_listing_lead_event: 'just-listed' |
    'price-dropped' | 'back-in-stock'. Prices are Decimal (numeric) or None.
    """
    listing_id: int
    vendor_slug: str
    vendor_display_name: str
    raw_title: str
    coral_name: str | None
    coral_slug: str | None
    named_coral_id: int | None
    arm: str
    event_at: datetime
    current_price: Decimal | None
    prior_price: Decimal | None
    compare_at_price: Decimal | None
    image_url: str | None
    product_url: str

    # Scoring fields — populated by the I/O shell before rank() (T3).
    medal_pct: float = 0.0
    is_cross_vendor_cheapest: bool = False
    score: float = 0.0
    score_breakdown: dict | None = None

    @classmethod
    def from_row(cls, row: dict) -> "Candidate":
        """Build from a get_listing_lead_event result row (dict_row factory)."""
        return cls(
            listing_id=row["id"],
            vendor_slug=row["vendor_slug"],
            vendor_display_name=row["vendor_display_name"],
            raw_title=row.get("raw_title") or "",
            coral_name=row.get("named_coral_canonical_name"),
            coral_slug=row.get("named_coral_slug"),
            named_coral_id=row.get("named_coral_id"),
            arm=row["event"],
            event_at=row["event_at"],
            current_price=row.get("current_price"),
            prior_price=row.get("prior_price"),
            compare_at_price=row.get("compare_at_price"),
            image_url=row.get("image_url"),
            product_url=row.get("product_url") or "",
        )


def image_gate_reject(c: Candidate) -> str | None:
    """Return the drop-reason if this candidate fails the hard pre-filter, else
    None. The gate predicate is derived from MIRROR_HOST (no inlined literal);
    a non-mirror or absent image, or a null price, is not postable. Reason order
    is image-before-price so a row that fails both surfaces the image cause."""
    if c.image_url is None:
        return "no-image"
    if not c.image_url.startswith(MIRROR_HOST + "/"):
        return "non-mirror-image"
    if c.current_price is None:
        return "price-on-request"
    return None


def passes_image_gate(c: Candidate) -> bool:
    """True when the candidate clears the hard pre-filter (T2)."""
    return image_gate_reject(c) is None


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


def recency_factor(event_at: datetime, now: datetime, window_hours: int) -> float:
    """Linear recency in [0, 1]: 1.0 at now, decaying to 0 at the window edge.
    A just-fired event tiebreaks above a window-old one of equal weight."""
    if window_hours <= 0:
        return 0.0
    age_hours = (now - event_at).total_seconds() / 3600.0
    return max(0.0, min(1.0, 1.0 - age_hours / window_hours))


def compute_score(
    *,
    has_named_coral: bool,
    medal_pct: float,
    is_cross_vendor_cheapest: bool,
    recency: float,
) -> tuple[float, dict]:
    """The IG-worthiness score (T3). Additive weighted sum; returns
    (total, breakdown) so the printed/emitted candidate can show WHY it ranked.
    Cross-vendor is additive (not a gate) per Q1 guardrail."""
    cross = WEIGHT_CROSS_VENDOR_CHEAPEST if is_cross_vendor_cheapest else 0.0
    named = WEIGHT_NAMED_CORAL if has_named_coral else 0.0
    drop = WEIGHT_PRICE_DROP_MAGNITUDE * max(0.0, min(1.0, medal_pct))
    rec = WEIGHT_RECENCY * max(0.0, min(1.0, recency))
    total = cross + named + drop + rec
    return total, {
        "cross_vendor_cheapest": cross,
        "named_coral": named,
        "drop_magnitude": round(drop, 2),
        "recency": round(rec, 2),
    }


def cross_vendor_cheapest_ids(rows: list[dict]) -> set[int]:
    """Pure: from named-coral listing rows, return the ids that are the cheapest
    of their named_coral across >=2 DISTINCT vendors. Applies the three
    eligibility predicates itself — named_coral_id present, in_stock, NON-AUCTION
    (auction_end_time IS NULL), priced (current_price not None) — so the INV-05
    residual (D-3) and the OOS/phantom guards hold even if handed an unfiltered
    set. Defense in depth with the SQL WHERE in fetch_cross_vendor_cheapest.

    Genuine price ties yield >1 cheapest id (both ARE the cheapest). Prices
    (Decimal) are compared directly — exact, so a cent-for-cent tie is detected
    without float-rounding hazard."""
    eligible = [
        r for r in rows
        if r.get("named_coral_id") is not None
        and r.get("in_stock") is True
        and r.get("auction_end_time") is None
        and r.get("current_price") is not None
    ]
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


def rank(candidates: list[Candidate], top_n: int) -> list[Candidate]:
    """Sort scored candidates by score desc, event_at desc as the tiebreak,
    and return the top_n. Assumes .score / .event_at are populated."""
    ordered = sorted(candidates, key=lambda c: (c.score, c.event_at), reverse=True)
    return ordered[:top_n] if top_n and top_n > 0 else ordered


# ---------------------------------------------------------------------------
# I/O shell — DB read + orchestration.
# ---------------------------------------------------------------------------


def fetch_candidates(conn, window_hours: int) -> list[Candidate]:
    """T1 — the locked candidate base. get_listing_lead_event(NULL,
    window_hours, NULL, NULL): fleet-wide, any lead arm, uncapped. INV-05 is
    inherited arm-scoped inside the function (see module docstring)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM get_listing_lead_event(NULL, %s, NULL, NULL)",
            (window_hours,),
        )
        rows = cur.fetchall()
    return [Candidate.from_row(r) for r in rows]


def fetch_medal_magnitudes(conn, window_days: int) -> dict[int, float]:
    """T3 — CTK-047 medal magnitude per listing via the canonical medal surface
    get_recent_price_drops(p_window_days). Already carries INV-05 on both arms
    (CT-observed drop + vendor markdown) — no residual to re-assert here.
    Returns {listing_id: drop_fraction}; the max fraction per listing if a row
    appears under more than one arm."""
    out: dict[int, float] = {}
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM get_recent_price_drops(%s)", (window_days,))
        for r in cur.fetchall():
            frac = drop_fraction(r.get("prior_price"), r.get("current_price"), r.get("compare_at_price"))
            lid = r["id"]
            if frac > out.get(lid, 0.0):
                out[lid] = frac
    return out


def fetch_cross_vendor_cheapest(conn) -> set[int]:
    """T3 / T3-INV05 — listing_ids that are the cheapest of their named_coral
    across >=2 distinct vendors. Runs over the FULL vendor_listings population
    (NOT the gated candidate set), so the SELECT independently carries all three
    predicates D-3 named: in_stock = true AND auction_end_time IS NULL (the
    INV-05 residual) AND current_price IS NOT NULL (OOS/phantom guard). The
    >=2-vendor + cheapest ranking is computed by the pure cross_vendor_cheapest_ids
    (which re-asserts the same predicates — defense in depth)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, vendor_id, named_coral_id, current_price, in_stock, auction_end_time "
            "FROM vendor_listings "
            "WHERE named_coral_id IS NOT NULL "
            "  AND in_stock = true "
            "  AND auction_end_time IS NULL "
            "  AND current_price IS NOT NULL"
        )
        rows = cur.fetchall()
    return cross_vendor_cheapest_ids(rows)


def score_candidates(
    candidates: list[Candidate],
    medal_by_id: dict[int, float],
    cross_vendor_ids: set[int],
    now: datetime,
    window_hours: int,
) -> None:
    """Populate .medal_pct / .is_cross_vendor_cheapest / .score / .score_breakdown
    on each candidate in place (T3)."""
    for c in candidates:
        c.medal_pct = medal_by_id.get(c.listing_id, 0.0)
        c.is_cross_vendor_cheapest = c.listing_id in cross_vendor_ids
        c.score, c.score_breakdown = compute_score(
            has_named_coral=c.named_coral_id is not None,
            medal_pct=c.medal_pct,
            is_cross_vendor_cheapest=c.is_cross_vendor_cheapest,
            recency=recency_factor(c.event_at, now, window_hours),
        )


def _format_line(c: Candidate) -> str:
    title = c.raw_title if len(c.raw_title) <= TITLE_TRUNC else c.raw_title[:TITLE_TRUNC - 1] + "…"
    coral = f" [{c.coral_name}]" if c.coral_name else ""
    price = f"${c.current_price}" if c.current_price is not None else "price-on-request"
    xv = " +cross-vendor-cheapest" if c.is_cross_vendor_cheapest else ""
    return (f"  score={c.score:6.1f}{xv} [{c.vendor_slug}] id={c.listing_id}{coral} "
            f"{title!r} — {c.arm} — {price} — {c.product_url}")


def run(mode: str, top_n: int) -> int:
    from scrapers.common import db

    window_hours = WINDOW_HOURS[mode]
    # get_recent_price_drops takes DAYS; ceil the hours window (24h->1d, 168h->7d).
    window_days = max(1, -(-window_hours // 24))
    now = datetime.now(timezone.utc)

    conn = db.get_conn()
    try:
        candidates = fetch_candidates(conn, window_hours)
        gated = [c for c in candidates if passes_image_gate(c)]
        medal_by_id = fetch_medal_magnitudes(conn, window_days)
        cross_vendor_ids = fetch_cross_vendor_cheapest(conn)
    finally:
        conn.close()

    score_candidates(gated, medal_by_id, cross_vendor_ids, now, window_hours)
    selected = rank(gated, top_n)

    print(f"ig-select {mode}: {len(candidates)} candidate(s), {len(gated)} pass image gate, "
          f"selecting top {top_n}")
    for c in selected:
        print(_format_line(c))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mode", choices=("daily", "weekly-roundup"), default="daily",
                        help="Selection window + size (daily top-1 / weekly-roundup top-N).")
    parser.add_argument("--top-n", type=int, default=None,
                        help="Override the per-mode default selection size.")
    args = parser.parse_args()
    top_n = args.top_n if args.top_n is not None else DEFAULT_TOP_N[args.mode]
    try:
        return run(args.mode, top_n)
    except Exception as e:  # noqa: BLE001 — surface loudly, exit 1 (loud-failure posture)
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
