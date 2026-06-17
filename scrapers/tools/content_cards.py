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
RUNBOOK — migration 0043 apply ordering (HARD GATE for F9; Jon-side step)
================================================================================
F9 (build_f9 / select_f9_lineage) calls get_cross_vendor_carriers(), defined in
  supabase/migrations/0043_get_cross_vendor_carriers.sql
which is WRITTEN but NOT YET APPLIED to prod Neon. Until 0043 is applied the F9
path raises psycopg UndefinedFunction (SQLSTATE 42883) on the SELECT — BY DESIGN:
the loud signal that the deploy ran ahead of the schema. The driver does NOT catch
it (a missing function is a deploy-ordering error, not a clean no-post).

DEPLOY MUST NOT PRECEDE THE APPLY. Apply 0043 first (Jon-side, canonical path):
  python scripts/apply_migration_0043.py            # apply + verify
  # or: psql "$NEON_DATABASE_URL" -f supabase/migrations/0043_get_cross_vendor_carriers.sql   (after . .env)

CRON-WINDOW RACE (migration-state hazard): apply 0043 BEFORE the first scheduled
content-card run that includes F9, or that run fails F9 loudly. F7 and F8 touch
neither 0043 nor get_cross_vendor_carriers and run regardless. To bank F7/F8 before
the apply, restrict with --only f7,f8 (or run_all(..., only={"f7","f8"})).

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
        out_path=Path(out_dir) / _OUT_NAME["f7"],
    )


def build_f8(conn, *, now: datetime, out_dir: str | Path) -> Path | None:
    """F8 superlative single: select -> render, or None (clean skip) when no drop
    clears the glitch + worthiness gates. fields pass straight through
    superlative_fields (INV-01); pct + name derive from the SAME row, so the
    headline % can never disagree with the rendered Price. pair (%-parity gate)."""
    row = cq.select_superlative_drop(conn)
    if row is None:
        return None
    return data_card.render_f8_superlative(
        name=row["named_coral_canonical_name"],
        pct=cq.superlative_pct(row),
        fields=cq.superlative_fields(row),
        now=now,
        out_path=Path(out_dir) / _OUT_NAME["f8"],
    )


def build_f9(conn, *, now: datetime, out_dir: str | Path) -> Path | None:
    """F9 lineage spotlight: select -> render, or None (clean skip) when no
    >= 2-vendor coral has a renderable inner. REQUIRES migration 0043 applied (see
    the module runbook) — an unapplied 0043 raises UndefinedFunction here, NOT None.
    coral / vendor_count / items pass straight through from the selector."""
    result = cq.select_f9_lineage(conn)
    if result is None:
        return None
    coral, vendor_count, items = result
    return data_card.render_f9_lineage(
        coral=coral,
        vendor_count=vendor_count,
        items=items,
        now=now,
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
    bank the no-0043 formats before applying 0043); F9 with 0043 unapplied raises
    loudly (deploy-ordering, per the runbook), only after F7/F8 have banked."""
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
                             "bank the no-0043 formats before applying migration 0043.")
    args = parser.parse_args()
    try:
        return run(args.out_dir, only=_parse_only(args.only))
    except Exception as e:  # noqa: BLE001 — surface loudly, exit 1 (loud-failure posture)
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
