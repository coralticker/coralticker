-- CTK-087 — Tidal Gardens vendors row (Phase 2 scraper #11, the last v1
-- launch vendor — completes the plan §V1 vendor list).
--
-- Closes the data-side prerequisite for the Tidal Gardens scraper:
-- scrapers/common/run.py:db.fetch_vendor() reads this row at stage 1 (Config)
-- of the arch §2.1 lifecycle, then merges with scrapers/vendors/
-- tidal-gardens.yaml per arch §2.3 (DB row wins on conflict). Without this
-- row the scraper fails fast at stage 1 — loud-failure-not-silent-skip.
--
-- Apply order: AFTER 0020_extend_vendors_platform_magento.sql (which extends
-- the platform CHECK to accept 'magento'). This INSERT against the un-extended
-- CHECK would fail with constraint-violation.
--
-- vendor_id=11 disposition per CTK-087 plan §Scope item 5 + the reservation
-- noted in 0019_add_poto_vendor.sql ("Tidal Gardens is reserved at 11"). POTO
-- took id=10; id range 11-12 is the unused gap below the test-row tail.
--
-- Sequence + collision check (CTK-087 Session 2, confirmed on Neon 2026-05-28):
-- MAX(vendors.id) = 14. Real vendors occupy 1-10; test rows hold the tail
-- (_ctk033_test id=13, _ctk029_test id=14). id range 11-12 is UNUSED — so the
-- explicit id=11 INSERT is collision-free, and the trailing setval is a no-op
-- (id=11 < MAX 14 -> setval(MAX(id)) leaves the sequence at 14).
--
-- vendors-row columns (per supabase/migrations/0001_init.sql:40-53 schema):
--   - id = 11           smallserial primary key; explicit literal for
--                       open-items.md L25 vendor-ID stability watch.
--   - slug = 'tidal-gardens'        matches scrapers/vendors/tidal-gardens.yaml
--                                    filename + .github/workflows/tidal-gardens
--                                    .yml run arg (run.py CLI). Hyphenated per
--                                    the CTK-093 slug/YAML-filename-parity fix.
--   - display_name = 'Tidal Gardens'   Copley, OH per .claude/research/
--                                       phase-1.5-vendor-scan.md §8.
--   - base_url = 'https://tidalgardens.com'  canonical domain.
--   - platform = 'magento'        CTK-087 Session 1 investigation 2026-05-28
--                                  (x-magento-cache-debug header + 48 markers);
--                                  cite-back in scrapers/vendors/tidal-gardens
--                                  .yaml. Requires the 0020 CHECK extension.
--   - scrape_method = 'html'      server-rendered category-grid HTML scrape
--                                  via scrapers/vendors/tidal_gardens.py BS4
--                                  parse (same scrape_method value as the BC
--                                  Stencil vendors; no Playwright).
--   - cadence_label = 'daily'     CTK-087 plan §Q cadence lock (Jon 2026-05-28).
--                                  Monthly YouTube-Live drops; not hourly-
--                                  volatile. Workflow cron 31 10 * * * UTC,
--                                  off-minute per open-items.md L53.
--   - image_strategy = 'mirror'   default per arch §1.3 + CTK-019 #52;
--                                  runtime-flippable to 'hotlink' via UPDATE.
--   - active = true               workflow_dispatch fires immediately; first
--                                  scheduled cron firing at next 10:31 UTC.
--
-- Idempotent re-application: ON CONFLICT (slug) DO NOTHING preserves the row
-- across migration re-runs + supabase db reset cycles.
--
-- seed.sql parity note: supabase/seed.sql carries Phase 1 vendors 1-4 only per
-- CTK-028 D3 sub-option (a); this migration is the canonical add-path for
-- Tidal Gardens.

INSERT INTO vendors (id, slug, display_name, base_url, platform, scrape_method, cadence_label, image_strategy, active)
VALUES
  (11, 'tidal-gardens', 'Tidal Gardens', 'https://tidalgardens.com', 'magento', 'html', 'daily', 'mirror', true)
ON CONFLICT (slug) DO NOTHING;

-- Bump the smallserial sequence past the explicit-id INSERT so subsequent
-- vendor INSERTs without an explicit id don't collide. No-op under current
-- sequence state (MAX(id)=14 from _ctk029_test; id=11 < 14).
SELECT setval(
  pg_get_serial_sequence('vendors', 'id'),
  (SELECT MAX(id) FROM vendors)
);
