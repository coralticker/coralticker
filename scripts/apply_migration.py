"""scripts/apply_migration.py — CTK-208: one parameterized migration apply-runner,
replacing the ~40 cloned scripts/apply_migration_00NN.py one-offs.

Usage:
  python -m scripts.apply_migration <NN> [--drop "<SQL>"] [--expect-vendor '<JSON>']

  <NN>             migration number, e.g. 64 or 0064; resolves the single
                   supabase/migrations/00NN_*.sql by glob (ambiguous / missing =
                   loud exit 1).
  --drop "<SQL>"   optional DROP statement(s) executed BEFORE the migration body so
                   a CREATE-FUNCTION migration is re-runnable (the 0062 idiom).
  --expect-vendor  JSON object describing the common vendor-row case. Must carry a
                   "slug" key (the lookup); every other key/value is asserted equal
                   on the vendors row after apply. Mirrors the 0064 declarative
                   verify, parameterized.

Optional per-migration verify hook (no registry, no plugin system): if
scripts/migration_verify.py defines a callable verify_<NN>(conn), the runner calls
it after apply for migrations whose guarantee is richer than a vendor-row match.
Absent module / absent function = no extra verify (the common case). Behavioral
guarantees that can be checked WITHOUT the just-applied live DB (e.g. the 0062
drop-cadence function family's row-shape contracts) belong in scrapers/tests/, not
here — the hook is only for assertions that must run against the live post-apply DB.

Connection is scrapers.common.db.get_conn (architecture-v1.md #65), autocommit per
that module — no explicit COMMIT. Exit 1 (loud) on: no/ambiguous SQL match, apply
exception, verify mismatch, or hook failure. Prints bytes + ms (the 0064 shape).

Examples:
  python -m scripts.apply_migration 64 \\
      --expect-vendor '{"slug":"coralstop","id":37,"platform":"shopify","active":true}'
  python -m scripts.apply_migration 62 \\
      --drop "DROP FUNCTION IF EXISTS get_vendor_recent_drops(text,int,int);"
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

from scrapers.common.db import get_conn
# Top-level import (CTK-208 /code-review #5): the hook module always ships, so a
# BROKEN scripts/migration_verify.py must fail loudly here, not be swallowed as
# "no hooks present" by a bare `except ImportError` around the import.
from scripts import migration_verify as _migration_verify

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "supabase" / "migrations"

# RPC convention (architecture-v1.md): every public RPC function carries an EXECUTE
# grant to these non-owner roles. The grant check below re-instates the apply-time
# guarantee the per-migration clones carried.
_RPC_GRANT_ROLES = ("service_role", "authenticated", "anon")
# Detect functions a migration creates (signature head only); RETURNS trigger funcs
# are excluded from the grant check (they are never EXECUTE-granted to roles).
_CREATE_FUNCTION_RE = re.compile(
    r"CREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+(?:public\.)?\"?(\w+)\"?\s*\(",
    re.IGNORECASE,
)


def _resolve(nn: str) -> Path:
    """Resolve the single supabase/migrations/00NN_*.sql for a migration number.
    Loud exit 1 on no match or ambiguity — never guess."""
    stem = nn.zfill(4)
    matches = sorted(MIGRATIONS_DIR.glob(f"{stem}_*.sql"))
    if not matches:
        print(f"  FAILED: no migration matches {stem}_*.sql under {MIGRATIONS_DIR}")
        sys.exit(1)
    if len(matches) > 1:
        print(f"  FAILED: {stem} is ambiguous — {[m.name for m in matches]}")
        sys.exit(1)
    return matches[0]


def _verify_vendor(conn, expect: dict) -> None:
    """Declarative vendor-row verify (the common new-vendor case). expect must carry
    'slug' (the lookup key); every key is asserted equal on the vendors row."""
    slug = expect.get("slug")
    if not slug:
        print("  VERIFY FAILED: --expect-vendor JSON must carry a 'slug' key")
        sys.exit(1)
    cols = list(expect.keys())
    with conn.cursor() as cur:
        cur.execute(f"SELECT {', '.join(cols)} FROM vendors WHERE slug = %s", (slug,))
        row = cur.fetchone()
    if row is None:
        print(f"  VERIFY FAILED: vendors row for slug={slug!r} missing after apply")
        sys.exit(1)
    for key, want in expect.items():
        got = row[key]
        if got != want:
            print(f"  VERIFY FAILED: vendors.{key} = {got!r}, expected {want!r}")
            sys.exit(1)
    print(f"  verified: vendors row slug={slug!r} matches {len(expect)} expected field(s)")


def _verify_function_grants(conn, sql: str) -> None:
    """CTK-208 /code-review #3 — re-instate the apply-time RPC-grant guarantee the
    per-migration clones carried. If the migration creates any non-trigger function,
    verify each carries a non-owner EXECUTE grant (service_role/authenticated/anon per
    the RPC convention); loud exit 1 if absent. A migration that adds GRANT EXECUTE in
    its own body (the convention) passes; one that forgets fails here rather than
    silently shipping an un-callable RPC.

    Trigger functions (RETURNS trigger) are excluded — they are never EXECUTE-granted
    to roles. A genuinely-private SECURITY-DEFINER helper would need a verify_<NN> hook
    override instead; none exist today."""
    matches = list(_CREATE_FUNCTION_RE.finditer(sql))
    if not matches:
        return
    bounds = [m.start() for m in matches] + [len(sql)]
    checked: list[str] = []
    for i, m in enumerate(matches):
        name = m.group(1)
        segment = sql[m.start():bounds[i + 1]]
        if re.search(r"RETURNS\s+trigger", segment, re.IGNORECASE):
            continue  # trigger function — no role EXECUTE grant expected
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM information_schema.routine_privileges "
                "WHERE routine_schema = 'public' AND routine_name = %s "
                "AND privilege_type = 'EXECUTE' AND grantee = ANY(%s) LIMIT 1",
                (name, list(_RPC_GRANT_ROLES)),
            )
            if cur.fetchone() is None:
                print(
                    f"  VERIFY FAILED: function {name}() has no "
                    f"{'/'.join(_RPC_GRANT_ROLES)} EXECUTE grant after apply — add a "
                    f"GRANT EXECUTE ON FUNCTION {name}(...) to the migration (RPC convention)"
                )
                sys.exit(1)
        checked.append(name)
    if checked:
        print(f"  verified: non-owner EXECUTE grant present on {', '.join(checked)}")


def _run_hook(conn, nn: str) -> None:
    """Optional per-migration verify hook. Calls migration_verify.verify_<NN> if it
    exists; no-op otherwise. raises (loud) on hook failure."""
    fn = getattr(_migration_verify, f"verify_{nn.zfill(4)}", None)
    if fn is None:
        return
    print(f"  running verify hook verify_{nn.zfill(4)}...")
    fn(conn)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="apply_migration")
    ap.add_argument("nn", help="migration number, e.g. 64 or 0064")
    ap.add_argument("--drop", default=None,
                    help="DROP SQL run before the body (re-runnable CREATE FUNCTION)")
    ap.add_argument("--expect-vendor", default=None,
                    help="JSON vendor-row expectation (must include slug)")
    args = ap.parse_args(argv)

    path = _resolve(args.nn)
    sql = path.read_text(encoding="utf-8")

    with get_conn() as conn:
        with conn.cursor() as cur:
            print(f"executing: {path.name} ({len(sql)} bytes)...")
            t0 = time.monotonic()
            try:
                if args.drop:
                    cur.execute(args.drop)
                cur.execute(sql)
            except Exception as exc:  # noqa: BLE001 — surface loudly, exit 1
                print(f"  FAILED: {type(exc).__name__}: {exc}")
                return 1
            elapsed_ms = (time.monotonic() - t0) * 1000.0
            print(f"  applied in {elapsed_ms:.0f} ms")

        _verify_function_grants(conn, sql)
        if args.expect_vendor:
            _verify_vendor(conn, json.loads(args.expect_vendor))
        _run_hook(conn, args.nn)

    print(f"{path.stem} applied.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
