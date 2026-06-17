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
                           below-price-floor : current_price < MIN_SPOTLIGHT_PRICE
                                               (2026-06-17) — too low-value for the
                                               daily hero slot (the $9.59-frag
                                               misfire). A hard cut, not a soft score
                                               penalty; threshold from the live
                                               distribution (see results.md).

  T3  scoring          — weighted sort over the gated set; weights are the
                         WEIGHT_* named constants below (compute_score). Ordering
                         (CTK-159 Q1; drop term rebalanced 2026-06-17 after the
                         $9.59-frag misfire): cross-vendor "cheapest" dominates; then a
                         high-dollar drop; named-coral is a +30 booster (NOT a gate —
                         confirmed brand call); recency the tiebreak. The misfire fix
                         is the hard price FLOOR (T2), not a value-reward term —
                         absolute price does NOT score (see the weights note).
                         Cross-vendor is a WEIGHT, not a hard gate. Signals on top of T1:
                           - named-coral demand   : named_coral_id present (binary
                                                    booster; matcher covers ~20/91
                                                    named corals early).
                           - price-drop magnitude : CTK-047 medal data via
                                                    get_recent_price_drops(days) —
                                                    the canonical medal surface;
                                                    already carries INV-05 on both
                                                    arms. v1 scores the ABSOLUTE
                                                    dollar drop / DOLLAR_FULL (an $80
                                                    markdown beats a 50%-off $10 frag),
                                                    not the percent.
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

# Shared content-data query layer (CTK-161 D-1). fetch_cross_vendor_cheapest,
# fetch_medal_magnitudes, the pure cross_vendor_cheapest_ids ranker, and
# drop_fraction were extracted to content_queries.py so this IG selector is one
# consumer of the shared layer alongside the new content-format functions. The
# cross-vendor ranking itself promoted to SQL (get_cross_vendor_cheapest). These
# names are re-exported so existing importers (the score path below, the CTK-159
# tests) keep resolving them from ig_select.
from scrapers.tools.content_queries import (  # noqa: F401  (intentional re-export)
    MIRROR_HOST,
    MedalMagnitude,
    cross_vendor_cheapest_ids,
    drop_fraction,
    fetch_cross_vendor_cheapest,
    fetch_medal_magnitudes,
)

# MIRROR_HOST moved to content_queries (the shared layer) at the CTK-164 B-path
# build so the content-card eligibility filter can reuse it without a circular
# import; re-exported here so existing importers (test_ig_select, test_ig_spotlight)
# keep resolving ig_select.MIRROR_HOST. Single source of truth + drift-guard
# (== images._PUBLIC_HOST) unchanged — see content_queries.MIRROR_HOST.

# Per-mode observation window. daily = today's events; weekly-roundup = 7d.
WINDOW_HOURS = {"daily": 24, "weekly-roundup": 168}

# Per-mode default selection size. daily picks the single best spotlight;
# weekly-roundup assembles a top-N candidate set (override with --top-n).
DEFAULT_TOP_N = {"daily": 1, "weekly-roundup": 7}

# ---------------------------------------------------------------------------
# IG-worthiness weights (CTK-159; rebalanced 2026-06-17 after the misfire where an
# unmatched $9.59 frag won the daily slot). The misfire fix is the hard PRICE FLOOR
# (MIN_SPOTLIGHT_PRICE, a T2 gate cut), plus the drop term being ABSOLUTE DOLLARS,
# not percent (a 50%-off $10 frag saves $5; a 20%-off $400 coral saves $80 — the
# latter is the better post). Per the /brand-manager rulings 2026-06-17.
#
# NO price-VALUE reward term: the final directive dropped it. With the diversity
# guard (Item C) deferred, a value-reward would re-introduce the high-end skew the
# floor removes by subtraction — so absolute price intentionally does NOT score. The
# floor sets the lower bound; nothing rewards being expensive above it.
#
# Ordering they produce (most→least postable), realistic day:
#   cross-vendor cheapest  (+100; the dominant signal — the unfair-advantage post)
#   high-$ drop            (WEIGHT_DROP * clamp(dollars_saved / DOLLAR_FULL), up to 50)
#   named-coral booster    (+30; a booster, NOT a gate — confirmed brand call)
#   recency                (<=10; tiebreak only)
# Cross-vendor stays additive, not a gate (long-standing Q1 guardrail) — but with the
# value term gone the max non-cross score is 30+50+10 = 90 < 100, so a cross-vendor
# pick now reliably tops.
WEIGHT_CROSS_VENDOR_CHEAPEST = 100.0  # binary: dominant signal
WEIGHT_DROP = 50.0                    # * clamp(dollars_saved / DOLLAR_FULL, 0, 1)
WEIGHT_NAMED_CORAL = 30.0             # binary: named_coral_id present (booster, not a gate)
WEIGHT_RECENCY = 10.0                 # * recency factor (0..1); tiebreak

# Scoring thresholds — picked from the live in-stock candidate + dollar-drop
# distributions on prod Neon 2026-06-17 (scripts/diag_ig_spotlight_thresholds.py),
# NOT guessed. See CTK-159 results.md for the percentiles + worked examples.
#   MIN_SPOTLIGHT_PRICE  hard T2 floor — a spotlight piece must clear "modest value".
#                        $25 cuts the cheapest ~17% of in-stock candidates (p25-ish)
#                        and cuts the $9.59 misfire decisively. THE actual misfire fix.
#   DOLLAR_FULL          dollar drop at which the drop term saturates (p90 of observed
#                        drops, ~$100 — a $100 markdown is a strong drop).
MIN_SPOTLIGHT_PRICE = 25.0
DOLLAR_FULL = 100.0

# Title truncation in the printed line — keep it scannable.
TITLE_TRUNC = 70


def _clamp01(x: float) -> float:
    """Clamp to [0, 1] — the shared shape for every continuous score term."""
    return max(0.0, min(1.0, x))


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
    medal_pct: float = 0.0          # drop fraction (0..1) — informational; not scored in v1
    dollars_saved: float = 0.0      # absolute dollar drop — the scored drop magnitude
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
    """Return the drop-reason if this candidate fails the hard T2 candidate gate,
    else None. The image predicate is derived from MIRROR_HOST (no inlined literal);
    a non-mirror or absent image, or a null price, is not postable. The price FLOOR
    (below-price-floor) is the 2026-06-17 add: a piece under MIN_SPOTLIGHT_PRICE is
    too low-value for the daily hero slot (the $9.59-frag misfire) — a hard cut, not
    a soft score penalty. Reason order: image first (a row failing image surfaces the
    image cause), then price-on-request, then the floor."""
    if c.image_url is None:
        return "no-image"
    if not c.image_url.startswith(MIRROR_HOST + "/"):
        return "non-mirror-image"
    if c.current_price is None:
        return "price-on-request"
    if float(c.current_price) < MIN_SPOTLIGHT_PRICE:
        return "below-price-floor"
    return None


def passes_image_gate(c: Candidate) -> bool:
    """True when the candidate clears the hard pre-filter (T2)."""
    return image_gate_reject(c) is None


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
    dollars_saved: float,
    is_cross_vendor_cheapest: bool,
    recency: float,
) -> tuple[float, dict]:
    """The IG-worthiness score (T3). Additive weighted sum; returns
    (total, breakdown) so the printed/emitted candidate can show WHY it ranked.

    The drop term is ABSOLUTE dollars (2026-06-17): WEIGHT_DROP * clamp(dollars_saved
    / DOLLAR_FULL), so an $80 markdown outranks a 50%-off $10 frag ($5) — no percent
    kicker. Absolute price does NOT score (the final directive dropped the value-reward
    term; the floor is the only price lever — see the weights note). Cross-vendor stays
    additive (not a gate) per the Q1 guardrail."""
    cross = WEIGHT_CROSS_VENDOR_CHEAPEST if is_cross_vendor_cheapest else 0.0
    named = WEIGHT_NAMED_CORAL if has_named_coral else 0.0
    drop = WEIGHT_DROP * _clamp01(dollars_saved / DOLLAR_FULL)
    rec = WEIGHT_RECENCY * _clamp01(recency)
    total = cross + named + drop + rec
    return total, {
        "cross_vendor_cheapest": cross,
        "named_coral": named,
        "drop_dollars": round(drop, 2),
        "recency": round(rec, 2),
    }


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


def score_candidates(
    candidates: list[Candidate],
    medal_by_id: dict[int, MedalMagnitude],
    cross_vendor_ids: set[int],
    now: datetime,
    window_hours: int,
) -> None:
    """Populate .medal_pct / .dollars_saved / .is_cross_vendor_cheapest / .score /
    .score_breakdown on each candidate in place (T3). medal_by_id carries both the
    drop fraction (informational) and the absolute dollars (the scored magnitude)."""
    for c in candidates:
        mag = medal_by_id.get(c.listing_id)
        c.medal_pct = mag.fraction if mag else 0.0
        c.dollars_saved = mag.dollars if mag else 0.0
        c.is_cross_vendor_cheapest = c.listing_id in cross_vendor_ids
        c.score, c.score_breakdown = compute_score(
            has_named_coral=c.named_coral_id is not None,
            dollars_saved=c.dollars_saved,
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


def select(
    conn, mode: str, top_n: int, now: datetime | None = None
) -> tuple[list[Candidate], list[Candidate], list[Candidate]]:
    """The full selection pipeline against an open conn: fetch (T1) -> image
    gate (T2) -> score (T3) -> rank top_n. Returns (candidates, gated, selected)
    so callers see the pre-gate population, the gate survivors, and the ranked
    top_n. Read-only; does NOT close conn (the caller owns its lifecycle). `now`
    defaults to datetime.now(utc) and is injectable for deterministic tests.

    Extracted from run() at Slice-B build (CTK-159) so the publish-or-notify
    adapter (scrapers/tools/ig_spotlight.py) consumes one selection path rather
    than forking the fetch/gate/score/rank orchestration."""
    window_hours = WINDOW_HOURS[mode]
    # get_recent_price_drops takes DAYS; ceil the hours window (24h->1d, 168h->7d).
    window_days = max(1, -(-window_hours // 24))
    if now is None:
        now = datetime.now(timezone.utc)

    candidates = fetch_candidates(conn, window_hours)
    gated = [c for c in candidates if passes_image_gate(c)]
    medal_by_id = fetch_medal_magnitudes(conn, window_days)
    # fetch_cross_vendor_cheapest now returns the render-ready crowned ROWS (the
    # CTK-161 SQL function); the score path only needs the id-set membership test.
    cross_vendor_ids = {r["id"] for r in fetch_cross_vendor_cheapest(conn)}

    score_candidates(gated, medal_by_id, cross_vendor_ids, now, window_hours)
    selected = rank(gated, top_n)
    return candidates, gated, selected


def run(mode: str, top_n: int) -> int:
    from scrapers.common import db

    conn = db.get_conn()
    try:
        candidates, gated, selected = select(conn, mode, top_n)
    finally:
        conn.close()

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
