"""scrapers/tests/test_ig_select.py — CTK-159 Slice A unit coverage for the
Instagram spotlight selector.

Pure tests — no DB, no network. They drive the selection core
(scrapers/tools/ig_select.py) directly: the T2 image gate, the T3 scoring
weights + ordering, the cross-vendor "cheapest" computation (incl. the INV-05
residual auction-exclusion and the OOS/phantom + >=2-vendor guards), and a
drift guard pinning MIRROR_HOST to the mirror writer's _PUBLIC_HOST.

Runnable as:
  python -m scrapers.tests.test_ig_select

Coverage:
  test_mirror_host_matches_writer        MIRROR_HOST == images._PUBLIC_HOST (drift guard)
  test_gate_passes_clean                 mirror image + price -> passes
  test_gate_drops_null_image             image_url NULL -> 'no-image'
  test_gate_drops_non_mirror_image       raw/hotlink URL -> 'non-mirror-image'
  test_gate_drops_price_on_request       current_price NULL -> 'price-on-request'
  test_gate_image_reason_precedes_price  null image + null price -> image reason wins
  test_cross_vendor_cheapest_basic       cheapest of 2-vendor coral -> in set
  test_cross_vendor_excludes_auction     INV-05 residual: auction row never crowned
  test_cross_vendor_excludes_oos         sold-out (in_stock false) cheapest excluded
  test_cross_vendor_excludes_null_price  price-on-request row excluded
  test_cross_vendor_single_vendor_none   only 1 vendor carries it -> no cross-vendor signal
  test_cross_vendor_price_tie            genuine tie -> both ids crowned
  test_score_ordering_v1                 Q1 ordering holds on a representative set
  test_score_cross_vendor_not_a_gate     cross-less day: strong drop still picked;
                                         cross-vendor wins when present, gates nothing
  test_rank_top1                         daily top-1 picks the highest score
  test_rank_tiebreak_prefers_fresher     equal score -> fresher event_at wins
  test_drop_fraction_arms               CT-drop (prior) + markdown (compare_at) + clamp
  test_recency_factor_bounds            recency 1.0 at now, 0 at/after the window edge
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from scrapers.common import images
from scrapers.tools import ig_select
from scrapers.tools.ig_select import (
    Candidate,
    MIN_SPOTLIGHT_PRICE,
    MIRROR_HOST,
    PRICE_BANDS,
    RECENT_PICK_WINDOW,
    WEIGHT_BAND_BALANCE,
    WEIGHT_CROSS_VENDOR_CHEAPEST,
    WEIGHT_DROP,
    WEIGHT_NAMED_CORAL,
    WEIGHT_RECENCY,
    MedalMagnitude,
    band_overrep_penalty,
    band_shares,
    compute_score,
    cross_vendor_cheapest_ids,
    drop_fraction,
    fetch_recent_pick_bands,
    image_gate_reject,
    price_band,
    rank,
    recency_factor,
    record_picks,
    score_candidates,
)

NOW = datetime(2026, 6, 14, 12, 0, 0, tzinfo=timezone.utc)


def _cand_row(**kw) -> dict:
    """A get_listing_lead_event-shaped row; override any field."""
    base = dict(
        id=1, vendor_slug="poto", vendor_display_name="Pieces of the Ocean",
        raw_title="Rainbow Acro", named_coral_canonical_name=None,
        named_coral_slug=None, named_coral_id=None, event="just-listed",
        event_at=NOW, current_price=Decimal("49.99"), prior_price=None,
        compare_at_price=None, image_url=MIRROR_HOST + "/poto/rainbow.webp",
        product_url="https://poto.example/products/rainbow",
    )
    base.update(kw)
    return base


def _xv_row(**kw) -> dict:
    """A vendor_listings-shaped row for cross_vendor_cheapest_ids."""
    base = dict(
        id=1, vendor_id=1, named_coral_id=100, current_price=Decimal("50.00"),
        in_stock=True, auction_end_time=None,
    )
    base.update(kw)
    return base


# --- drift guard ---------------------------------------------------------

def test_mirror_host_matches_writer():
    assert MIRROR_HOST == images._PUBLIC_HOST, (
        "MIRROR_HOST diverged from the mirror writer; the image gate would pass "
        "stale or reject live mirror URLs"
    )


# --- T2 image gate -------------------------------------------------------

def test_gate_passes_clean():
    assert image_gate_reject(Candidate.from_row(_cand_row())) is None


def test_gate_drops_null_image():
    assert image_gate_reject(Candidate.from_row(_cand_row(image_url=None))) == "no-image"


def test_gate_drops_non_mirror_image():
    c = Candidate.from_row(_cand_row(image_url="https://cdn.shopify.com/x.jpg"))
    assert image_gate_reject(c) == "non-mirror-image"


def test_gate_drops_price_on_request():
    c = Candidate.from_row(_cand_row(current_price=None))
    assert image_gate_reject(c) == "price-on-request"


def test_gate_image_reason_precedes_price():
    # A row failing both surfaces the image cause first (image-before-price).
    c = Candidate.from_row(_cand_row(image_url=None, current_price=None))
    assert image_gate_reject(c) == "no-image"


def test_gate_drops_below_price_floor():
    # Today's misfire: an unmatched $9.59 frag — below MIN_SPOTLIGHT_PRICE, hard-cut.
    c = Candidate.from_row(_cand_row(current_price=Decimal("9.59")))
    assert image_gate_reject(c) == "below-price-floor"
    # At the floor it passes (boundary: < floor, not <=).
    at_floor = Candidate.from_row(_cand_row(current_price=Decimal(str(MIN_SPOTLIGHT_PRICE))))
    assert image_gate_reject(at_floor) is None
    # Image cause still precedes the floor (a below-floor row with no image -> no-image).
    no_img = Candidate.from_row(_cand_row(image_url=None, current_price=Decimal("9.59")))
    assert image_gate_reject(no_img) == "no-image"


# --- T3 cross-vendor cheapest -------------------------------------------

def test_cross_vendor_cheapest_basic():
    rows = [
        _xv_row(id=1, vendor_id=1, current_price=Decimal("60.00")),
        _xv_row(id=2, vendor_id=2, current_price=Decimal("40.00")),  # cheapest
    ]
    assert cross_vendor_cheapest_ids(rows) == {2}


def test_cross_vendor_excludes_auction():
    # INV-05 residual: a cheaper auction row must NOT be crowned cheapest.
    rows = [
        _xv_row(id=1, vendor_id=1, current_price=Decimal("60.00")),
        _xv_row(id=2, vendor_id=2, current_price=Decimal("70.00")),
        _xv_row(id=3, vendor_id=3, current_price=Decimal("10.00"),
                auction_end_time=NOW + timedelta(hours=6)),  # cheapest but auction
    ]
    # id=3 excluded entirely; id=1 is cheapest of the two eligible vendors.
    assert cross_vendor_cheapest_ids(rows) == {1}


def test_cross_vendor_excludes_oos():
    rows = [
        _xv_row(id=1, vendor_id=1, current_price=Decimal("60.00")),
        _xv_row(id=2, vendor_id=2, current_price=Decimal("80.00")),
        _xv_row(id=3, vendor_id=3, current_price=Decimal("5.00"), in_stock=False),
    ]
    assert cross_vendor_cheapest_ids(rows) == {1}


def test_cross_vendor_excludes_null_price():
    rows = [
        _xv_row(id=1, vendor_id=1, current_price=Decimal("60.00")),
        _xv_row(id=2, vendor_id=2, current_price=Decimal("80.00")),
        _xv_row(id=3, vendor_id=3, current_price=None),  # price-on-request
    ]
    assert cross_vendor_cheapest_ids(rows) == {1}


def test_cross_vendor_single_vendor_none():
    # Only one vendor carries the coral -> "cheapest" is meaningless -> no signal.
    rows = [
        _xv_row(id=1, vendor_id=1, current_price=Decimal("60.00")),
        _xv_row(id=2, vendor_id=1, current_price=Decimal("40.00")),
    ]
    assert cross_vendor_cheapest_ids(rows) == set()


def test_cross_vendor_price_tie():
    rows = [
        _xv_row(id=1, vendor_id=1, current_price=Decimal("40.00")),
        _xv_row(id=2, vendor_id=2, current_price=Decimal("40.00")),
        _xv_row(id=3, vendor_id=3, current_price=Decimal("55.00")),
    ]
    assert cross_vendor_cheapest_ids(rows) == {1, 2}


# --- T3 scoring + ranking ------------------------------------------------

def _score(has_named=False, dollars=0.0, cross=False, rec=0.0) -> float:
    total, _ = compute_score(
        has_named_coral=has_named, dollars_saved=dollars,
        is_cross_vendor_cheapest=cross, recency=rec,
    )
    return total


def test_score_ordering_v1():
    # 2026-06-17 ordering: cross-vendor dominates; then a high-$ drop; named is a
    # booster; recency only the tiebreak. No value term — absolute price doesn't score.
    cross_vendor = _score(cross=True)                  # 100
    big_drop = _score(dollars=100.0)                   # 50
    named_only = _score(has_named=True)                # 30
    recency_only = _score(rec=1.0)                     # 10
    assert cross_vendor > big_drop > named_only > recency_only


def test_score_absolute_dollar_drop_ordering():
    # The misfire fix: ABSOLUTE dollars, not percent. A 20%-off $400 piece (~$80
    # saved) outranks a 50%-off $10 frag ($5 saved) even though its percent is
    # bigger — on the dollar-drop term alone (no value term in play). (The $10 frag
    # is also below the floor — gated out upstream.)
    big = _score(dollars=80.0)
    frag = _score(dollars=5.0)
    assert big > frag


def test_score_named_is_booster_not_gate():
    # Named adds a flat +30 but does NOT gate: an unnamed high-$-drop piece still
    # outranks a named no-drop one.
    named_weak = _score(has_named=True)              # 30
    unnamed_strong = _score(dollars=100.0)            # 50
    assert unnamed_strong > named_weak
    # And the boost is purely additive — same piece, exactly +WEIGHT_NAMED_CORAL.
    assert _score(has_named=True, dollars=20.0) == _score(dollars=20.0) + WEIGHT_NAMED_CORAL


def _scored_cand(lid, *, named=False, dollars=0.0, cross=False, rec=0.0, ev=NOW):
    c = Candidate.from_row(_cand_row(id=lid, event_at=ev))
    c.score, _ = compute_score(
        has_named_coral=named, dollars_saved=dollars,
        is_cross_vendor_cheapest=cross, recency=rec,
    )
    return c


def test_score_cross_vendor_not_a_gate():
    # Guardrail (Jon): cross-vendor is a WEIGHT, not a hard gate. On a day
    # NOTHING crosses vendors, a strong single-vendor piece must still be
    # selectable (not filtered out); and when a cross-vendor row IS present it
    # wins as the top signal WITHOUT gating the others out. Exercised through
    # the real compute_score + rank, not bare score arithmetic.
    cross_less = [
        _scored_cand(1, dollars=100.0),    # strong $ drop
        _scored_cand(2, named=True),        # named-coral, no drop
        _scored_cand(3, rec=1.0),           # recency only
    ]
    # No cross-vendor bonus anywhere -> the strong piece is selected, not gated.
    assert rank(cross_less, 1)[0].listing_id == 1

    with_cross = cross_less + [_scored_cand(4, cross=True)]
    ranked = rank(with_cross, len(with_cross))
    assert ranked[0].listing_id == 4                          # top signal wins
    assert {c.listing_id for c in ranked} == {1, 2, 3, 4}     # nothing gated out


def test_rank_top1():
    def cand(lid, score, ev=NOW):
        c = Candidate.from_row(_cand_row(id=lid, event_at=ev))
        c.score = score
        return c
    cands = [cand(1, 30.0), cand(2, 78.0), cand(3, 48.0)]
    top = rank(cands, 1)
    assert [c.listing_id for c in top] == [2]


def test_rank_tiebreak_prefers_fresher():
    # Equal score -> the fresher (later) event_at wins the tiebreak, so the
    # day's pick is the more recent of two equally-weighted spotlights.
    def cand(lid, score, ev):
        c = Candidate.from_row(_cand_row(id=lid, event_at=ev))
        c.score = score
        return c
    older = cand(1, 50.0, NOW - timedelta(hours=5))
    fresher = cand(2, 50.0, NOW)
    assert [c.listing_id for c in rank([older, fresher], 1)] == [2]


# --- helpers -------------------------------------------------------------

def test_drop_fraction_arms():
    # CT-observed drop via prior_price.
    assert abs(drop_fraction(Decimal("100"), Decimal("60"), None) - 0.4) < 1e-9
    # Markdown arm: prior_price NULL, fall back to compare_at_price.
    assert abs(drop_fraction(None, Decimal("75"), Decimal("100")) - 0.25) < 1e-9
    # Neither usable -> 0.
    assert drop_fraction(None, Decimal("50"), None) == 0.0
    # Non-positive baseline guarded.
    assert drop_fraction(Decimal("0"), Decimal("0"), None) == 0.0


def test_recency_factor_bounds():
    assert recency_factor(NOW, NOW, 24) == 1.0
    assert recency_factor(NOW - timedelta(hours=24), NOW, 24) == 0.0
    assert recency_factor(NOW - timedelta(hours=48), NOW, 24) == 0.0  # clamped


# --- Item C: price bands ------------------------------------------------

def test_price_band_boundaries():
    # Lower-inclusive / upper-exclusive at every edge.
    assert price_band(25.0) == "<$150"          # floor lands in band 1
    assert price_band(149.99) == "<$150"
    assert price_band(150.0) == "$150-400"       # edge -> upper band
    assert price_band(399.99) == "$150-400"
    assert price_band(400.0) == "$400-800"
    assert price_band(799.99) == "$400-800"
    assert price_band(800.0) == "$800+"
    assert price_band(99999.0) == "$800+"
    # Decimal input bands the same as float.
    assert price_band(Decimal("150.00")) == "$150-400"
    assert price_band(Decimal("400.00")) == "$400-800"


def test_band_shares():
    assert band_shares([]) == {}
    s = band_shares(["<$150", "<$150", "$800+"])
    assert abs(s["<$150"] - 2 / 3) < 1e-9
    assert abs(s["$800+"] - 1 / 3) < 1e-9
    assert "$150-400" not in s  # absent band -> not in the map


# --- Item C: band over-representation penalty ----------------------------

def test_band_penalty_zero_without_history():
    # No recent picks (empty shares) -> no down-weight for any band.
    assert band_overrep_penalty("$400-800", {}) == 0.0
    assert band_overrep_penalty(None, {"<$150": 1.0}) == 0.0


def test_band_penalty_zero_at_or_below_fair_share():
    fair = 1.0 / len(PRICE_BANDS)  # 0.25 for the 4 seed bands
    # Exactly at fair rotation -> no penalty (only OVER-representation is penalized).
    assert band_overrep_penalty("<$150", {"<$150": fair}) == 0.0
    # Below fair -> still 0 (clamped).
    assert band_overrep_penalty("<$150", {"<$150": fair / 2}) == 0.0


def test_band_penalty_saturated_is_full_weight():
    # A band that fills the whole recent window -> the full WEIGHT_BAND_BALANCE.
    assert abs(band_overrep_penalty("$400-800", {"$400-800": 1.0}) - WEIGHT_BAND_BALANCE) < 1e-9


def test_band_penalty_monotonic_in_share():
    # More-represented -> larger down-weight (the diversity gradient).
    low = band_overrep_penalty("<$150", {"<$150": 0.5})
    high = band_overrep_penalty("<$150", {"<$150": 0.83})
    assert 0.0 < low < high <= WEIGHT_BAND_BALANCE


def test_band_balance_below_cross_vendor_margin():
    # THE D-3 guardrail as a static invariant: the max band down-weight must stay
    # STRICTLY below the cross-vendor lead, so a band-penalized cross-vendor pick
    # (100 - penalty) can never fall under an unpenalized non-cross pick (<= 90).
    max_non_cross = WEIGHT_DROP + WEIGHT_NAMED_CORAL + WEIGHT_RECENCY
    cross_margin = WEIGHT_CROSS_VENDOR_CHEAPEST - max_non_cross
    assert WEIGHT_BAND_BALANCE < cross_margin, (
        f"WEIGHT_BAND_BALANCE {WEIGHT_BAND_BALANCE} >= cross margin {cross_margin}: "
        "a saturated cross-vendor pick could be unseated by the diversity guard"
    )


# --- Item C: compute_score band term -------------------------------------

def test_compute_score_band_penalty_subtracts():
    base, _ = compute_score(has_named_coral=False, dollars_saved=100.0,
                            is_cross_vendor_cheapest=False, recency=0.0)
    penalized, bd = compute_score(has_named_coral=False, dollars_saved=100.0,
                                  is_cross_vendor_cheapest=False, recency=0.0,
                                  band_penalty=WEIGHT_BAND_BALANCE)
    assert abs(penalized - (base - WEIGHT_BAND_BALANCE)) < 1e-9
    assert bd["band_diversity"] == -round(WEIGHT_BAND_BALANCE, 2)


# --- Item C: scoring + ranking with the band guard -----------------------

def _med(**by_id):
    """{id: MedalMagnitude(dollars=...)} from id->dollars kwargs (band test fixtures)."""
    return {int(k[1:]): MedalMagnitude(fraction=0.0, dollars=v) for k, v in by_id.items()}


def test_band_guard_reorders_non_cross_picks():
    # The down-weight FLIPS order among same-tier non-cross picks. X has the bigger
    # raw drop but sits in the saturated band; Y is smaller but in a fresh band.
    #   X: drop 30 + recency 10 - penalty 8 = 32   ($500 -> "$400-800", saturated)
    #   Y: drop 25 + recency 10 - penalty 0 = 35   ($100 -> "<$150", fresh)
    x = Candidate.from_row(_cand_row(id=1, current_price=Decimal("500.00"), event_at=NOW))
    y = Candidate.from_row(_cand_row(id=2, current_price=Decimal("100.00"), event_at=NOW))
    shares = {"$400-800": 1.0}  # the whole recent window is "$400-800"
    score_candidates([x, y], _med(c1=60.0, c2=50.0), set(), NOW, 24, shares)
    assert x.band == "$400-800" and y.band == "<$150"
    assert rank([x, y], 1)[0].listing_id == 2, "fresh-band pick must win once the saturated band is penalized"
    # Control: with NO history (empty shares) the bigger raw drop wins — proving the
    # penalty, not the drop, is what flipped the order.
    x2 = Candidate.from_row(_cand_row(id=1, current_price=Decimal("500.00"), event_at=NOW))
    y2 = Candidate.from_row(_cand_row(id=2, current_price=Decimal("100.00"), event_at=NOW))
    score_candidates([x2, y2], _med(c1=60.0, c2=50.0), set(), NOW, 24, {})
    assert rank([x2, y2], 1)[0].listing_id == 1


def test_band_guard_never_unseats_cross_vendor():
    # The guardrail: even a fully-saturated band penalty leaves a cross-vendor pick
    # on top of the strongest possible non-cross pick.
    #   A (cross): 100 - penalty 8 = 92            ($500 -> "$400-800", saturated)
    #   B (non-cross, max): drop 50 + named 30 + recency 10 = 90  ($100 -> "<$150", fresh)
    a = Candidate.from_row(_cand_row(id=1, current_price=Decimal("500.00"), event_at=NOW))
    b = Candidate.from_row(_cand_row(id=2, current_price=Decimal("100.00"),
                                     named_coral_id=100, event_at=NOW))
    shares = {"$400-800": 1.0}
    score_candidates([a, b], _med(a1=0.0, b2=100.0), {1}, NOW, 24, shares)
    ranked = rank([a, b], 2)
    assert ranked[0].listing_id == 1, "a saturated-band cross-vendor pick must still top"
    assert {c.listing_id for c in ranked} == {1, 2}, "nothing gated out — soft down-weight only"


# --- Item C: pick-history I/O (offline, fake conn) -----------------------

class _FakeTxn:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        self.conn.transactions += 1
        return self

    def __exit__(self, *a):
        return False


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows
        self.calls = []
        self.many_calls = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.calls.append((sql, params))

    def executemany(self, sql, seq):
        self.many_calls.append((sql, list(seq)))

    def fetchall(self):
        return self._rows


class _FakeConn:
    def __init__(self, rows=None):
        self.cur = _FakeCursor(rows or [])
        self.transactions = 0

    def cursor(self):
        return self.cur

    def transaction(self):
        return _FakeTxn(self)


def test_fetch_recent_pick_bands_reads_window():
    conn = _FakeConn(rows=[{"band": "<$150"}, {"band": "$800+"}])
    bands = fetch_recent_pick_bands(conn, "daily")
    assert bands == ["<$150", "$800+"]
    # Mode-scoped + windowed: the query binds (mode, RECENT_PICK_WINDOW).
    _, params = conn.cur.calls[0]
    assert params == ("daily", RECENT_PICK_WINDOW)


def test_record_picks_atomic_single_round_trip():
    # #2 fold: one executemany inside one transaction (not a per-row execute loop).
    conn = _FakeConn()
    sel = [
        Candidate.from_row(_cand_row(id=11, current_price=Decimal("90.00"))),
        Candidate.from_row(_cand_row(id=12, current_price=Decimal("250.00"))),
    ]
    sel[0].band = "<$150"
    sel[1].band = "$150-400"
    n = record_picks(conn, sel, "daily")
    assert n == 2
    assert conn.transactions == 1, "insert must be wrapped in a transaction (atomic)"
    assert conn.cur.calls == [], "no per-row execute() — executemany only"
    assert len(conn.cur.many_calls) == 1, "single round-trip"
    assert conn.cur.many_calls[0][1] == [(11, "<$150", "daily"), (12, "$150-400", "daily")]
    # Empty selection -> no write, no transaction.
    conn2 = _FakeConn()
    assert record_picks(conn2, [], "daily") == 0
    assert conn2.cur.many_calls == [] and conn2.transactions == 0


def test_record_picks_bands_from_price_when_unset():
    # A candidate whose .band was not pre-set falls back to price_band(current_price).
    conn = _FakeConn()
    c = Candidate.from_row(_cand_row(id=20, current_price=Decimal("500.00")))
    assert c.band is None
    record_picks(conn, [c], "weekly-roundup")
    assert conn.cur.many_calls[0][1] == [(20, "$400-800", "weekly-roundup")]


def test_record_picks_skips_unbandable_candidate():
    # #7 guard: a candidate with neither a band nor a price is skipped, not crashed on.
    conn = _FakeConn()
    c = Candidate.from_row(_cand_row(id=30, current_price=None))
    c.band = None
    assert record_picks(conn, [c], "daily") == 0
    assert conn.cur.many_calls == []


def _run_all():
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failures = 0
    for fn in fns:
        try:
            fn()
            print(f"ok   {fn.__name__}")
        except AssertionError as e:
            failures += 1
            print(f"FAIL {fn.__name__}: {e}")
    print(f"\n{len(fns) - failures}/{len(fns)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    import sys
    sys.exit(_run_all())
