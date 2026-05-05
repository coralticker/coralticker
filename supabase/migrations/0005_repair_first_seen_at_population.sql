-- CTK-032 Session 2 — repair `first_seen_at` mutation on rows where pre-fix
-- runs silently overwrote the timestamp via the H2 mechanism (UPDATE-path
-- SET first_seen_at = EXCLUDED.first_seen_at = now() across mixed-decision
-- batch upserts).
--
-- Detection: signal #1 only — `EXISTS price_history WHERE observed_at <
-- first_seen_at`. Dispositive evidence per disposition file
-- `lead-review-results-2026-05-05-session-2-q1-heuristic-refinement.md`:
-- price_history is append-only by arch §1.5 / decision #7, so any ph row
-- pre-dating the listing's first_seen_at is impossible if first_seen_at
-- reflects the true first-observation moment. Signals #2/#2'/#3 dropped:
-- #2 (started_at < first_seen_at) over-broad; #2' (finished_at <
-- first_seen_at) has 991-row PE false-positive risk on legit-new-by-
-- later-run rows; #3 (last_price_changed_at < first_seen_at) is dead
-- because last_price_changed_at is set fresh during the same run that
-- mutates first_seen_at.
--
-- Re-anchor: `first_seen_at = MIN(price_history.observed_at)` for the
-- listing. Earliest evidence-of-existence wins. No LEAST(), no NULL
-- handling — signal #1 fires only when the MIN exists strictly less than
-- the current value.
--
-- Pre-state range: BETWEEN 6500 AND 6600 (current count 6540 at
-- 2026-05-05 query time; tight range catches drift between query and
-- apply). RAISE EXCEPTION on miss → transaction rolls back, no harm.
--
-- Post-state verification: signal #1 returns 0 for all rows. Every
-- mutated row's first_seen_at now equals its MIN(price_history.observed_at)
-- → no observed_at strictly less than first_seen_at survives. RAISE
-- EXCEPTION on non-zero → transaction rolls back.
--
-- Trigger interaction: 0004 added `BEFORE UPDATE OF first_seen_at`
-- preserving OLD.first_seen_at — that's the integrity protection for
-- production traffic. This migration is corrective DDL-equivalent
-- maintenance; DISABLE the trigger for the UPDATE statement, ENABLE on
-- exit. ALTER TABLE inside a transaction: trigger state changes are
-- transactional in PostgreSQL, so a ROLLBACK restores prior state.
--
-- Coverage: 6540 of 9544 catalog rows (~65%); 35% leave-untouched per
-- plan §3 success criterion #5's "where signal exists" qualifier. The
-- 35% have no signal evidence of mutation and may be either correctly-
-- timestamped (legit-new added by later runs) or quietly imprecise with
-- no way to tell. Downstream consumers (CTK-029 cold-start backfill,
-- CTK-005/006 wishlist alerts) tolerate ~hour-level imprecision via
-- matched_at-as-lower-bound semantic per arch §3.8 + §4.2.

BEGIN;

DO $$
DECLARE
  v_pre_count integer;
BEGIN
  SELECT count(*) INTO v_pre_count
  FROM vendor_listings vl
  WHERE EXISTS (
    SELECT 1 FROM price_history ph
    WHERE ph.listing_id = vl.id AND ph.observed_at < vl.first_seen_at
  );

  IF v_pre_count NOT BETWEEN 6500 AND 6600 THEN
    RAISE EXCEPTION
      'CTK-032 Session 2 pre-state guard: signal #1 row count % outside expected range [6500, 6600]; aborting migration. Rerun signal #1 query and re-validate scope before re-applying.',
      v_pre_count;
  END IF;

  RAISE NOTICE 'CTK-032 Session 2 pre-state OK: signal #1 scope = %', v_pre_count;
END
$$;

ALTER TABLE vendor_listings DISABLE TRIGGER vendor_listings_preserve_first_seen_at;

UPDATE vendor_listings vl
SET first_seen_at = (
  SELECT MIN(ph.observed_at)
  FROM price_history ph
  WHERE ph.listing_id = vl.id
)
WHERE EXISTS (
  SELECT 1 FROM price_history ph
  WHERE ph.listing_id = vl.id AND ph.observed_at < vl.first_seen_at
);

ALTER TABLE vendor_listings ENABLE TRIGGER vendor_listings_preserve_first_seen_at;

DO $$
DECLARE
  v_post_count integer;
BEGIN
  SELECT count(*) INTO v_post_count
  FROM vendor_listings vl
  WHERE EXISTS (
    SELECT 1 FROM price_history ph
    WHERE ph.listing_id = vl.id AND ph.observed_at < vl.first_seen_at
  );

  IF v_post_count <> 0 THEN
    RAISE EXCEPTION
      'CTK-032 Session 2 post-state verification: signal #1 still fires for % rows after backfill; expected 0. Re-anchor logic broken; rolling back.',
      v_post_count;
  END IF;

  RAISE NOTICE 'CTK-032 Session 2 post-state OK: signal #1 scope = 0';
END
$$;

COMMIT;
