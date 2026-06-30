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


def verify_0069(conn):
    """CTK-214 Discord-parity — confirm the per-channel split landed live: both channel
    columns present, the old single column GONE, the channel-param functions callable,
    and an invalid channel RAISES (committed != applied). Behavioral guarantees (per-
    channel independence, fire-once) live in scrapers/tests/test_onboarding_detection."""
    import psycopg

    with conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'vendors' AND column_name IN "
            "('onboarding_announced_at', 'onboarding_announced_email_at', 'onboarding_announced_discord_at')"
        )
        cols = {r["column_name"] for r in cur.fetchall()}
        if "onboarding_announced_at" in cols:
            raise AssertionError("0069 verify: old vendors.onboarding_announced_at still present (should be dropped)")
        missing = {"onboarding_announced_email_at", "onboarding_announced_discord_at"} - cols
        if missing:
            raise AssertionError(f"0069 verify: vendors missing channel column(s) {sorted(missing)}")

        # Channel-param read functions smoke-call clean for each valid channel.
        for ch in ("email", "discord"):
            cur.execute("SELECT * FROM get_pending_onboarding_announcements(%s)", (ch,))
            cur.fetchall()
        cur.execute("SELECT * FROM get_onboarding_strip_state()")
        cur.fetchall()

        # An invalid channel must RAISE (not silently return []). The apply runner's
        # connection is autocommit, so a failed statement does not poison the connection
        # (no open transaction to abort) -- a plain try/except is enough.
        try:
            cur.execute("SELECT * FROM get_pending_onboarding_announcements('sms')")
            cur.fetchall()
            raise AssertionError("0069 verify: invalid channel 'sms' did not raise")
        except psycopg.errors.RaiseException:
            pass

        # Sentinel-slug no-ops (no live mutation).
        cur.execute("SELECT stamp_first_organic_drop_at('!_ctk214_verify_nonexistent') AS s")
        if cur.fetchone()["s"] is not None:
            raise AssertionError("0069 verify: stamp on a nonexistent slug returned non-NULL")
        cur.execute("SELECT * FROM mark_onboarding_announced(ARRAY['!_ctk214_verify_nonexistent'], 'email')")
        if cur.fetchall():
            raise AssertionError("0069 verify: mark stamped a nonexistent slug")
        # Guarded-source dependency resolves (the plpgsql organic branch is runtime-only).
        cur.execute(
            "SELECT 1 FROM get_f7_arrivals_guarded(24 * 180, ARRAY['just-listed']) "
            "WHERE vendor_slug = '!_ctk214_verify_nonexistent' LIMIT 1"
        )
        cur.fetchall()


def verify_0068(conn):
    """CTK-214 — confirm the two vendor-state columns landed and the four onboarding
    functions are callable against the live post-apply DB (committed != applied,
    feedback_migration_committed_not_applied). Live-DB-only: column presence + a
    smoke-call of each read function. Behavioral guarantees (fire-once, bulk-cohort
    suppression, the browseable predicate) live in scrapers/tests/, not here."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'vendors' "
            "AND column_name IN ('onboarding_announced_at', 'first_organic_drop_at')"
        )
        cols = {r["column_name"] for r in cur.fetchall()}
        missing = {"onboarding_announced_at", "first_organic_drop_at"} - cols
        if missing:
            raise AssertionError(f"0068 verify: vendors missing column(s) {sorted(missing)}")

        # Smoke-call the read functions — a signature/body error surfaces here, not
        # at the first digest render. Result rows are not asserted (live-data drift).
        cur.execute("SELECT * FROM get_pending_onboarding_announcements()")
        cur.fetchall()
        cur.execute("SELECT * FROM get_onboarding_strip_state()")
        cur.fetchall()
        # stamp_first_organic_drop_at on a non-existent slug must no-op to NULL (the
        # vendor lookup returns no row -> v_announced NULL -> early RETURN NULL).
        cur.execute("SELECT stamp_first_organic_drop_at('!_ctk214_verify_nonexistent') AS s")
        if cur.fetchone()["s"] is not None:
            raise AssertionError("0068 verify: stamp on a nonexistent slug returned non-NULL")
        # The stamp's organic-detection branch (get_f7_arrivals_guarded EXISTS) is plpgsql
        # -- resolved at RUNTIME, and the sentinel-slug call above short-circuits before
        # it. Smoke-call the guarded source directly so a rename/signature break in that
        # dependency surfaces at apply, not at the first scrape (/code-review CTK-214 [0]).
        cur.execute(
            "SELECT 1 FROM get_f7_arrivals_guarded(24 * 180, ARRAY['just-listed']) "
            "WHERE vendor_slug = '!_ctk214_verify_nonexistent' LIMIT 1"
        )
        cur.fetchall()
        # mark_onboarding_announced on no-match slugs stamps nothing (empty return).
        cur.execute("SELECT * FROM mark_onboarding_announced(ARRAY['!_ctk214_verify_nonexistent'])")
        if cur.fetchall():
            raise AssertionError("0068 verify: mark_onboarding_announced stamped a nonexistent slug")
