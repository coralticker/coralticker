-- 0031_fix_origin_vendor_originator_attribution.sql
-- CTK-126 seed-attribution audit — corrects two named_corals rows whose
-- origin_vendor + canonical_name carried a RESELLER prefix over the true
-- strain-originator. Jon-ratified 2026-06-05; brand canon landed at
-- branding-guide.md §"Originator full names" (Pro Corals + GARF drift-added,
-- reseller-prefix-shed ruling).
--
--   id=1  PC Rainbow Acropora — originator Pro Corals (Jim & Sonny, ~2005);
--         Battlecorals is one of many resellers (row source slug is
--         battlecorals.com/products/pro-corals-rainbow-acro).
--   id=14 GARF Bonsai Acropora — originator GARF (Geothermal Aquaculture
--         Research Foundation, Leroy Headlee); TSA is a reseller. "Garf"->"GARF"
--         acronym casing per branding-guide §"Type label casing".
--
-- Per architecture-v1.md:
--   #47 — slug is immutable post-insert; a canonical_name change does NOT
--          cascade to slug. So slug is DELIBERATELY UNTOUCHED here:
--          /coral/battlecorals-pc-rainbow and /coral/tsa-garf-bonsai-acropora
--          keep resolving. The page TITLE (canonical_name) is the user-visible
--          honesty surface; the slug is an opaque permalink (#47 example is
--          renaming "JF Homewrecker" while keeping /coral/jf-homewrecker).
--   #18 — normalized_name is the matcher's stage-1 canonical key
--          (matcher.py canonical_index). It MUST track canonical_name or the
--          renamed canonical stops matching at stage-1. Updated in lockstep:
--          lowercase + unaccent + whitespace-collapse of the new canonical.
--   #65 — apply via scripts/apply_migration_0031.py (scrapers.common.db).
--
-- Aliases: the old reseller-prefixed forms are PRESERVED as alias rows so
-- listings still titled the old way keep landing (stage-4 substring auto-link).
-- The pre-existing 'pc rainbow acropora' / 'garf bonsai acropora' aliases are
-- KEPT, not deleted: stage-4 is substring-match (matcher.py:265) while the
-- canonical only matches exact/prefix, so those aliases still add mid-title
-- coverage the canonical does not — "redundant with the canonical" holds only
-- for exact/prefix hits, not substring. No DB uniqueness constraint on
-- aliases.alias_text; keeping them is strictly additive. Net alias change here
-- is 2 INSERTs, 0 DELETEs.
--
-- Guarded WHEREs (id + old value) fail-safe to 0 rows if state already drifted.

BEGIN;

-- id=1 — Battlecorals PC Rainbow -> PC Rainbow Acropora (origin Pro Corals)
UPDATE named_corals
   SET canonical_name  = 'PC Rainbow Acropora',
       normalized_name = 'pc rainbow acropora',
       origin_vendor   = 'Pro Corals'
 WHERE id = 1
   AND canonical_name = 'Battlecorals PC Rainbow'
   AND origin_vendor  = 'Battlecorals';

-- id=14 — TSA Garf Bonsai Acropora -> GARF Bonsai Acropora (origin GARF)
UPDATE named_corals
   SET canonical_name  = 'GARF Bonsai Acropora',
       normalized_name = 'garf bonsai acropora',
       origin_vendor   = 'GARF'
 WHERE id = 14
   AND canonical_name = 'TSA Garf Bonsai Acropora'
   AND origin_vendor  = 'TSA';

-- Preserve old reseller-prefixed canonical forms as auto-link aliases.
-- match_behavior='auto-link' + named_coral_id NOT NULL + cluster_label NULL
-- satisfies aliases_check. alias_text stored normalized (lowercase) per the
-- migration 0013 seed convention (normalize at INSERT time).
INSERT INTO aliases (alias_text, named_coral_id, match_behavior, notes)
VALUES
  ('battlecorals pc rainbow', 1, 'auto-link',
   'Old canonical pre-CTK-126 reseller-prefix shed (Battlecorals = reseller). Preserves existing matches.'),
  ('tsa garf bonsai acropora', 14, 'auto-link',
   'Old canonical pre-CTK-126 reseller-prefix shed (TSA = reseller). Preserves existing matches.');

COMMIT;

-- Expect: 1 + 1 named_corals rows updated, 2 aliases inserted.
