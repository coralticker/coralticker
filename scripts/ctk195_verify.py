"""CTK-195 D-1 verify — the call sites agree with the shared guarded SQL function.

Read-only differential. For each F7 count call site, compares the count the Python
content engine returns against the count of a direct get_f7_arrivals_guarded read on
the SAME live matrix, threading the SAME event_filter the call site uses:

  - count_new_arrivals      vs  get_f7_arrivals_guarded(168, ['just-listed'])
  - select_f7_arrivals[0]   vs  get_f7_arrivals_guarded(168, ['just-listed','back-in-stock'])

The invariant is pre == post, NOT a frozen number — the live 168h window rolls on
now() (788 on 2026-06-24 -> ~773 since; catalog drift, expected). What must hold is
that the Python path and the SQL function agree at a single instant.

  BEFORE the Python swap: the call sites run the in-Python _guard_arrivals; equality
  proves the SQL port reproduces the original computation (a port-fidelity bug in
  event_filter threading or the trailing-days clamp at non-default windows would
  surface here — the standalone 788 check can't catch it, both filters route the
  default window).

  AFTER the swap: the call sites consume the SQL function; equality is the regression
  smoke that the call sites still thread their filters correctly and crash-free.

Same script, meaningful both runs. Run:  PYTHONPATH=. .venv/bin/python scripts/ctk195_verify.py
"""

from __future__ import annotations

import sys

from scrapers.common.db import get_conn
from scrapers.tools import content_queries as cq

WINDOW_H = 168
ARM = cq._F7_ARRIVAL_EVENT       # "just-listed"
RESTOCK = cq._F7_RESTOCK_EVENT   # "back-in-stock"


def _sql_guarded_count(conn, event_filter) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) AS n FROM get_f7_arrivals_guarded(%s, %s)",
            (WINDOW_H, event_filter),
        )
        return cur.fetchone()["n"]


def main() -> int:
    with get_conn() as conn:
        # count_new_arrivals call site — just-listed only.
        py_count_new = cq.count_new_arrivals(conn, WINDOW_H)
        sql_count_new = _sql_guarded_count(conn, [ARM])

        # select_f7_arrivals call site — both arms (cover true_count).
        py_true_count = cq.select_f7_arrivals(conn, WINDOW_H)[0]
        sql_true_count = _sql_guarded_count(conn, [ARM, RESTOCK])

    rows = [
        ("count_new_arrivals  [just-listed]", py_count_new, sql_count_new),
        ("select_f7_arrivals  [both arms]  ", py_true_count, sql_true_count),
    ]
    print(f"=== CTK-195 D-1 call-site / SQL-function differential ({WINDOW_H}h) ===")
    ok = True
    for label, py, sql in rows:
        match = "==" if py == sql else "!= MISMATCH"
        if py != sql:
            ok = False
        print(f"  {label}  python={py:>5}  sql={sql:>5}  {match}")

    if not ok:
        print(
            "\n  VERIFY FAILED: a call site diverges from the SQL function — "
            "port-fidelity bug (event_filter threading or trailing-days clamp)."
        )
        return 1
    print("\n  pre==post invariant holds: every call site agrees with the SQL function.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
