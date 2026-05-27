"""CTK-029 v1 batch backfill — thin wrapper around scrapers.rematch.rematch_one.

Iterates the 20 v1 seed named_corals (migration 0012 IDs 1-20 contiguous
per CTK-029 Session 1 post-apply verify) serially, calling rematch_one
per coral. Captures per-coral hit counts + total updated + runtime.

CLI:

    python -m scrapers.rematch_v1_batch

Output: stdout table of (id, canonical_name, scanned, updated, elapsed_sec)
+ aggregate footer. Suitable for paste into CTK-029 results.md.

Reuses one psycopg connection across all 20 calls (rematch_one accepts a
caller-managed conn). The single-coral cascade is cheap per arch §3.8
("takes seconds" at 10k×1 scale); 20 sequential runs stay well inside
that envelope. No chunking, no resumability, no parallelism — one-shot
script per plan §B3b.
"""

from __future__ import annotations

import logging
import sys
import time

from scrapers.common import db
from scrapers.rematch import rematch_one

V1_SEED_ID_RANGE = range(1, 21)  # migration 0012 IDs 1-20, contiguous


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    started = time.monotonic()
    rows: list[dict] = []
    with db.get_conn() as conn:
        for nc_id in V1_SEED_ID_RANGE:
            rows.append(rematch_one(conn, named_coral_id=nc_id))

    total_scanned = sum(r["scanned"] for r in rows)
    total_updated = sum(r["updated"] for r in rows)
    elapsed = time.monotonic() - started

    print()
    print(f"{'id':>4}  {'canonical_name':<40}  {'scanned':>8}  {'updated':>8}  {'elapsed':>8}")
    print(f"{'-' * 4}  {'-' * 40}  {'-' * 8}  {'-' * 8}  {'-' * 8}")
    for r in rows:
        print(
            f"{r['named_coral_id']:>4}  "
            f"{r['canonical_name'][:40]:<40}  "
            f"{r['scanned']:>8}  "
            f"{r['updated']:>8}  "
            f"{r['elapsed_sec']:>7.3f}s"
        )
    print(f"{'-' * 4}  {'-' * 40}  {'-' * 8}  {'-' * 8}  {'-' * 8}")
    print(
        f"{'TOT':>4}  {'(20 v1 seed corals)':<40}  "
        f"{total_scanned:>8}  {total_updated:>8}  {elapsed:>7.3f}s"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
