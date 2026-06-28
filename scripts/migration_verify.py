"""scripts/migration_verify.py — CTK-208: optional per-migration verify hooks for
the apply-runner (scripts/apply_migration.py).

Convention, not a registry: define a module-level callable named verify_<NN>(conn)
where <NN> is the zero-padded 4-digit migration number (e.g. verify_0062). After
applying migration NN, the runner looks up getattr(this_module, f"verify_{NN}") and
calls it with the live post-apply connection if present. No registration dict, no
plugin discovery — just the name.

When to add a hook here vs. a test in scrapers/tests/:
  - Add a TEST (the default) for any guarantee checkable without the just-applied
    live DB — function row-shapes, parser behavior, classifier tokens. Tests run in
    CI and on every `pytest scrapers/tests/` without a live connection.
  - Add a HOOK here only for an assertion that must run against the live DB state
    immediately after the migration applies and cannot be expressed as a vendors-row
    match (which --expect-vendor already covers).

A hook raises on failure (the runner surfaces it loud + exits 1). It returns nothing
on success. There are no hooks today — the common new-vendor case is covered by
--expect-vendor, and the 0062-style behavioral guarantees were ported into
scrapers/tests/ at CTK-208 rather than left as one-off apply-script verify blocks.

Example shape (do not uncomment — illustrative):
    def verify_0099(conn):
        with conn.cursor() as cur:
            cur.execute("SELECT count(*)::int AS n FROM some_table")
            if cur.fetchone()["n"] == 0:
                raise AssertionError("0099 verify: some_table is unexpectedly empty")
"""

from __future__ import annotations
