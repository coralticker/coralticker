-- CTK-214 (Tier 2 -- growth/coverage) -- new-vendor onboarding detection backend.
--
-- WHY: a newly-onboarded vendor's whole catalog lands at one first_seen_at -- the
-- CTK-198/CTK-213 cold-start + bulk_cluster suppression correctly withholds it from
-- the "new arrivals" surfaces (it is "we started watching them," not "new"). That
-- leaves four onboarded vendors dark: zero subscriber signal until they post an
-- organic drop. This migration adds the two vendor-state timestamps + the read
-- functions the digest/strip consume to surface a single HONEST "now tracking"
-- announcement -- a catalog-size count, explicitly NOT "N new arrivals."
--
-- THREE SIGNALS (all additive; no existing function touched):
--   1. get_pending_onboarding_announcements() -- vendors not yet announced, with a
--      live browseable-in-stock count n. The digest renders one line per row, then
--      stamps onboarding_announced_at via mark_onboarding_announced() AFTER a
--      successful send (fire-once; benign double-announce on send-failure beats a
--      silent under-announce -- CTK-214 directive Q3).
--   2. get_onboarding_strip_state() -- announced vendors + both timestamps; the
--      frontend owns the 7-day / first-organic-drop retire policy. Backend just
--      provides onboarded_at + first_organic_drop_at.
--   3. stamp_first_organic_drop_at(slug) -- fire-once stamp, called post-persist by
--      the scrape pipeline (scrapers/common/first_organic_drop.py). Owns the full
--      gate: announced AND not-yet-stamped AND has a guarded-just-listed survivor.
--
-- HONEST-FRAMING INVARIANT (load-bearing): n is ALWAYS the browseable in-stock
-- catalog size -- in_stock AND NOT equipment AND NOT invert (EXCLUDED_CATEGORIES,
-- INV-07). NEVER total rows, NEVER "new arrivals." Lose that distinction and the
-- announcement re-introduces the exact cold-start lie CTK-198/CTK-213 suppress. The
-- predicate is the NULL-safe set form (vl.category IS NULL OR vl.category <> ALL(...))
-- matching 0067 -- the IS NULL arm keeps reclassified None-category corals visible.
--
-- ORGANIC DETECTION reuses the guarded just-listed arm verbatim -- NOT a parallel
-- "is-organic" detector. get_f7_arrivals_guarded(window, ARRAY['just-listed']) +
-- vl.bulk_cluster = false (INV-08) + the equipment exclusion (INV-07), the exact
-- population get_vendor_drop_cadence reads (migration 0066). The onboarding bulk
-- cohort (>=50 same-first_seen_at -> bulk_cluster=true, or cold_start) is excluded
-- by construction: it never reaches guard_disposition='kept', so it can never stamp
-- first_organic_drop_at.
--
-- TEST-VENDOR BELT (CTK-213): active = true AND slug NOT LIKE '!_%' ESCAPE '!' on
-- every vendor scan here -- the pending/strip queries MUST carry it or _ctk*test
-- vendors get announced.
--
-- Apply: python -m scripts.apply_migration 68
-- Verify: verify_0068 (scripts/migration_verify.py) -- columns live + functions
--   callable (committed != applied, feedback_migration_committed_not_applied).

-- ===========================================================================
-- Columns -- two nullable vendor-state timestamps. Additive, no default. The
-- established set is backfilled below (Option 1); only a genuinely-fresh onboard
-- carries NULL/NULL (pending announce / awaiting first organic drop).
-- ===========================================================================
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS onboarding_announced_at timestamptz;
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS first_organic_drop_at   timestamptz;

COMMENT ON COLUMN vendors.onboarding_announced_at IS
  'CTK-214 -- when the "now tracking" onboarding announcement was sent to subscribers (fire-once). NULL = not yet announced (pending) or pre-feature vendor. Stamped by mark_onboarding_announced() in the digest post-send bookkeeping.';
COMMENT ON COLUMN vendors.first_organic_drop_at IS
  'CTK-214 -- when the vendor first produced a guarded-just-listed organic survivor AFTER onboarding announcement (bulk_cluster=false + cold-start-survived, INV-08). NULL = a genuinely-fresh onboard awaiting its first organic drop. Stamped once by stamp_first_organic_drop_at() at scrape time. Drives the strip retire policy (frontend).';

-- ===========================================================================
-- One-time backfill -- mark every PRE-FEATURE vendor as already-onboarded so the
-- pending query (Signal 1) surfaces ONLY the genuinely-new dark vendors, not the
-- 14 vendors tracked for months. Without this the next digest would announce
-- "now tracking World Wide Corals / Top Shelf / Aqua SD / ..." -- vendors that
-- predate the feature (CTK-214 build, Option 1; Jon-ratified 2026-06-29).
--
-- The first batch is AUTHORITATIVELY the 4 dark vendors named in the directive --
-- biota, reefundertheroof, coralstop, austinaquafarms. The established set is the
-- complement by EXPLICIT slug-exclusion, NOT a created_at date cutoff (fragile magic
-- constant) and NOT an organic-survivor EXISTS check (would wrongly exclude a dark
-- vendor that already posted an organic drop post-onboarding -> never announced).
--
-- BOTH timestamps -> created_at (Option 1). first_organic_drop_at = created_at (not
-- NULL, not now()) because these vendors have demonstrably dropped organically for
-- months: NULL would lie to the retire predicate ("first drop unknown"), now() would
-- claim "dropped today." The three-way equality (created_at = announced_at = first
-- drop) is a legible "pre-feature backfilled row" signature. It also makes
-- first_organic_drop_at IS NULL mean exactly one thing downstream: "a genuinely-fresh
-- onboard awaiting its first drop." Q2's earlier "NULL=N/A, no backfill" is formally
-- SUPERSEDED here -- it assumed established vendors stay onboarding_announced_at=NULL,
-- which Signal 1's NULL-discriminator structurally cannot honor.
--
-- IS NULL guard makes the backfill fire-once across re-applies: a vendor already
-- stamped (by a real announce or a prior apply) is never clobbered.
UPDATE vendors
SET onboarding_announced_at = created_at,
    first_organic_drop_at   = created_at
WHERE active = true
  AND slug NOT IN ('biota', 'reefundertheroof', 'coralstop', 'austinaquafarms')
  AND slug NOT LIKE '!_%' ESCAPE '!'              -- CTK-213 belt: never touch test vendors
  AND onboarding_announced_at IS NULL;            -- fire-once across re-applies

-- ===========================================================================
-- Signal 1 -- get_pending_onboarding_announcements()
-- Vendors active + not test + not yet announced, with a live browseable-in-stock
-- count n. Only n > 0 rows (a vendor with no browseable stock has nothing to
-- announce). The digest reads this, renders, then stamps via
-- mark_onboarding_announced() AFTER send.
-- ===========================================================================
DROP FUNCTION IF EXISTS get_pending_onboarding_announcements();
CREATE FUNCTION get_pending_onboarding_announcements()
RETURNS TABLE (vendor_slug text, display_name text, n integer)
LANGUAGE sql
STABLE
AS $$
  -- Compute the browseable count ONCE in a derived table, then filter n > 0 outside.
  -- (Postgres does NOT common-subexpression-eliminate a correlated scalar subquery, so
  -- repeating it in SELECT and WHERE would scan vendor_listings twice per candidate --
  -- /code-review CTK-214 [8].)
  SELECT c.vendor_slug, c.display_name, c.n
  FROM (
    SELECT
      v.slug AS vendor_slug,
      v.display_name,
      (
        -- Browseable in-stock catalog size (the honest-framing count). Derived live,
        -- never a stored literal -- it drifts every scrape. NULL-safe set form matching
        -- EXCLUDED_CATEGORIES (INV-07, 0067).
        SELECT count(*)::int
        FROM vendor_listings vl
        WHERE vl.vendor_id = v.id
          AND vl.in_stock = true
          AND (vl.category IS NULL OR vl.category <> ALL(ARRAY['equipment','invert']::text[]))
      ) AS n
    FROM vendors v
    WHERE v.active = true
      AND v.slug NOT LIKE '!_%' ESCAPE '!'        -- CTK-213 test-vendor belt
      AND v.onboarding_announced_at IS NULL
  ) c
  WHERE c.n > 0
  ORDER BY c.n DESC, c.vendor_slug;
$$;

GRANT EXECUTE ON FUNCTION get_pending_onboarding_announcements() TO service_role, authenticated, anon;

-- ===========================================================================
-- Signal 2 -- get_onboarding_strip_state()
-- Announced + not-yet-organically-retired vendors, with both timestamps + the same
-- live browseable-in-stock n. Returns ACTIVE strips only (first_organic_drop_at IS
-- NULL) so the 14 pre-feature backfilled vendors (retired-by-data, first_organic_
-- drop_at = created_at) never ride the payload -- CTK-214 Jon parking-lot 2026-06-29.
--
-- Division of labor: backend drops the ORGANIC-retired set (the binary
-- first_organic_drop_at fact, not a tunable); the FRONTEND owns the 7-day TIME cap
-- (a policy knob) on what remains. first_organic_drop_at is structurally NULL in this
-- view but stays in the RETURNS shape (locked contract) -- a future widening that
-- surfaces just-retired vendors won't change the signature. Row count is bounded by
-- the number of fresh-onboard vendors (a handful), so no window cap.
-- ===========================================================================
DROP FUNCTION IF EXISTS get_onboarding_strip_state();
CREATE FUNCTION get_onboarding_strip_state()
RETURNS TABLE (
  vendor_slug text,
  display_name text,
  n integer,
  onboarded_at timestamptz,
  first_organic_drop_at timestamptz
)
LANGUAGE sql
STABLE
AS $$
  SELECT
    v.slug AS vendor_slug,
    v.display_name,
    (
      SELECT count(*)::int
      FROM vendor_listings vl
      WHERE vl.vendor_id = v.id
        AND vl.in_stock = true
        AND (vl.category IS NULL OR vl.category <> ALL(ARRAY['equipment','invert']::text[]))
    ) AS n,
    v.onboarding_announced_at AS onboarded_at,
    v.first_organic_drop_at
  FROM vendors v
  WHERE v.active = true
    AND v.slug NOT LIKE '!_%' ESCAPE '!'          -- CTK-213 test-vendor belt
    AND v.onboarding_announced_at IS NOT NULL      -- announced (on the strip)
    AND v.first_organic_drop_at IS NULL            -- not yet organically retired
  ORDER BY v.onboarding_announced_at DESC, v.slug;
$$;

GRANT EXECUTE ON FUNCTION get_onboarding_strip_state() TO service_role, authenticated, anon;

-- ===========================================================================
-- mark_onboarding_announced(slugs text[]) -- fire-once stamp for Signal 1.
-- Called by the digest in its post-send bookkeeping (CTK-214 Q3: stamp AFTER a
-- successful send -- a stamp failure re-announces next digest (benign) vs a
-- pre-send stamp silently dropping a vendor on send-failure (under-announce)).
-- Monotonic: only stamps rows still NULL, so a re-call is a no-op (idempotent).
-- Returns the slugs actually stamped this call (for the digest's bookkeeping log).
-- ===========================================================================
DROP FUNCTION IF EXISTS mark_onboarding_announced(text[]);
CREATE FUNCTION mark_onboarding_announced(slugs text[])
RETURNS TABLE (stamped_slug text)
LANGUAGE sql
AS $$
  UPDATE vendors v
  SET onboarding_announced_at = now()
  WHERE v.slug = ANY(slugs)
    AND v.active = true                           -- never stamp an inactive vendor (/code-review CTK-214 [2])
    AND v.slug NOT LIKE '!_%' ESCAPE '!'          -- CTK-213 belt -- parity with every other 0068 vendor scan
    AND v.onboarding_announced_at IS NULL         -- fire-once: never re-stamp
  RETURNING v.slug;
$$;

GRANT EXECUTE ON FUNCTION mark_onboarding_announced(text[]) TO service_role, authenticated, anon;

-- ===========================================================================
-- stamp_first_organic_drop_at(p_vendor_slug text) -- Signal 2's fire-once organic
-- stamp. Called post-persist by the scrape pipeline (after the bulk_cluster flip,
-- so the onboarding flood is already flagged). Owns the FULL gate so the diff.py
-- hook stays a cheap fail-soft trigger:
--   - onboarding_announced_at IS NOT NULL  (post-onboarding only -- a drop in the
--     pre-announce gap has no strip to retire; pre-feature vendors stay NULL)
--   - first_organic_drop_at IS NULL        (fire-once)
--   - EXISTS a guarded-just-listed survivor (bulk_cluster=false + cold-start-
--     survived + not equipment -- the get_vendor_drop_cadence organic population)
-- Returns the stamp when newly set, the existing stamp when already set, NULL when
-- no survivor yet (the common per-scrape no-op). plpgsql: the gate short-circuits
-- the (expensive) 10y guarded scan when the cheap column checks already decide it.
-- ===========================================================================
DROP FUNCTION IF EXISTS stamp_first_organic_drop_at(text);
CREATE FUNCTION stamp_first_organic_drop_at(p_vendor_slug text)
RETURNS timestamptz
LANGUAGE plpgsql
AS $$
DECLARE
  v_announced timestamptz;
  v_existing  timestamptz;
  v_stamp     timestamptz;
BEGIN
  SELECT onboarding_announced_at, first_organic_drop_at
    INTO v_announced, v_existing
  FROM vendors
  WHERE slug = p_vendor_slug
    AND active = true
    AND slug NOT LIKE '!_%' ESCAPE '!';           -- CTK-213 test-vendor belt

  -- Not announced yet, or pre-feature vendor: no strip exists, nothing to stamp.
  IF v_announced IS NULL THEN
    RETURN NULL;
  END IF;

  -- Already stamped (fire-once): no write, no guarded scan -- and RETURN NULL. The
  -- return value means "this call stamped JUST NOW," so the diff.py hook logs only a
  -- genuine first-organic-drop event, never a no-op on the 14 backfilled vendors
  -- (/code-review CTK-214 [3]). first_organic_drop_at IS NULL is the fire-once guard.
  IF v_existing IS NOT NULL THEN
    RETURN NULL;
  END IF;

  -- Has the vendor produced a guarded-just-listed organic survivor? Read the guarded
  -- source DIRECTLY -- guard_disposition='kept' already excludes bulk_cluster (INV-08)
  -- and f7_arrivals_dispositioned's base CTE already excludes equipment+invert (INV-07,
  -- 0067), so NO join-back or re-filter is needed (/code-review CTK-214 [7]). The same
  -- arm get_vendor_drop_cadence reads. Window bounded to 180d -- generous margin past
  -- the strip's retire horizon (the frontend 7-day cap), not the full 10y. EXISTS
  -- short-circuits on the first match.
  -- NOTE (/code-review CTK-214 [1]): a vendor whose post-onboarding drops are ALWAYS
  -- >=50-at-one-timestamp batches is bulk_cluster-suppressed and never yields a kept
  -- survivor -- consistent with INV-08 (a same-timestamp dump is not genuinely-new).
  -- Such a vendor retires via the frontend time cap instead; nil user impact (the
  -- strip still retires).
  IF EXISTS (
    SELECT 1
    FROM get_f7_arrivals_guarded(24 * 180, ARRAY['just-listed']) le
    WHERE le.vendor_slug = p_vendor_slug
  ) THEN
    UPDATE vendors
    SET first_organic_drop_at = now()
    WHERE slug = p_vendor_slug
      AND first_organic_drop_at IS NULL           -- fire-once guard at the write too
    RETURNING first_organic_drop_at INTO v_stamp;
    RETURN v_stamp;
  END IF;

  RETURN NULL;
END;
$$;

GRANT EXECUTE ON FUNCTION stamp_first_organic_drop_at(text) TO service_role, authenticated, anon;
