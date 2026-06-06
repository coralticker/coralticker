"""Apply migration 0034 — CTK-124: DROP the zero-arg get_recent_price_drops()
signature (overload two-step, step two).

Gated on the CTK-124 Session 2 frontend deploy (commit 45a01f4, live
spot-check passed 2026-06-06) — all four lib/queries/listings.ts
statements now bind the one-arg union signature, so nothing calls the
zero-arg function. See the migration header for the ordering rationale.

Uses scrapers.common.db.get_conn per CTK-061 amendment-2 single-statement
path. Mirrors apply_migration_0033.py shape.

Idempotent: DROP IF EXISTS scoped to the empty-args signature.

Verification:
  - zero-arg signature GONE from pg_proc
  - one-arg union signature still present; projects event_at +
    compare_at_price; EXECUTE privilege intact (per-signature grants)
  - one-arg smoke call returns rows (live /deals dependency)
"""

from __future__ import annotations

import sys
from pathlib import Path

from scrapers.common.db import get_conn

MIGRATION_PATH = Path(__file__).resolve().parent.parent / "supabase" / "migrations" / "0034_drop_zero_arg_price_drops.sql"

WINDOW_DAYS = 7  # smoke value — mirrors DEALS_WINDOW_DAYS (D-1, Jon-ratified 2026-06-04)


def main() -> int:
    sql = MIGRATION_PATH.read_text(encoding="utf-8")

    with get_conn() as conn:
        with conn.cursor() as cur:
            print(f"executing: {MIGRATION_PATH.name} ({len(sql)} bytes)...")
            try:
                cur.execute(sql)
            except Exception as exc:
                print(f"  FAILED: {type(exc).__name__}: {exc}")
                return 1
            print("  ok")

        print()
        print("=" * 70)
        print("post-apply verification — pg_proc signatures + grants + smoke")
        print("=" * 70)

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT pg_get_function_identity_arguments(oid) AS args,
                       pg_get_function_result(oid) AS result
                FROM pg_proc
                WHERE proname = 'get_recent_price_drops'
                  AND pronamespace = 'public'::regnamespace
                ORDER BY pronargs
                """
            )
            rows = cur.fetchall()
        sigs = {r["args"] for r in rows}
        for row in rows:
            print(f"  get_recent_price_drops({row['args']})")
        if "" in sigs:
            print("  STILL PRESENT: zero-arg signature survived the DROP")
            return 1
        if "p_window_days integer" not in sigs:
            print("  MISSING: one-arg union signature gone — DROP over-reached")
            return 1
        one_arg = [r for r in rows if r["args"] == "p_window_days integer"][0]
        if "event_at" not in one_arg["result"] or "compare_at_price" not in one_arg["result"]:
            print("  CHANGED: one-arg result lacks event_at / compare_at_price")
            return 1
        print("  signatures ok: zero-arg retired; one-arg union untouched")

        # CTK-124 Session 3b fix: filter PER-SIGNATURE, not by routine_name.
        # Privileges attach per-signature; while two overloads coexist, a
        # name-level filter lets either signature's grant satisfy the check
        # (false positive for the surviving one). routines.specific_name is
        # '<routine_name>_<pg_proc oid>', so resolving the target overload's
        # OID pins the check to exactly that signature. This script is the
        # overload-two-step TEMPLATE — any future same-name signature
        # migration inherits this shape, not the name-level filter.
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT grantee
                FROM information_schema.routine_privileges
                WHERE specific_name = (
                    SELECT proname || '_' || oid::text
                    FROM pg_proc
                    WHERE proname = 'get_recent_price_drops'
                      AND pronamespace = 'public'::regnamespace
                      AND pg_get_function_identity_arguments(oid) = 'p_window_days integer'
                )
                  AND privilege_type = 'EXECUTE'
                """
            )
            grantees = sorted({r["grantee"] for r in cur.fetchall()})
        print(f"  EXECUTE grantees on remaining signature: {grantees}")
        if not grantees:
            print("  MISSING: no EXECUTE grants on the one-arg signature")
            return 1

        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS c FROM get_recent_price_drops(%s)", (WINDOW_DAYS,))
            smoke = cur.fetchone()["c"]
        print(f"  get_recent_price_drops({WINDOW_DAYS}) smoke: {smoke} rows")
        if smoke == 0:
            print("  DEFECT: one-arg union returns zero rows (live /deals dependency)")
            return 1

        print()
        print("all checks passed")

    return 0


if __name__ == "__main__":
    sys.exit(main())
