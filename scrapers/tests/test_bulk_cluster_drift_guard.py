"""scrapers/tests/test_bulk_cluster_drift_guard.py — CTK-198 N-drift guard.

The bulk_cluster threshold N=50 must live in EXACTLY one place
(scrapers/common/bulk_cluster.BULK_CLUSTER_MIN). The three write sites that
materialize the cohort-size test — the write-time hook, the one-shot backfill,
and the nightly audit — must reference that constant (via the %(min)s param),
NEVER a bare integer literal, so a future N change in one place can't silently
miss another.

Failure mode this guards against: someone tunes the audit to `>= 30` but leaves
the backfill at the constant's 50 (or vice versa). The catalog then disagrees
with itself about what a dump is — the exact silent-divergence class the
single-constant design exists to prevent.

It also locks the READ-side contract: migration 0057 (f7_arrivals_dispositioned)
and any newness surface read the PERSISTED bulk_cluster column and must NOT
re-derive the threshold (no `count(*) >= N` in the read path). And it checks the
0056 COMMENT documents the same N (in-DB documentation can't drift from code).

Pure static analysis — reads source/SQL file text, no DB. Note vs. the build
directive: the directive named "3 SQL-literal sites (0057, diff.py hook, audit
tool)"; the implementation instead routes all three WRITE sites through the
imported Python constant (strictly safer than scattered SQL literals — they
cannot drift), and 0057 carries NO threshold (it reads the persisted column per
item #3). This test enforces that stronger invariant.

Runnable as:
  python -m scrapers.tests.test_bulk_cluster_drift_guard
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from scrapers.common.bulk_cluster import BULK_CLUSTER_MIN

_ROOT = Path(__file__).resolve().parent.parent.parent

# Write sites: must reference BULK_CLUSTER_MIN, must NOT hardcode a competing
# cohort-size literal against count(*).
_WRITE_SITES = [
    _ROOT / "scrapers" / "common" / "bulk_cluster.py",
    _ROOT / "scripts" / "ctk198_bulk_cluster_backfill.py",
    _ROOT / "scrapers" / "tools" / "bulk_cluster_audit.py",
]

# Read sites: must read the persisted column, must NOT re-derive the threshold.
_MIGRATION_0057 = _ROOT / "supabase" / "migrations" / "0057_f7_arrivals_bulk_cluster_disposition.sql"
_MIGRATION_0056 = _ROOT / "supabase" / "migrations" / "0056_add_bulk_cluster_column.sql"

# A cohort-size threshold literal: `count(*) ... >= <int>` or `HAVING ... >= <int>`.
_COHORT_LITERAL = re.compile(r"count\(\*\)[^\n]*?>=\s*(\d+)", re.IGNORECASE)
# The threshold param must BIND to the constant — `"min": BULK_CLUSTER_MIN`. The
# bare-substring check ("BULK_CLUSTER_MIN" in text) is satisfied by a dead import
# or a docstring mention, so a site could hardcode `{"min": 30}` and still pass it;
# this asserts the value actually feeds the query param.
_MIN_BINDING = re.compile(r"""["']min["']\s*:\s*BULK_CLUSTER_MIN""")
_FAILURES: list[str] = []


def _check(cond: bool, msg: str) -> None:
    if not cond:
        _FAILURES.append(msg)


def main() -> int:
    # 1. Anchor: the constant is the value the rest of the system mirrors.
    _check(BULK_CLUSTER_MIN == 50,
           f"BULK_CLUSTER_MIN = {BULK_CLUSTER_MIN}, expected 50 "
           "(directive-locked; change here intentionally + update the 0056 COMMENT).")

    # 2. Write sites reference the constant, BIND it to the query param, and
    #    hardcode no competing literal.
    for path in _WRITE_SITES:
        text = path.read_text(encoding="utf-8")
        if path.name != "bulk_cluster.py":
            _check("BULK_CLUSTER_MIN" in text,
                   f"{path.name} does not reference BULK_CLUSTER_MIN — it must import "
                   "the single-source constant, not hardcode N.")
        # The %(min)s param must bind to the constant — closes the dead-import /
        # hardcoded-`{'min': 30}` false-pass the bare substring check allows.
        _check(bool(_MIN_BINDING.search(text)),
               f"{path.name} does not bind the min param to BULK_CLUSTER_MIN "
               "(`\"min\": BULK_CLUSTER_MIN`) — a hardcoded `{{'min': N}}` would "
               "silently fork the threshold.")
        # No `count(*) >= <int>` literal: the cohort test must flow through the
        # %(min)s param bound to BULK_CLUSTER_MIN. (bulk_cluster.py's flip helper
        # also uses %(min)s, so this holds for the const module too.)
        for m in _COHORT_LITERAL.finditer(text):
            _FAILURES.append(
                f"{path.name}: hardcoded cohort literal `count(*) >= {m.group(1)}` — "
                "must use the %(min)s param bound to BULK_CLUSTER_MIN.")

    # 3. Read path (0057) reads the persisted column, never re-derives N.
    sql_0057 = _MIGRATION_0057.read_text(encoding="utf-8")
    _check("bulk_cluster" in sql_0057,
           "0057 does not reference the bulk_cluster column.")
    _check("'bulk_cluster'" in sql_0057,
           "0057 does not add the 'bulk_cluster' disposition value.")
    for m in _COHORT_LITERAL.finditer(sql_0057):
        _FAILURES.append(
            f"0057 re-derives a cohort threshold (`count(*) >= {m.group(1)}`) — the read "
            "path must read the persisted bulk_cluster column, not recompute N.")

    # 4. 0056 COMMENT documents the same N (in-DB doc can't drift from code).
    sql_0056 = _MIGRATION_0056.read_text(encoding="utf-8")
    doc_thresholds = re.findall(r">=\s*(\d+)\s*rows", sql_0056)
    _check(bool(doc_thresholds),
           "0056 COMMENT does not state the cohort threshold (`>= N rows`).")
    for n in doc_thresholds:
        _check(int(n) == BULK_CLUSTER_MIN,
               f"0056 COMMENT documents `>= {n} rows` but BULK_CLUSTER_MIN = "
               f"{BULK_CLUSTER_MIN} — update the COMMENT to match the constant.")

    if _FAILURES:
        print(f"FAIL — {len(_FAILURES)} drift-guard violation(s):")
        for f in _FAILURES:
            print(f"  - {f}")
        return 1
    print(f"PASS — N={BULK_CLUSTER_MIN} single-sourced; 3 write sites reference the "
          "constant; read path + 0056 COMMENT consistent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
