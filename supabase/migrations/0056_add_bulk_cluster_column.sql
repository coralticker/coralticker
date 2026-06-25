-- CTK-198 (Tier 1B) — persist `bulk_cluster` on vendor_listings so every newness
-- surface reads ONE source for the single-timestamp bulk-insert guard instead of
-- each re-deriving it. Sibling to CTK-191 (read-side median-relative guard) +
-- CTK-195 (shared-SQL port).
--
-- ─── What this is ───
--
-- bulk_cluster = true for a row whose (vendor_id, first_seen_at) cohort has >= 50
-- rows — a single-timestamp batch dump (vendor re-index or onboarding flood). The
-- median-relative CTK-191 guard (max(80, 4 x trailing-median) per (vendor, day))
-- catches only the 3 largest per-day cohorts; high-volume same-second dumps
-- (WWC 175 @ 06-20 15:25:39, AquaSD 153, ...) slip through as 'kept'. Of 786 'kept'
-- just-listed rows live 2026-06-25, 729 (93%) sit in >=10 single-timestamp cohorts;
-- honest organic floor ~57.
--
-- ─── Why a persisted column (the self-healing contract) ───
--
-- bulk_cluster is a PURE FUNCTION of immutable (vendor_id, first_seen_at): a row's
-- cohort never changes after the scrape that wrote it (first_seen_at is write-once —
-- DB DEFAULT now() on INSERT, never touched on UPDATE, + the preserve_first_seen_at
-- trigger), so the boolean persists cleanly. It does NOT subsume the read-side
-- cold_start / bulk_relist dispositions — those are median-relative (a trailing
-- window that moves daily), so a fixed row's disposition changes over time and
-- can't be stably persisted (the is_auction trap). bulk_cluster is orthogonal and
-- additive.
--
-- Maintained by two writers over the threshold N=50 (defined once in
-- scrapers/common/bulk_cluster.py BULK_CLUSTER_MIN):
--   1. write-time, vendor-scoped, false->true only (diff.persist_phase_a hook) —
--      immediacy: a noon re-index is flagged before the next request.
--   2. nightly full-catalog IS DISTINCT FROM reconcile (scrapers/tools/
--      bulk_cluster_audit.py, cron ~14:02 UTC clear of scrape windows) — the
--      durable self-heal + the only writer permitted a true->false correction.
-- Plus a one-shot historical backfill (scripts/ctk198_bulk_cluster_backfill.py).
-- The cron-window race is benign: the write-time hook already covers fresh cohorts.
--
-- ─── Apply shape ───
--
-- ADD COLUMN ... NOT NULL DEFAULT false is METADATA-ONLY on Neon/PG15 (PG11+ stores
-- a constant default in pg_attribute; no table rewrite, no per-row backfill for the
-- column add). The ~15,779-row historical backfill of true values is a SEPARATE
-- one-shot script (gated behind a dry-run eyeball), not this DDL. Apply via
-- scripts/apply_migration_0056.py (mirrors apply_migration_0055.py). Re-runnable:
-- IF NOT EXISTS makes the ADD idempotent; COMMENT is unconditional CREATE-OR-REPLACE
-- semantics.
--
-- APPLY-ORDER (load-bearing): this column MUST be applied to prod before the
-- diff.py write-time hook deploys — the hook's UPDATE errors if the column is absent.

ALTER TABLE vendor_listings
  ADD COLUMN IF NOT EXISTS bulk_cluster boolean NOT NULL DEFAULT false;

COMMENT ON COLUMN vendor_listings.bulk_cluster IS
  'CTK-198: true iff this row''s (vendor_id, first_seen_at) cohort has >= 50 rows '
  '(BULK_CLUSTER_MIN) — a single-timestamp batch dump (re-index / onboarding flood) '
  'the median-relative CTK-191 guard misses. Pure function of immutable '
  '(vendor_id, first_seen_at). Self-healing: write-time vendor-scoped false->true '
  'hook in diff.persist_phase_a + nightly full-catalog reconcile in '
  'scrapers/tools/bulk_cluster_audit.py (the only true->false writer). Newness '
  'surfaces (f7_arrivals_dispositioned 4th disposition, get_aggregate_activity, '
  '/new feeds) read this column; they do not re-derive the threshold. INV-08.';
