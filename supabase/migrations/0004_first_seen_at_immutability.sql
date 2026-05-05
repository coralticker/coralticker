-- CTK-032 Session 1 — first_seen_at immutability via column-scoped trigger.
--
-- Closes the H2 failure path observed on WWC scraper_runs.id=9 (2026-05-05
-- 08:36:48Z): mixed-decision Phase A UPSERT chunk (3602 new + 1 oos) → PostgREST
-- batch-upsert column-set unioned across rows includes first_seen_at →
-- ON CONFLICT DO UPDATE SET first_seen_at = EXCLUDED.first_seen_at fires
-- with NULL on UPDATE-path rows that omitted the column → 23502 NOT NULL
-- aborts the chunk + the run. Robust under root-cause uncertainty per
-- plan §3 Option A: the trigger + the diff.py payload-omit change together
-- close H1, H2, and (b2) without requiring root-cause certainty before
-- repair lands.
--
-- Mechanism: BEFORE UPDATE OF first_seen_at fires only when first_seen_at
-- is in the SET clause (column-scoped, not BEFORE UPDATE on every column).
-- When it fires, NEW.first_seen_at is forced back to OLD.first_seen_at
-- regardless of incoming value (NULL via EXCLUDED, now() via classify-error,
-- or anything else). INSERT-path is unaffected — DB DEFAULT now() per
-- arch §1.4 + 0001_init.sql:149 handles fresh rows.
--
-- Cascade safety per plan §"Cascade risk on Option A — confirmed clean":
-- no RLS on vendor_listings; service_role bypasses RLS per arch §1.3;
-- BEFORE UPDATE triggers fire on the row regardless of role. No interaction
-- with 0003_grant_postgrest_roles.sql.
--
-- Idempotent: CREATE OR REPLACE on the function; CREATE TRIGGER is dropped-
-- and-recreated for re-run safety.

CREATE OR REPLACE FUNCTION public.preserve_first_seen_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.first_seen_at := OLD.first_seen_at;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS vendor_listings_preserve_first_seen_at ON vendor_listings;

CREATE TRIGGER vendor_listings_preserve_first_seen_at
BEFORE UPDATE OF first_seen_at ON vendor_listings
FOR EACH ROW
EXECUTE FUNCTION public.preserve_first_seen_at();
