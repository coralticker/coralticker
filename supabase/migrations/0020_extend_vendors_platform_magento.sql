-- CTK-087 Session 2 — extend `vendors.platform` CHECK constraint to accept
-- 'magento' per architecture-v1.md decision register (Magento = third
-- supported v1 platform class after shopify + bigcommerce).
--
-- Magento (server-rendered category-grid HTML, BS4 static parse) is the
-- platform behind Tidal Gardens (CTK-087 Session 1 investigation resolved
-- vendor-scan §8's "platform unclear"). Tidal Gardens is the first (and at v1
-- the only) consumer; a future second Magento vendor onboards with only the
-- per-vendor row INSERT shape (sibling migration like
-- 0021_add_tidal_gardens_vendor.sql), not a re-application of this CHECK
-- extension. Single-file vendor parser (scrapers/vendors/tidal_gardens.py),
-- no shared parse_magento.py until rule-of-three fires (arch §2.8).
--
-- Single transaction, DROP+ADD atomic — mirrors
-- 0014_extend_vendors_platform_bigcommerce.sql. scrapers.common.db.get_conn
-- opens the connection with autocommit=True (db.py:61), so without an explicit
-- BEGIN/COMMIT wrapper each ALTER would commit independently — between the DROP
-- and the ADD there'd be a constraint-absent window where a concurrent INSERT
-- could write platform='something_else' and bypass the whitelist. BEGIN/COMMIT
-- wraps both ALTERs into one transaction; PG's table-level lock on the second
-- ALTER waits for the first to release, so DROP and ADD land atomically from
-- any concurrent reader/writer's perspective.
--
-- Apply order pin: this migration applies BEFORE
-- 0021_add_tidal_gardens_vendor.sql (which INSERTs platform='magento'). INSERT
-- against the un-extended CHECK would fail with constraint-violation.
--
-- Apply path is the architecture-v1.md decision register row #65 canonical:
-- single-file cursor.execute() via scrapers.common.db.get_conn against
-- NEON_DATABASE_URL. Idempotent re-application via `DROP CONSTRAINT IF EXISTS`
-- — re-run after the first apply is a clean no-op.
--
-- Constraint name `vendors_platform_check` is the PG-default for the inline
-- column-level CHECK declared in 0001_init.sql:45, last extended to
-- 'bigcommerce' at 0014. The full whitelist after this migration:
-- shopify / custom / reefnbid / bigcommerce / magento.

BEGIN;

ALTER TABLE vendors DROP CONSTRAINT IF EXISTS vendors_platform_check;
ALTER TABLE vendors ADD CONSTRAINT vendors_platform_check
  CHECK (platform IN ('shopify','custom','reefnbid','bigcommerce','magento'));

COMMIT;
