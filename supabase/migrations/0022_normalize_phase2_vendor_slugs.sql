-- CTK-095 Axis 1 — normalize Phase 2 vendor slugs from kebab to snake_case
-- per the CTK-044 slug-shape canon (public URLs kebab; DB / YAML / R2 paths
-- snake; lib/queries/vendors.ts is the only normalization layer).
--
-- Drift root cause: CTK-085 (UC), CTK-086 (Vivid, RC), CTK-087 (TG) scaffolds
-- inserted slugs in kebab form (matching their then-kebab YAML filenames),
-- breaking the canon for 4 of the 11 v1 vendors. /vendor/<kebab>/ pages
-- 404'd on prod because getVendorBySlug() normalizes kebab → snake on read
-- (vendors.ts:42) and the kebab-stored row never matched the snake lookup.
--
-- Application surface is broader than these 4 UPDATEs: kebab YAML filenames
-- were `git mv`d to snake + their `slug:` fields edited + 4 GH Actions
-- workflow `python -m scrapers.common.run <slug>` CLI args edited in lock-
-- step + test_tidal_gardens_parse.py YAML_PATH edited. All land in the same
-- commit as this migration so cron windows don't catch a half-renamed state.
--
-- R2 + image_url left alone — diff.py:140-149 contract preserves existing
-- in_stock rows' image_url on UPDATE, so kebab R2 keys keep serving live
-- listings; future Phase B writes derive snake R2 prefix from the renamed
-- vendors.slug. Orphan kebab R2 objects natural-decay per
-- project_catalog_rotation_natural_recovery memory as listings turn over.
--
-- Single-token vendors (jf, tsa, wwc, poto, aquasd, battlecorals) +
-- pacific_east (already snake) — unaffected. WHERE-clause matches the
-- 4 drift slugs exactly; no false-positive risk on the 11-row table.

UPDATE vendors SET slug = 'reef_chasers'     WHERE slug = 'reef-chasers';
UPDATE vendors SET slug = 'tidal_gardens'    WHERE slug = 'tidal-gardens';
UPDATE vendors SET slug = 'unique_corals'    WHERE slug = 'unique-corals';
UPDATE vendors SET slug = 'vivid_aquariums'  WHERE slug = 'vivid-aquariums';
