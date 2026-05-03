-- CoralTicker seed data. Runs after migrations on `supabase db reset`.
-- Per CTK-028 D3 sub-option (a): Phase 1 vendor rows baked at CTK-028 close.
-- Phase 2+ vendors deferred to per-vendor tickets where cadence_label /
-- image_strategy / scrape_method get weighed in context.
--
-- Vendor IDs are stable from this seed:
--   1 = Pacific East   (CTK-024)
--   2 = WWC            (CTK-025)
--   3 = TSA            (CTK-026)
--   4 = JF             (CTK-027)
--
-- Per-scraper tickets verify their row landed (no INSERT) and proceed.
-- base_url values are best-guess from research/phase-1.5-vendor-scan.md;
-- per-scraper YAML is canonical per arch §2.4. CTK-024+ first manual
-- workflow_dispatch will catch any miss as a fetch failure → SQL UPDATE.
--
-- cadence_label per arch §2.7 (decision #15):
--   Pacific East = daily         (continuous new-arrival flow, daily 03-05 ET cron)
--   WWC          = hourly        (continuous + Sunday-heavy live sales)
--   TSA          = event-aware   (15-min Sat/Sun 11a-11p drop window; hourly otherwise)
--   JF           = drop-day-aware (daily baseline + 5-min on announced-drop days, second workflow)
--
-- platform + scrape_method per research/phase-1.5-vendor-scan.md:
--   All four are Shopify-confirmed (PE, WWC, TSA) or Shopify-likely (JF —
--   confirm before scraper build per research §2). All four start with
--   /products.json scrape_method; per-vendor YAML overrides if needed.
--
-- image_strategy default 'mirror' per arch §1.3 + CTK-019 #52. Operational
-- escalation path (vendor takedown / image-block) is a `vendors` row UPDATE
-- to 'hotlink' + re-scrape, no code commit.
--
-- Idempotent re-application: `supabase db reset` re-runs both the migration
-- AND seed.sql. ON CONFLICT (slug) DO NOTHING preserves any UPDATE made via
-- per-scraper ticket (e.g., base_url corrections, image_strategy flips).

INSERT INTO vendors (slug, display_name, base_url, platform, scrape_method, cadence_label, image_strategy, active)
VALUES
  ('pacific_east', 'Pacific East Aquaculture', 'https://pacificeastaquaculture.com', 'shopify', 'products_json', 'daily',           'mirror', true),
  ('wwc',          'World Wide Corals',        'https://worldwidecorals.com',        'shopify', 'products_json', 'hourly',          'mirror', true),
  ('tsa',          'Top Shelf Aquatics',       'https://topshelfaquatics.com',       'shopify', 'products_json', 'event-aware',     'mirror', true),
  ('jf',           'Jason Fox Signature Corals','https://jasonfoxsignaturecorals.com','shopify', 'products_json', 'drop-day-aware',  'mirror', true)
ON CONFLICT (slug) DO NOTHING;
