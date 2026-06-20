"""CTK-161 driver glue — wire the F7/F8/F9 selectors to the data_card renderers.

Thin orchestration only: each format = select (content_queries) -> render
(data_card). The driver fetches via the selectors and feeds the renderers; it does
NOT re-shape fields. INV-01 is pinned at the renderers (build_card_fields ->
format_data_row_html, test_data_row_parity) — selector output passes straight
through. The F8 headline %/name are derived from the SAME row the INV-01 fields
render from (superlative_pct shares superlative_fields' baseline -> %-parity).

A selector returning None is a CLEAN SKIP, not an error — that format produces no
post this run:
  - F8: select_superlative_drop -> None when no drop clears the glitch + worthiness
    gates this week (skip F8, never a forced weak superlative).
  - F9: select_f9_lineage -> None when no >= 2-vendor coral has a renderable inner.
  - F7: skipped here when no inner renders (an item-less carousel is not a post).

================================================================================
RUNBOOK — get_cross_vendor_carriers() (F9 dependency; LIVE on prod Neon)
================================================================================
F9 (build_f9 / select_f9_lineage) calls get_cross_vendor_carriers(), created in
  supabase/migrations/0043_get_cross_vendor_carriers.sql
and superseded on prod by
  supabase/migrations/0044_get_cross_vendor_carriers_tiebreak.sql  (DROP + CREATE
  with the deterministic `vl.id DESC` tiebreak — CTK-161 retro #2 fold)
which is APPLIED + verified on prod Neon. The F9 path runs against the live
function; no apply step gates a content-card run.

Historical context: before the function landed, the F9 path raised psycopg
UndefinedFunction (SQLSTATE 42883) on the SELECT — by design, the loud signal that
a deploy had run ahead of the schema (the driver never caught it: a missing
function is a deploy-ordering error, not a clean no-post). With the function live
this no longer fires.

If a FUTURE migration ever drops the function, re-apply BEFORE the next scheduled
content-card run that includes F9. Canonical re-apply path is the CURRENT (0044)
body — NOT apply_migration_0043.py, whose body predates the tiebreak and would
revert it:
  psql "$NEON_DATABASE_URL" -f supabase/migrations/0044_get_cross_vendor_carriers_tiebreak.sql   (after . .env)

F7 and F8 touch neither the function nor F9. To bank a subset (e.g. F7/F8 only),
restrict with --only f7,f8 (or run_all(..., only={"f7","f8"})).

Run:
  python -m scrapers.tools.content_cards [--out-dir build/cards] [--only f7,f8,f9]

Reads NEON_DATABASE_URL from the environment (.env via scrapers.common.db). The
rendered MP4s land in --out-dir (the operator grabs them — same posture as the
ig_spotlight reels). Exit 0 on a clean run; 1 on error (loud-failure posture).
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from scrapers.tools import content_queries as cq
from scrapers.tools import data_card

DEFAULT_OUT_DIR = "build/cards"

# CTK-173 follow-on — the F7/F9 closer-card on-image line (final carousel slide).
# CONFIRMED 2026-06-19 (Jon + /brand-manager): "Full feed at coralticker.com." — the
# coralticker.com domain renders bold near-black, "Full feed at" + the period regular
# weight, no forest (treatment in build_closer + reel-frame-closer.html). "link in bio"
# is caption-only canon and must NOT appear on the card.
_CLOSER_LINE = "Full feed at coralticker.com."

# Output filename per format. One file per format per run (overwritten); the
# grid-stocking batch banks them in out_dir for the operator to post.
_OUT_NAME = {
    "f7": "f7-arrivals.mp4",
    "f8": "f8-superlative.mp4",
    "f9": "f9-lineage.mp4",
}


def build_f7(conn, *, now: datetime, out_dir: str | Path) -> Path | None:
    """F7 arrivals/back-in-stock carousel: select -> render, or None (clean skip)
    when no inner renders. The cover count + composition pass straight through from
    the selector — the honest-count surface (cover names the TRUE full-window count;
    composition picks the cover copy; both derived over the full population, not the
    capped sample)."""
    true_count, composition, items = cq.select_f7_arrivals(conn)
    if not items:
        return None
    return data_card.render_f7_arrivals(
        count=true_count,
        composition=composition,
        items=items,
        now=now,
        closer_line=_CLOSER_LINE,
        out_path=Path(out_dir) / _OUT_NAME["f7"],
    )


def build_f8(conn, *, now: datetime, out_dir: str | Path) -> Path | None:
    """F8 superlative single: select -> render, or None (clean skip) when no drop
    clears the glitch + worthiness gates. fields pass straight through
    superlative_fields (INV-01); pct + name derive from the SAME row, so the
    headline % can never disagree with the rendered Price. pair (%-parity gate).

    Renders the ANIMATED reveal/strike-draw card (render_f8_reveal — CTK-172 locked:
    plain headline reveal + un-struck-hold strike-draw on the Price). NOTE: from
    CTK-161's first commit through 2026-06-19 this called render_f8_superlative (the
    static Ken Burns single-card), so production F8 never animated — CTK-172 built the
    reveal path + template + tests but the driver was never repointed. Fixed here; the
    held end-frame is INV-01 byte-identical to the static card, so only the motion
    changed."""
    row = cq.select_superlative_drop(conn)
    if row is None:
        return None
    return data_card.render_f8_reveal(
        name=row["named_coral_canonical_name"],
        pct=cq.superlative_pct(row),
        fields=cq.superlative_fields(row),
        now=now,
        out_path=Path(out_dir) / _OUT_NAME["f8"],
    )


def build_f9(conn, *, now: datetime, out_dir: str | Path) -> Path | None:
    """F9 lineage spotlight: select -> render, or None (clean skip) when no
    >= 2-vendor coral has a renderable inner. Calls get_cross_vendor_carriers(),
    live on prod (migration 0044; see the module runbook). Were the function ever
    dropped this would raise UndefinedFunction here (NOT None) — a deploy-ordering
    error, not a clean no-post. coral / vendor_count / items pass straight through
    from the selector."""
    result = cq.select_f9_lineage(conn)
    if result is None:
        return None
    coral, vendor_count, items = result
    return data_card.render_f9_lineage(
        coral=coral,
        vendor_count=vendor_count,
        items=items,
        now=now,
        closer_line=_CLOSER_LINE,
        out_path=Path(out_dir) / _OUT_NAME["f9"],
    )


_BUILDERS = {"f7": build_f7, "f8": build_f8, "f9": build_f9}
_ORDER = ("f7", "f8", "f9")


def run_all(conn, *, now: datetime | None = None, out_dir: str | Path = DEFAULT_OUT_DIR,
            only: set[str] | None = None) -> dict[str, Path | None]:
    """Run the selected format builders in order (F7, F8, F9) and return
    {format: Path | None}. None means a clean skip (nothing to post for that
    format). One `now` is captured for the whole run so every relative-time field is
    consistent across the cards. `only` restricts to a subset (e.g. {"f7", "f8"} to
    bank a subset without F9). get_cross_vendor_carriers() is live on prod (0044), so
    F9 runs against the live function; were it ever dropped, F9 would raise loudly
    (deploy-ordering, per the runbook) rather than skip."""
    now = now or datetime.now(timezone.utc)
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    formats = [f for f in _ORDER if only is None or f in only]
    return {f: _BUILDERS[f](conn, now=now, out_dir=out_dir) for f in formats}


# ---------------------------------------------------------------------------
# I/O shell — conn lifecycle + the operator-facing run summary.
# ---------------------------------------------------------------------------


def _parse_only(value: str | None) -> set[str] | None:
    if value is None:
        return None
    keys = {k.strip().lower() for k in value.split(",") if k.strip()}
    bad = keys - set(_BUILDERS)
    if bad:
        raise SystemExit(f"--only: unknown format(s) {sorted(bad)} (expected f7 / f8 / f9)")
    return keys


def run(out_dir: str | Path, only: set[str] | None = None) -> int:
    from scrapers.common import db

    conn = db.get_conn()
    try:
        results = run_all(conn, out_dir=out_dir, only=only)
    finally:
        conn.close()

    for f in _ORDER:
        if f in results:
            path = results[f]
            print(f"{f}: {('rendered -> ' + str(path)) if path is not None else 'skipped (nothing to post)'}")
    rendered = sum(1 for p in results.values() if p is not None)
    print(f"content-cards: {rendered}/{len(results)} rendered to {out_dir}.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR,
                        help="Output dir for the rendered MP4s (default build/cards).")
    parser.add_argument("--only", default=None,
                        help="Comma list of formats to run (f7,f8,f9). Use 'f7,f8' to "
                             "bank a subset without F9.")
    args = parser.parse_args()
    try:
        return run(args.out_dir, only=_parse_only(args.only))
    except Exception as e:  # noqa: BLE001 — surface loudly, exit 1 (loud-failure posture)
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
