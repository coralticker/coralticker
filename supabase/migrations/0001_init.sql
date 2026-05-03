-- CoralTicker v1 schema bootstrap. Migration 0001 / CTK-028.
-- Transcribes architecture-v1.md §1.2-§1.9.1 + §4.2 + §1.3 bucket-bootstrap verbatim.
-- Decision register: #1-#56 (schema-touching subset; 21 rows enumerated in
-- CTK-028/plan.md §"Architecture inheritance") + #57 (path + bucket-bootstrap).
-- Idempotent re-application via `supabase db reset` per arch decision #35.

-- =============================================================================
-- Extensions (must be first; gin_trgm_ops index below depends on pg_trgm).
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;

-- =============================================================================
-- ENUM types.
-- =============================================================================

-- Postgres native ENUM per arch §1.9.1 + decision #46.
-- Initial values cover Phase 2 surfaces named in site.md §1; expand via
-- ALTER TYPE email_signup_source ADD VALUE '<surface>' as marketing surface
-- area grows.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'email_signup_source') THEN
    CREATE TYPE email_signup_source AS ENUM (
      'homepage',
      'footer',
      'new_drops_page',
      'coral_page',
      'vendor_page',
      'other'
    );
  END IF;
END $$;

-- =============================================================================
-- §1.3 vendors
-- =============================================================================

CREATE TABLE vendors (
  id             smallserial PRIMARY KEY,
  slug           text NOT NULL UNIQUE,
  display_name   text NOT NULL,
  base_url       text NOT NULL,
  platform       text NOT NULL CHECK (platform IN ('shopify','custom','reefnbid')),
  scrape_method  text NOT NULL CHECK (scrape_method IN ('products_json','html','playwright')),
  cadence_label  text NOT NULL CHECK (cadence_label IN (
                   'daily','hourly','event-aware','drop-day-aware','30-min','sub-minute')),
  image_strategy text NOT NULL DEFAULT 'mirror'
                 CHECK (image_strategy IN ('mirror','hotlink')),
  active         boolean NOT NULL DEFAULT true,
  created_at     timestamptz NOT NULL DEFAULT now()
);

COMMENT ON COLUMN vendors.image_strategy IS
  'Per-vendor image-handling posture (CTK-019 / decision #52). Runtime-flippable in response to vendor pushback (takedown, image-block) — flip and re-scrape, no code commit. Distinct from YAML config (set-once at scraper-author time, e.g. originator_prefix per #23).';

-- =============================================================================
-- §1.7 named_corals
-- (Created before vendor_listings + aliases — both reference named_corals(id).)
-- =============================================================================

CREATE TABLE named_corals (
  id                      serial PRIMARY KEY,
  canonical_name          text NOT NULL UNIQUE,
  normalized_name         text NOT NULL,
  slug                    text NOT NULL UNIQUE,
  origin_vendor           text NOT NULL CHECK (length(origin_vendor) > 0),
  coral_type              text NOT NULL CHECK (coral_type IN (
                            'sps','lps','softie','zoa','mushroom','anemone','clam','chalice')),
  genus                   text,
  category                smallint NOT NULL CHECK (category IN (1, 2)),
                          -- 1 = stable lineage, 2 = semi-stable (requires vendor prefix)
  requires_vendor_prefix  boolean NOT NULL DEFAULT false,
  approx_price_min        numeric(10,2),
  approx_price_max        numeric(10,2),
  notes                   text,
  source_urls             text[],
  active                  boolean NOT NULL DEFAULT true,
  created_at              timestamptz NOT NULL DEFAULT now(),
  updated_at              timestamptz NOT NULL DEFAULT now()
);

COMMENT ON COLUMN named_corals.slug IS
  'URL-facing identifier for /coral/[slug]. Derived from canonical_name at seed time by lib/slug.ts (kebab-case + lowercase + unaccent). Immutable post-insert per decision #47 — a canonical_name rename does NOT cascade to slug; external URLs and Phase 3 SEO depend on slug stability. Curator-discipline invariant (no DB trigger).';

COMMENT ON COLUMN named_corals.origin_vendor IS
  'Free-text per decision #6. Originators outside v1 scrape list (Tyree, Cherry Corals, ECC, ORA) get string labels like "Tyree/Reeffarmers". Phase 4 may add lineage_originator_vendor_id FK if needed (Q1-1).';

CREATE INDEX idx_nc_normalized ON named_corals (normalized_name);
CREATE INDEX idx_nc_active     ON named_corals (active) WHERE active = true;

-- =============================================================================
-- §1.8 aliases
-- =============================================================================

CREATE TABLE aliases (
  id              serial PRIMARY KEY,
  alias_text      text NOT NULL,
  named_coral_id  integer REFERENCES named_corals(id),
  cluster_label   text,
  match_behavior  text NOT NULL CHECK (match_behavior IN ('auto-link','flag-review')),
  notes           text,
  created_at      timestamptz NOT NULL DEFAULT now(),

  -- Two-shape CHECK per decision #5 / #21: exactly one of (named_coral_id,
  -- cluster_label) is set, and match_behavior follows.
  --   1:1 alias        -> named_coral_id NOT NULL, cluster_label NULL,    'auto-link'
  --   cluster flag     -> named_coral_id NULL,     cluster_label NOT NULL, 'flag-review'
  CHECK (
    (named_coral_id IS NOT NULL AND cluster_label IS NULL AND match_behavior = 'auto-link')
    OR
    (named_coral_id IS NULL AND cluster_label IS NOT NULL AND match_behavior = 'flag-review')
  )
);

CREATE INDEX idx_al_text        ON aliases (alias_text);
CREATE INDEX idx_al_named_coral ON aliases (named_coral_id) WHERE named_coral_id IS NOT NULL;

-- =============================================================================
-- §1.4 vendor_listings
-- =============================================================================

CREATE TABLE vendor_listings (
  id                     bigserial PRIMARY KEY,
  vendor_id              smallint NOT NULL REFERENCES vendors(id),
  vendor_sku             text,
  product_url            text NOT NULL,
  raw_title              text NOT NULL,
  normalized_title       text NOT NULL,
  current_price          numeric(10,2),
  currency               text NOT NULL DEFAULT 'USD',
  in_stock               boolean NOT NULL,
  image_url              text,
  category               text CHECK (category IN (
                           'sps','lps','softie','zoa','mushroom','anemone','clam','chalice',
                           'fish','invert','equipment','other')),

  -- Lineage heuristic set by scraper (input to §3), separate from match result.
  lineage_flag           text NOT NULL DEFAULT 'unknown' CHECK (lineage_flag IN (
                           'unknown','vendor-named','lineage-traceable')),

  -- Named-coral linkage (denormalized per decision #1 — NOT a junction table).
  named_coral_id         integer REFERENCES named_corals(id),
  match_confidence       text CHECK (match_confidence IN ('exact','alias','fuzzy','manual')),
  match_method           text,
  matched_at             timestamptz,

  first_seen_at          timestamptz NOT NULL DEFAULT now(),
  last_seen_at           timestamptz NOT NULL DEFAULT now(),
  last_price_changed_at  timestamptz,

  UNIQUE (vendor_id, product_url)
);

COMMENT ON COLUMN vendor_listings.normalized_title IS
  'Lowercased, whitespace-collapsed, unaccented title. Vendor prefix PRESERVED (decision #18 — §3.2 cascade fix). Do NOT strip the vendor prefix during normalization; the matcher cascade depends on it.';

COMMENT ON COLUMN vendor_listings.image_url IS
  'Nullable. Interpretation depends on vendors.image_strategy (CTK-019 / decision #54). For mirror strategy: Supabase Storage URL on fetch success, NULL on permanent failure (404/403/upload error) — 1-attempt fetch only, image is presentation. For hotlink strategy: vendor''s own image URL verbatim, no fetch. Frontend reads opaquely.';

COMMENT ON COLUMN vendor_listings.matched_at IS
  'When this listing''s named_coral_id became effective from a user-event perspective (decision #30). Real-time scrape sets now(); cold-start backfill (§3.8) sets first_seen_at (in the past, NOT picked up by notifier). Notifier filters on matched_at > last_poll AND named_coral_id IS NOT NULL (§4.3).';

COMMENT ON COLUMN vendor_listings.match_method IS
  'Free text per decision #19. Carries diagnostic strings: "prefix+seed-exact", "alias-hit", "fuzzy-0.87", "cluster:holy_grail_torch". Open-ended; no CHECK constraint.';

CREATE UNIQUE INDEX idx_vl_sku_unique
  ON vendor_listings (vendor_id, vendor_sku) WHERE vendor_sku IS NOT NULL;

CREATE INDEX idx_vl_last_seen        ON vendor_listings (last_seen_at DESC);
CREATE INDEX idx_vl_vendor_stock     ON vendor_listings (vendor_id, in_stock, last_seen_at DESC);
CREATE INDEX idx_vl_named_coral      ON vendor_listings (named_coral_id) WHERE named_coral_id IS NOT NULL;
CREATE INDEX idx_vl_normalized_title ON vendor_listings USING gin (normalized_title gin_trgm_ops);

-- =============================================================================
-- §1.6 scraper_runs
-- (Created before price_history — price_history.scraper_run_id references it.)
-- =============================================================================

CREATE TABLE scraper_runs (
  id                      bigserial PRIMARY KEY,
  vendor_id               smallint NOT NULL REFERENCES vendors(id),
  started_at              timestamptz NOT NULL DEFAULT now(),
  finished_at             timestamptz,
  status                  text NOT NULL CHECK (status IN ('running','success','failed','partial')),
  listings_seen           integer NOT NULL DEFAULT 0,
  listings_new            integer NOT NULL DEFAULT 0,
  listings_price_changed  integer NOT NULL DEFAULT 0,
  listings_restocked      integer NOT NULL DEFAULT 0,
  listings_oos            integer NOT NULL DEFAULT 0,
  error_class             text CHECK (error_class IN (
                            'http_429','http_5xx','network','html_schema_change','block','parse','timeout','other')),
  error_message           text,
  http_status_last        integer,
  html_hash               text,
  git_sha                 text
);

COMMENT ON COLUMN scraper_runs.html_hash IS
  'Stable-region shape hash per decision #11 + §2.6. Hash of a deliberately-stable subset of the listing page (e.g., first product card''s outer HTML minus prices/timestamps). Sudden change is the "vendor redesigned the site" sentinel — error_class = ''html_schema_change''. NOT a content hash; do not substitute.';

COMMENT ON COLUMN scraper_runs.git_sha IS
  'Scraper version that ran. Essential for "why did scraping break" triage; without it, matching scrape failures to commit history is timestamp guesswork.';

CREATE INDEX idx_sr_vendor_time ON scraper_runs (vendor_id, started_at DESC);
CREATE INDEX idx_sr_failed      ON scraper_runs (started_at DESC) WHERE status IN ('failed','partial');

-- =============================================================================
-- §1.5 price_history
-- =============================================================================

CREATE TABLE price_history (
  id              bigserial PRIMARY KEY,
  listing_id      bigint NOT NULL REFERENCES vendor_listings(id) ON DELETE CASCADE,
  price           numeric(10,2),
  in_stock        boolean NOT NULL,
  observed_at     timestamptz NOT NULL DEFAULT now(),
  scraper_run_id  bigint REFERENCES scraper_runs(id)
);

COMMENT ON TABLE price_history IS
  'Append-only. One row per observed (price, in_stock) CHANGE — not per scrape. Decision #7. Write rule lives in scraper diff logic per §2.2; not enforced at DB level (no trigger).';

CREATE INDEX idx_ph_listing_time ON price_history (listing_id, observed_at DESC);
CREATE INDEX idx_ph_observed     ON price_history (observed_at DESC);

-- =============================================================================
-- §1.9.1 email_signups (Phase 2 pre-auth)
-- =============================================================================

CREATE TABLE email_signups (
  id              serial PRIMARY KEY,
  email           text NOT NULL,
  source          email_signup_source NOT NULL,
  subscribed_at   timestamptz NOT NULL DEFAULT now(),
  confirmed_at    timestamptz,
  unsubscribed_at timestamptz
);

COMMENT ON COLUMN email_signups.email IS
  'Stored as user provided (case preserved for display). Canonicalization for uniqueness via lower(email) functional index, not by mutating stored value.';

COMMENT ON COLUMN email_signups.confirmed_at IS
  'NULL = double-opt-in pending. Notifier filters on confirmed_at IS NOT NULL AND unsubscribed_at IS NULL.';

CREATE UNIQUE INDEX idx_es_email_lower ON email_signups (lower(email));

-- =============================================================================
-- §4.2 notifier_state (single-row Phase 3 v1 schema object per §1.1)
-- =============================================================================

CREATE TABLE notifier_state (
  id              smallint PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  last_poll_at    timestamptz NOT NULL DEFAULT now(),
  last_run_status text NOT NULL DEFAULT 'success',
  updated_at      timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE notifier_state IS
  'Single-row design enforced by CHECK (id = 1). Notifier reads on each run; advances last_poll_at ONLY on full-batch success per §4.2 prose. Partial-success runs leave last_poll_at where it was — next run picks up the gap. §6 alerts when now() - last_poll_at > 6 hr.';

-- Seed the single row at migration time so the notifier never has to ask
-- "does the row exist yet" — it just reads + updates.
INSERT INTO notifier_state (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

-- =============================================================================
-- §1.3 Storage bucket bootstrap (per arch decision #57 + §1.3 prose).
-- =============================================================================

-- listing-images bucket per CTK-019 #51 + arch §1.3 "Bucket bootstrap and RLS
-- posture". public=true so browsers reading vendor_listings.image_url hit the
-- object directly without auth. Idempotent via ON CONFLICT (id) DO NOTHING.
-- No CREATE POLICY ON storage.objects in v1 — scraper writes use the service
-- role key (RLS-bypassing); no anon-key write paths to image storage.
INSERT INTO storage.buckets (id, name, public)
VALUES ('listing-images', 'listing-images', true)
ON CONFLICT (id) DO NOTHING;
