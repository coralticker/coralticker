-- CTK-038 Session 1 — `scraper_runs.phase_b_finished_at` observability column.
--
-- Closes the Phase A/B observability gap surfaced by CTK-026 Session 2 (Q-4):
-- today `scraper_runs.status='success'` + `finished_at=<Phase A end>` is
-- written BEFORE Phase B mirror starts (per CTK-024 Session 2 design —
-- image-only failure does NOT fail the listing row, image-fetch I/O moved
-- out of inline persist loop). Phase B then continues for tens of minutes
-- or hard-cancels at the 60-min `timeout-minutes` cap. Future-Jon at 11pm
-- querying "did the last run succeed?" sees `status='success',
-- finished_at=14:53:47Z` and concludes "yes" — but the workflow may have
-- continued through Phase B and ultimately cancelled mid-mirror.
--
-- TSA cold-start id=20 (2026-05-07 14:52Z) was the empirical surface:
-- row finalized 14:53:47Z with `status='success', finished_at=14:53:47Z,
-- error_class=null`; Phase B ran ~60min (3165/4191 mirrored) before GH
-- Actions hard-cancelled at 15:53:30Z. Row says success, reality was
-- cancelled — no DB-side signal distinguished the two.
--
-- Fix: additive column `phase_b_finished_at TIMESTAMPTZ NULL`. Populated
-- post-Phase-B by `scrapers/common/run.py` via `db.finish_phase_b` helper
-- (CTK-038 Session 1 code change). `finished_at` semantic UNCHANGED
-- (Phase A end-time per CTK-024 design). NULL strictly means pre-CTK-038
-- OR Phase-B-cancelled (hard-cancel at timeout never reaches the
-- post-Phase-B write; zero-NEW steady-state rows DO populate it because
-- the helper-call lifts OUT of the `if ... and mirror_queue:` sub-block
-- into the parent `if status_finalized and status == "success":` block
-- per CTK-038 D-3).
--
-- Query shape future-Jon greps: `WHERE status='success' AND
-- phase_b_finished_at IS NULL` finds hard-cancelled cold-starts cleanly;
-- `started_at < <CTK-038-deploy-date>` discriminates pre-CTK-038 rows
-- from Phase-B-cancelled rows when the distinction matters. No backfill
-- of historical rows per D-3 — acceptable lossiness at Phase 1 close.
--
-- Idempotent per CTK-028/032/033/034 migration convention: `ADD COLUMN
-- IF NOT EXISTS` no-ops on re-run. Additive nullable column with no
-- default — metadata-only ALTER on PostgreSQL, no row rewrite, no lock
-- escalation against active scrapers per CTK-038 Risks §1 mitigation.

ALTER TABLE scraper_runs
  ADD COLUMN IF NOT EXISTS phase_b_finished_at timestamptz;

COMMENT ON COLUMN scraper_runs.phase_b_finished_at IS
  'CTK-038 Phase B end-time. NULL = pre-CTK-038 row OR Phase B never completed (hard-cancel at workflow timeout, orchestrator process killed mid-mirror). NON-NULL = Phase B reached the post-mirror code path (mirror succeeded fully OR zero-NEW steady-state run with empty mirror_queue). Distinguish pre-CTK-038 from Phase-B-cancelled via `started_at < <CTK-038-deploy-date>`. `finished_at` retains Phase A end-time semantic per CTK-024 Session 2 design.';
