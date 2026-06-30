-- CTK-214 Discord-parity (Option b -- per-channel onboarding state). Supersedes the
-- single onboarding_announced_at stamp (0068) with two channel-scoped stamps so each
-- delivery channel announces a new vendor exactly once, INDEPENDENTLY.
--
-- WHY per-channel: a single stamp races across cron channels -- whichever digest runs
-- first (email vs Discord) stamps onboarding_announced_at, blanking the pending list,
-- and the second channel never announces. Per-channel state resolves it: each channel
-- reads + stamps only its own column.
--
-- first_organic_drop_at stays SINGLE -- "the vendor posted a real organic drop" is a
-- channel-agnostic fact, not a per-channel delivery event.
--
-- CONTINGENCY: this is Option (b). If Jon rules (a) (email-only interim), 0069 is
-- dropped and the 0068 single stamp stands as the email channel (Discord-onboarding
-- spins out under CTK-011). 0069 is additive-then-drop on a live column with NO live
-- consumer yet (the digest/strip frontend is unbuilt), so the blast radius is the
-- column rename alone.
--
-- Apply: python -m scripts.apply_migration 69
-- Verify: verify_0069 (committed != applied, feedback_migration_committed_not_applied).

-- ===========================================================================
-- Columns -- split the single announce stamp into two channel-scoped stamps. The old
-- onboarding_announced_at is DROPPED at the end (no live consumer). Any 0068-era single
-- stamp on it is lost -- benign: no digest has run yet, and a re-announce is the safe
-- failure direction (a double-announce, never a silent under-announce).
-- ===========================================================================
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS onboarding_announced_email_at   timestamptz;
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS onboarding_announced_discord_at timestamptz;

COMMENT ON COLUMN vendors.onboarding_announced_email_at IS
  'CTK-214 -- when the email digest sent this vendor''s "now tracking" onboarding announcement (fire-once, per-channel). NULL = not yet announced on email (pending) or pre-feature. Stamped by mark_onboarding_announced(slugs, ''email'') in post-send bookkeeping.';
COMMENT ON COLUMN vendors.onboarding_announced_discord_at IS
  'CTK-214 -- when the Discord digest sent this vendor''s onboarding announcement (fire-once, per-channel). NULL = not yet announced on Discord (pending) or pre-feature. Stamped by mark_onboarding_announced(slugs, ''discord'') in post-send bookkeeping.';

-- ===========================================================================
-- Re-backfill -- mark every PRE-FEATURE established vendor as already-announced on
-- BOTH channels (created_at), leaving the 4 dark vendors NULL/NULL so each channel
-- announces them independently. AUTHORITATIVE 4-dark set by explicit slug-exclusion
-- (not a date cutoff, not an organic-EXISTS check) + CTK-213 belt.
-- ===========================================================================
DO $$
BEGIN
  -- MIGRATE-ONCE: run the backfill ONLY while 0068's single onboarding_announced_at
  -- column still exists -- i.e. the FIRST apply. This migration drops that column below,
  -- so a re-apply (the runner has no migration-tracking table; the file is written to be
  -- idempotent) finds it gone and SKIPS the backfill entirely. This closes the re-apply
  -- silence-a-new-vendor hole: a genuinely-pending vendor onboarded AFTER the first apply
  -- (NULL/NULL, not in the dark set) is never stamped already-announced by a replay
  -- (/code-review 0069 [1]). The old per-column IS NULL guard could NOT tell that vendor
  -- from a pre-feature established one; the existence guard does.
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'vendors' AND column_name = 'onboarding_announced_at'
  ) THEN
    -- Sets ALL THREE state columns -- both channel stamps AND first_organic_drop_at =
    -- created_at -- so the strip-exclusion invariant (announced + organically-retired)
    -- is re-established by 0069 ITSELF, not inherited from 0068's surviving column state
    -- (/code-review 0069 [3]).
    UPDATE vendors
    SET onboarding_announced_email_at   = created_at,
        onboarding_announced_discord_at = created_at,
        first_organic_drop_at           = created_at
    WHERE active = true
      AND slug NOT IN ('biota', 'reefundertheroof', 'coralstop', 'austinaquafarms')
      AND slug NOT LIKE '!_%' ESCAPE '!';            -- CTK-213 belt
  END IF;
END $$;

ALTER TABLE vendors DROP COLUMN IF EXISTS onboarding_announced_at;

-- ===========================================================================
-- Shared honest-framing count -- the browseable in-stock catalog size, with the INV-07
-- predicate in ONE place so get_pending + get_strip can't drift (0067 had to fan an
-- INV-07 widening across 6 functions by hand -- /code-review 0069 [7]). NULL-safe set
-- form: the IS NULL arm keeps reclassified None-category corals visible. Derived live,
-- never a stored literal -- it drifts every scrape.
-- ===========================================================================
DROP FUNCTION IF EXISTS vendor_browseable_in_stock_count(integer);
CREATE FUNCTION vendor_browseable_in_stock_count(p_vendor_id integer)
RETURNS integer
LANGUAGE sql
STABLE
AS $$
  SELECT count(*)::int
  FROM vendor_listings vl
  WHERE vl.vendor_id = p_vendor_id
    AND vl.in_stock = true
    AND (vl.category IS NULL OR vl.category <> ALL(ARRAY['equipment','invert']::text[]));
$$;

GRANT EXECUTE ON FUNCTION vendor_browseable_in_stock_count(integer) TO service_role, authenticated, anon;

-- ===========================================================================
-- Signal 1 -- get_pending_onboarding_announcements(p_channel text)
-- Channel-scoped: vendors active + not test + not yet announced ON THIS CHANNEL, with
-- a live browseable-in-stock count n > 0. plpgsql so an invalid channel RAISES rather
-- than silently returning the wrong (or empty) set.
-- ===========================================================================
DROP FUNCTION IF EXISTS get_pending_onboarding_announcements();
DROP FUNCTION IF EXISTS get_pending_onboarding_announcements(text);
CREATE FUNCTION get_pending_onboarding_announcements(p_channel text)
RETURNS TABLE (vendor_slug text, display_name text, n integer)
LANGUAGE plpgsql
STABLE
AS $$
BEGIN
  IF p_channel NOT IN ('email', 'discord') THEN
    RAISE EXCEPTION 'get_pending_onboarding_announcements: invalid channel %, expected ''email'' or ''discord''', p_channel;
  END IF;

  -- Compute the browseable count ONCE in a derived table, then filter n > 0 outside
  -- (the shared helper carries the honest-framing predicate).
  RETURN QUERY
  SELECT c.vendor_slug, c.display_name, c.n
  FROM (
    SELECT
      v.slug AS vendor_slug,
      v.display_name,
      vendor_browseable_in_stock_count(v.id) AS n
    FROM vendors v
    WHERE v.active = true
      AND v.slug NOT LIKE '!_%' ESCAPE '!'          -- CTK-213 test-vendor belt
      AND CASE p_channel
            WHEN 'email'   THEN v.onboarding_announced_email_at   IS NULL
            WHEN 'discord' THEN v.onboarding_announced_discord_at IS NULL
          END
  ) c
  WHERE c.n > 0
  ORDER BY c.n DESC, c.vendor_slug;
END;
$$;

GRANT EXECUTE ON FUNCTION get_pending_onboarding_announcements(text) TO service_role, authenticated, anon;

-- ===========================================================================
-- Signal 2 -- get_onboarding_strip_state()
-- Channel-AGNOSTIC web surface (neither email nor Discord). A vendor is "on the strip"
-- once announced on AT LEAST ONE channel and not yet organically retired.
--   onboarded_at = LEAST(email_at, discord_at) -- LEAST ignores NULLs, so this is the
--   EARLIEST announce on any channel (NULL only if announced nowhere). The web strip
--   appears as soon as the vendor is announced anywhere.
-- JUDGMENT CALL (the 0069 directive specified channel-param get_pending + mark but left
-- the strip's onboarded_at undefined under per-channel state): LEAST is the minimal
-- generalization of 0068's single onboarded_at and preserves the strip's behavior. If
-- the web strip should instead key off a specific channel (or onboard independently of
-- email/Discord), that's a /lead-frontend + /lead-backend call -- flag, not locked.
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
  -- n > 0 filter mirrors get_pending (/code-review 0069 [0]): an announced-but-not-yet-
  -- retired vendor whose browseable catalog has gone fully OOS must NOT ride the strip as
  -- "now tracking -- 0 pieces" (a dead click). Derived table so n filters once.
  SELECT c.vendor_slug, c.display_name, c.n, c.onboarded_at, c.first_organic_drop_at
  FROM (
    SELECT
      v.slug AS vendor_slug,
      v.display_name,
      vendor_browseable_in_stock_count(v.id) AS n,
      LEAST(v.onboarding_announced_email_at, v.onboarding_announced_discord_at) AS onboarded_at,
      v.first_organic_drop_at
    FROM vendors v
    WHERE v.active = true
      AND v.slug NOT LIKE '!_%' ESCAPE '!'          -- CTK-213 test-vendor belt
      AND (v.onboarding_announced_email_at IS NOT NULL
           OR v.onboarding_announced_discord_at IS NOT NULL)   -- announced on >=1 channel
      AND v.first_organic_drop_at IS NULL            -- not yet organically retired
  ) c
  WHERE c.n > 0
  ORDER BY c.onboarded_at DESC, c.vendor_slug;
$$;

GRANT EXECUTE ON FUNCTION get_onboarding_strip_state() TO service_role, authenticated, anon;

-- ===========================================================================
-- mark_onboarding_announced(slugs text[], p_channel text) -- per-channel fire-once
-- stamp. Called in the channel's post-send bookkeeping (stamp AFTER a successful send;
-- a stamp failure re-announces next digest (benign) vs a pre-send stamp dropping a
-- vendor on send-failure (under-announce)). Stamps only this channel's column; the
-- other channel is untouched, so the two announce independently. Monotonic (only NULL
-- rows), so a re-call no-ops. Returns the slugs actually stamped this call.
-- ===========================================================================
DROP FUNCTION IF EXISTS mark_onboarding_announced(text[]);
DROP FUNCTION IF EXISTS mark_onboarding_announced(text[], text);
CREATE FUNCTION mark_onboarding_announced(slugs text[], p_channel text)
RETURNS TABLE (stamped_slug text)
LANGUAGE plpgsql
AS $$
BEGIN
  IF p_channel NOT IN ('email', 'discord') THEN
    RAISE EXCEPTION 'mark_onboarding_announced: invalid channel %, expected ''email'' or ''discord''', p_channel;
  END IF;

  -- Two explicit branches (one per channel column) -- no dynamic SQL. active + belt
  -- guard every scan (parity with 0068 [2] fold); IS NULL is the fire-once guard.
  IF p_channel = 'email' THEN
    RETURN QUERY
    UPDATE vendors v
    SET onboarding_announced_email_at = now()
    WHERE v.slug = ANY(slugs)
      AND v.active = true
      AND v.slug NOT LIKE '!_%' ESCAPE '!'
      AND v.onboarding_announced_email_at IS NULL
    RETURNING v.slug;
  ELSE
    RETURN QUERY
    UPDATE vendors v
    SET onboarding_announced_discord_at = now()
    WHERE v.slug = ANY(slugs)
      AND v.active = true
      AND v.slug NOT LIKE '!_%' ESCAPE '!'
      AND v.onboarding_announced_discord_at IS NULL
    RETURNING v.slug;
  END IF;
END;
$$;

-- MUTATING function -- NOT granted to anon (unauthenticated). It UPDATEs vendor state,
-- so only the server-side roles get EXECUTE (/code-review 0069 [6]); the read functions
-- above keep the anon grant. The RPC-grant convention (architecture-v1 #65) is read-
-- oriented; this deviation is flagged for /lead-architect to fold into the convention.
GRANT EXECUTE ON FUNCTION mark_onboarding_announced(text[], text) TO service_role, authenticated;

-- ===========================================================================
-- stamp_first_organic_drop_at(p_vendor_slug text) -- unchanged logic except the
-- post-onboarding gate now reads "announced on AT LEAST ONE channel" instead of the
-- single column. Everything else (fire-once-returns-NULL, guarded-source EXISTS, 180d
-- window) is the 0068 [3]/[7] form, reproduced verbatim.
-- ===========================================================================
DROP FUNCTION IF EXISTS stamp_first_organic_drop_at(text);
CREATE FUNCTION stamp_first_organic_drop_at(p_vendor_slug text)
RETURNS timestamptz
LANGUAGE plpgsql
AS $$
DECLARE
  v_announced_any boolean;
  v_existing      timestamptz;
  v_stamp         timestamptz;
BEGIN
  SELECT (onboarding_announced_email_at IS NOT NULL OR onboarding_announced_discord_at IS NOT NULL),
         first_organic_drop_at
    INTO v_announced_any, v_existing
  FROM vendors
  WHERE slug = p_vendor_slug
    AND active = true
    AND slug NOT LIKE '!_%' ESCAPE '!';             -- CTK-213 test-vendor belt

  -- Not announced on any channel, or pre-feature vendor: no strip exists, nothing to
  -- stamp. (v_announced_any is NULL when the vendor row is absent -> falsy -> RETURN.)
  IF v_announced_any IS NOT TRUE THEN
    RETURN NULL;
  END IF;

  -- Already stamped (fire-once): RETURN NULL so the diff.py hook logs only a genuine
  -- first-drop event, never a no-op on the backfilled set (/code-review CTK-214 [3]).
  IF v_existing IS NOT NULL THEN
    RETURN NULL;
  END IF;

  -- Guarded-just-listed survivor? Read the guarded source DIRECTLY -- guard_disposition
  -- ='kept' already excludes bulk_cluster (INV-08) and the base CTE excludes equipment
  -- +invert (INV-07, 0067), so no join/re-filter (/code-review CTK-214 [7]). 180d window
  -- (margin past the strip's retire horizon). The always->=50-batch vendor is
  -- bulk-suppressed and retires via the frontend time cap -- consistent with INV-08,
  -- nil user impact (/code-review CTK-214 [1]).
  IF EXISTS (
    SELECT 1
    FROM get_f7_arrivals_guarded(24 * 180, ARRAY['just-listed']) le
    WHERE le.vendor_slug = p_vendor_slug
  ) THEN
    UPDATE vendors
    SET first_organic_drop_at = now()
    WHERE slug = p_vendor_slug
      AND first_organic_drop_at IS NULL             -- fire-once guard at the write too
    RETURNING first_organic_drop_at INTO v_stamp;
    RETURN v_stamp;
  END IF;

  RETURN NULL;
END;
$$;

-- MUTATING function (UPDATEs first_organic_drop_at) -- NOT granted to anon, same as
-- mark_onboarding_announced (/code-review 0069 [6]).
GRANT EXECUTE ON FUNCTION stamp_first_organic_drop_at(text) TO service_role, authenticated;
