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
    WEIGHT_NAMED_CORAL,
    compute_score,
    cross_vendor_cheapest_ids,
    drop_fraction,
    image_gate_reject,
    rank,
    recency_factor,
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
