"""scrapers/tests/test_content_cards.py — CTK-161 driver glue (content_cards.py).

Exercises the select -> render ORCHESTRATION purely: the three render functions are
swapped for spies, so no Chromium / ffmpeg is touched (the real render path is the
chromium-gated job in test_rasterize / test_video). What this pins:
  - None from a selector is a clean SKIP (render not called, builder returns None).
  - F7 with no eligible inner is a skip (item-less carousel is not a post).
  - selector output passes STRAIGHT THROUGH to the renderer (no field re-shaping).
  - F8 name/pct/fields derive from the same row; pct == the rendered Price. pair %.
  - run_all order + the --only subset (banking f7/f8 before the 0043 apply).

Pure: no DB, no browser. Runnable as:
  python -m scrapers.tests.test_content_cards
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import scrapers.tools.data_card as data_card
from scrapers.tools import content_cards as cc


# --- a canned-row conn, mirroring test_content_queries._FakeConn ------------

# A warm anchor sentinel — any non-None prior_run_finished_at means "we watched it
# appear" (not cold-start). The CTK-191 F7 guard only checks None vs not-None.
_WARM_ANCHOR = datetime(2000, 1, 1, tzinfo=timezone.utc)


def _guard_dispatch(sql, params):
    """No-op response for the CTK-191 F7 guard's two side queries, so a canned-row
    conn answers select_f7_arrivals' FULL query set (lead-event + cold-start anchor
    + trailing baseline): every just-listed row reads warm (not cold-start) and
    there is no trailing baseline (threshold falls to the ABS_FLOOR), making the
    guard a no-op over these orchestration fixtures. Returns None when `sql` is not
    a guard query — the caller falls back to its own canned rows."""
    if "scraper_runs" in sql:                        # fetch_arrival_anchors
        ids = (params[0] if params else []) or []
        return [{"id": i, "prior_run_finished_at": _WARM_ANCHOR} for i in ids]
    if "first_seen_at" in sql:                        # fetch_trailing_daily_arrivals
        return []
    return None


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows
        self._result = rows

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        guard = _guard_dispatch(sql, params)
        self._result = self._rows if guard is None else guard

    def fetchall(self):
        return self._result

    def fetchone(self):
        return self._result[0] if self._result else None


class _FakeConn:
    def __init__(self, rows):
        self._rows = rows

    def cursor(self):
        return _FakeCursor(self._rows)


# A conn that dispatches by SQL function name, so run_all (which calls several
# selectors over one conn) gets the right row shape per format — get_recent_price_
# drops returns drop rows, get_cross_vendor_carriers returns carriers, etc.
_SQL_KEY = {
    "get_listing_lead_event": "f7",
    "get_recent_price_drops": "f8",
    "get_cross_vendor_carriers": "f9",
}


class _DispatchCursor:
    def __init__(self, by_format):
        self._by_format = by_format
        self._rows: list = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        guard = _guard_dispatch(sql, params)          # CTK-191 anchor / trailing no-op
        if guard is not None:
            self._rows = guard
            return
        for fn, fmt in _SQL_KEY.items():
            if fn in sql:
                self._rows = self._by_format.get(fmt, [])
                return
        self._rows = []

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _MultiConn:
    """conn returning per-format rows keyed by the SQL function the selector runs."""

    def __init__(self, **by_format):
        self._by_format = by_format

    def cursor(self):
        return _DispatchCursor(self._by_format)


# --- render spies (swap the chromium/ffmpeg path for a recorder) ------------


class _Recorder:
    def __init__(self):
        self.calls: dict[str, dict] = {}

    def _make(self, fmt):
        def _fn(**kwargs):
            self.calls[fmt] = kwargs
            return Path(f"/fake/{fmt}.mp4")
        return _fn


_RENDER_ATTRS = {
    "f7": "render_f7_arrivals",
    "f8": "render_f8_reveal",        # CTK-161 driver fix: F8 renders the animated reveal, not static
    "f9": "render_f9_lineage",
}


def _with_spies(body):
    """Run body(rec) with data_card's three render functions swapped for spies; the
    driver looks them up as data_card.<attr> at call time, so attribute-patching the
    module catches every build_*/run_all path."""
    rec = _Recorder()
    saved = {f: getattr(data_card, attr) for f, attr in _RENDER_ATTRS.items()}
    for f, attr in _RENDER_ATTRS.items():
        setattr(data_card, attr, rec._make(f))
    try:
        body(rec)
    finally:
        for f, attr in _RENDER_ATTRS.items():
            setattr(data_card, attr, saved[f])


NOW = None  # run_all defaults now; the spies ignore it.


# --- row factories (only the fields each selector reads) --------------------


def _drop_row(**kw):
    base = {
        "named_coral_id": 1,
        "named_coral_canonical_name": "WWC Sunkist Bounce Mushroom",
        "named_coral_origin_vendor": "WWC",
        "image_url": None,
        "current_price": Decimal("455"),
        "prior_price": Decimal("650"),
        "compare_at_price": None,
        "event_at": "2026-06-16T12:00:00Z",
    }
    base.update(kw)
    return base


def _le_row(event, *, coral_id=1, coral="WWC Sunkist Bounce", vendor="WWC",
            vendor_id=10, price=Decimal("250"), at="2026-06-16T12:00:00Z", id=1):
    return {
        "id": id,
        "event": event,
        "named_coral_id": coral_id,
        "named_coral_canonical_name": coral,
        "vendor_id": vendor_id,
        "vendor_display_name": vendor,
        "current_price": price,
        "event_at": at,
    }


def _carrier(*, id=1, coral_id=1, coral="WWC Sunkist Bounce", vendor_id=10, vendor="WWC",
             price=Decimal("250"), at="2026-06-16T12:00:00Z"):
    return {
        "id": id,
        "named_coral_id": coral_id,
        "named_coral_canonical_name": coral,
        "vendor_id": vendor_id,
        "vendor_display_name": vendor,
        "current_price": price,
        "event_at": at,
    }


# --- F8 ---------------------------------------------------------------------


def test_f8_none_is_clean_skip():
    def body(rec):
        # No drop clears the gates -> selector None -> render NOT called, builder None.
        assert cc.build_f8(_FakeConn([]), now=NOW, out_dir="/tmp/x") is None
        assert "f8" not in rec.calls
    _with_spies(body)


def test_f8_maps_row_to_render_args_with_pct_parity():
    def body(rec):
        path = cc.build_f8(_FakeConn([_drop_row()]), now=NOW, out_dir="/tmp/x")
        assert path == Path("/fake/f8.mp4")
        call = rec.calls["f8"]
        assert call["name"] == "WWC Sunkist Bounce Mushroom"
        # fields pass straight through superlative_fields (INV-01 two-field row).
        assert [f["label"] for f in call["fields"]] == ["Price", "Listed"]
        # pct == the % of the RENDERED Price. pair (headline can't disagree w/ receipt).
        pair = call["fields"][0]["value"]
        old = float(pair["oldValue"].lstrip("$"))
        new = float(pair["newValue"].lstrip("$"))
        assert call["pct"] == round((old - new) / old * 100) == 30
        assert call["out_path"] == Path("/tmp/x/f8-superlative.mp4")
    _with_spies(body)


# --- F9 ---------------------------------------------------------------------


def test_f9_none_is_clean_skip():
    def body(rec):
        # Single-vendor coral -> selector None -> render NOT called.
        rows = [_carrier(vendor_id=10), _carrier(vendor_id=10)]
        assert cc.build_f9(_FakeConn(rows), now=NOW, out_dir="/tmp/x") is None
        assert "f9" not in rec.calls
    _with_spies(body)


def test_f9_passes_selector_tuple_through():
    def body(rec):
        rows = [
            _carrier(vendor_id=10, vendor="WWC", at="2026-06-16T12:00:00Z"),
            _carrier(vendor_id=11, vendor="TSA", at="2026-06-15T12:00:00Z"),
        ]
        path = cc.build_f9(_FakeConn(rows), now=NOW, out_dir="/tmp/x")
        assert path == Path("/fake/f9.mp4")
        call = rec.calls["f9"]
        assert call["coral"] == "WWC Sunkist Bounce"
        assert call["vendor_count"] == 2
        assert [it["vendor"] for it in call["items"]] == ["WWC", "TSA"]   # straight through
        assert call["out_path"] == Path("/tmp/x/f9-lineage.mp4")
    _with_spies(body)


# --- F7 ---------------------------------------------------------------------


def test_f7_no_inner_is_clean_skip():
    def body(rec):
        # Population exists but nothing card-eligible (unmatched) -> no inner -> skip.
        rows = [_le_row("just-listed", coral_id=None)]
        assert cc.build_f7(_FakeConn(rows), now=NOW, out_dir="/tmp/x") is None
        assert "f7" not in rec.calls
    _with_spies(body)


def test_f7_passes_count_and_composition_through():
    def body(rec):
        rows = [_le_row("back-in-stock", coral_id=1), _le_row("back-in-stock", coral_id=2)]
        path = cc.build_f7(_FakeConn(rows), now=NOW, out_dir="/tmp/x")
        assert path == Path("/fake/f7.mp4")
        call = rec.calls["f7"]
        assert call["count"] == 2
        assert call["composition"] == "all-restocks"     # honest composition, not defaulted
        assert len(call["items"]) == 2
        assert call["out_path"] == Path("/tmp/x/f7-arrivals.mp4")
    _with_spies(body)


# --- run_all ----------------------------------------------------------------


def test_run_all_only_subset_skips_f9(tmp_path):
    # --only f7,f8 banks the no-0043 formats and never touches the F9 path (the
    # get_cross_vendor_carriers query that requires migration 0043 applied).
    def body(rec):
        f8_conn = _FakeConn([_drop_row()])
        results = cc.run_all(f8_conn, out_dir=str(tmp_path), only={"f8"})
        assert set(results) == {"f8"}
        assert results["f8"] == Path("/fake/f8.mp4")
        assert "f9" not in rec.calls and "f7" not in rec.calls
    _with_spies(body)


def test_run_all_collects_per_format_results(tmp_path):
    # All three over one conn: F7 renders (restocks), F8 renders (worthy drop), F9
    # skips (single-vendor coral -> None). Proves run_all returns a per-format map
    # including skips, with each selector getting its own row shape.
    def body(rec):
        conn = _MultiConn(
            f7=[_le_row("back-in-stock", coral_id=1), _le_row("back-in-stock", coral_id=2)],
            f8=[_drop_row()],
            f9=[_carrier(vendor_id=10), _carrier(vendor_id=10)],   # one vendor -> skip
        )
        results = cc.run_all(conn, out_dir=str(tmp_path))
        assert list(results) == ["f7", "f8", "f9"]                  # F7, F8, F9 order
        assert results["f7"] == Path("/fake/f7.mp4")
        assert results["f8"] == Path("/fake/f8.mp4")
        assert results["f9"] is None                                # clean skip in the map
    _with_spies(body)


def _run_all():
    import inspect
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failures = 0
    for fn in fns:
        try:
            # tmp_path-taking tests get a throwaway dir.
            if "tmp_path" in inspect.signature(fn).parameters:
                import tempfile
                with tempfile.TemporaryDirectory() as d:
                    fn(Path(d))
            else:
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
