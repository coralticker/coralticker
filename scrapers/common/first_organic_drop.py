"""scrapers/common/first_organic_drop.py — CTK-214 Signal 2 scrape-time stamp.

Fire-once stamp of `vendors.first_organic_drop_at`: the moment a newly-onboarded
vendor first produces a genuine organic drop AFTER its onboarding announcement,
so the frontend's "now tracking" strip can retire (the vendor has gone live with
real drops, not just the indexed catalog).

All the gate logic lives in the SQL function `stamp_first_organic_drop_at` (migration
0068) — announced AND not-yet-stamped AND has a guarded-just-listed survivor
(bulk_cluster=false + cold-start-survived, INV-08; the exact organic population
get_vendor_drop_cadence reads). This module is the cheap fail-soft TRIGGER the scrape
pipeline calls post-persist; it owns no detection logic of its own (do NOT build a
parallel is-organic detector — CTK-214 directive).

Mirrors the bulk_cluster write-time hook discipline (scrapers/common/bulk_cluster.py):
called OUTSIDE the persist transaction (autocommit), gated on a new-listing decision
this run (preserving the "empty decisions = zero writes" contract), best-effort, the
caller swallows exceptions. A missed stamp self-heals on the vendor's NEXT scrape that
still has a surviving organic row (the gate is idempotent — `first_organic_drop_at IS
NULL` guards both the read and the write), so the scrape's success never depends on it.

Cheap by construction: the SQL gate short-circuits on the two column checks
(announced? already stamped?) before the expensive guarded scan runs, so the common
qualifying-scrape path — a vendor already stamped, or not yet announced — is two
indexed column reads and no guarded-source scan.
"""

from __future__ import annotations

import datetime

import psycopg


def stamp_first_organic_drop(conn: psycopg.Connection, vendor_slug: str) -> datetime.datetime | None:
    """Post-persist hook (CTK-214): ask the DB to stamp first_organic_drop_at for
    this vendor if (and only if) it is announced, not yet stamped, and has a
    guarded-just-listed organic survivor. Returns the stamp timestamp when newly
    set OR already set, None when there is no survivor yet (the per-scrape no-op).

    The whole decision is the SQL function's — this is one RPC call. Vendor-scoped
    and idempotent: re-calling after a stamp is a column read, not a re-write.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT stamp_first_organic_drop_at(%s) AS stamped", (vendor_slug,))
        row = cur.fetchone()
    # dict_row (scrapers.common.db) -> {"stamped": <ts|None>}; positional fallback.
    if row is None:
        return None
    return row["stamped"] if isinstance(row, dict) else row[0]
