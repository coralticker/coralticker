-- CTK-090 Session 1 — extend `vendors.platform` CHECK constraint to accept
-- 'bigcommerce' per architecture-v1.md decision register row #66.
--
-- BC Stencil = third supported v1 platform class. AquaSD (CTK-090) is the
-- first consumer; future BC vendors (vendor-scan §11 flags Coral Farm as a
-- plausible second BC vendor inside Phase 2) onboard with only the per-
-- vendor row INSERT shape (sibling migration like 0015_add_aquasd_vendor.sql),
-- not a re-application of this CHECK extension.
--
-- Single transaction, DROP+ADD atomic per CTK-090 Session 1 review note +
-- /backend-engineer carry-in 2026-05-26. scrapers.common.db.get_conn opens
-- the connection with autocommit=True (per db.py:61), so without an explicit
-- BEGIN/COMMIT wrapper each ALTER would commit independently — between the
-- DROP and the ADD there'd be a constraint-absent window where a concurrent
-- INSERT could write `platform='something_else'` and bypass the whitelist.
-- BEGIN/COMMIT wraps both ALTERs into one transaction; PG's table-level lock
-- on the second ALTER waits for the first to release before applying, so
-- the DROP and ADD land atomically from any concurrent reader/writer's
-- perspective.
--
-- Apply order pin per CTK-090 plan §Scope item 9: this migration applies
-- BEFORE 0015_add_aquasd_vendor.sql (which INSERTs platform='bigcommerce').
-- INSERT against the un-extended CHECK would fail with constraint-violation.
--
-- Apply path is the architecture-v1.md decision register row #65 canonical:
-- single-file cursor.execute() via scrapers.common.db.get_conn against
-- NEON_DATABASE_URL. Idempotent re-application via `DROP CONSTRAINT IF
-- EXISTS` — re-run after the first apply is a clean no-op.
--
-- Constraint name `vendors_platform_check` is the PG-default for the inline
-- column-level CHECK declared in 0001_init.sql:45
-- (`platform text NOT NULL CHECK (platform IN ('shopify','custom','reefnbid'))`).

BEGIN;

ALTER TABLE vendors DROP CONSTRAINT IF EXISTS vendors_platform_check;
ALTER TABLE vendors ADD CONSTRAINT vendors_platform_check
  CHECK (platform IN ('shopify','custom','reefnbid','bigcommerce'));

COMMIT;
