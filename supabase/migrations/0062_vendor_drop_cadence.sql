-- CTK-204 — per-vendor drop-cadence query family feeding the /vendor/[slug]
-- "drop rhythm" section. Two row-returning functions, ONE honest-organic
-- population. New names, zero blast radius on the live RPCs (no DROP, no REPLACE
-- of an existing function).
--
-- ─── The honest-organic population (the whole correctness story) ───
--
-- A vendor's "drops" are derived from the SAME guarded recipe as
-- get_aggregate_activity (migration 0058), NOT a raw vendor_listings read. Two
-- guards stack, and BOTH halves are load-bearing:
--
--   1. get_f7_arrivals_guarded(window_hours, ARRAY['just-listed']) — strips the
--      median-relative read-side noise: cold-start onboarding dumps (a newly
--      watched vendor's whole catalog registering as just-listed on first scrape)
--      and bulk re-index surges. This is migration 0052's guarded source.
--   2. JOIN vendor_listings vl ON vl.id = le.id
--        WHERE vl.category IS DISTINCT FROM 'equipment'   -- INV-07 (NULL-safe denylist)
--          AND vl.bulk_cluster = false                    -- INV-08 (persisted single-
--                                                         --         timestamp cohort flag)
--
-- Why both: bulk_cluster = false alone leaves cold-start onboarding rows in.
-- Live (2026-06-28): Battlecorals 280 raw just-listed -> 0 organic (its whole
-- signal is a 494-row cold-start dump on 2026-05-25, all cold_start-dispositioned;
-- the 5 listings first-seen 2026-05-31 are in_stock=false OOS-on-arrival rows that
-- emit no just-listed lead-event, so they are NOT drops). Shipping the raw
-- predicate would fabricate rhythm on quiet/onboarding vendors — the exact
-- trust-floor break this ticket forbids. The guarded source is the missing half.
--
-- ─── Scope A — get_vendor_recent_drops — recent-drops feed, all vendors ───
--
-- Row-returning over the honest-organic population for ONE vendor, ORDER BY
-- first_seen_at DESC. Projects exactly the get_f7_arrivals_guarded 19-col shape so
-- the render reuses the existing arrival-row mapping. An EMPTY result is the
-- honest "quiet lately" state (Cornbred, Battlecorals, the 3 new onboarders) —
-- render-side, never an error.
--
-- ─── Scope B — get_vendor_drop_cadence — day-of-week histogram + computed gate ───
--
-- One summary row per vendor: watch history span, organic drop count, last organic
-- drop, median scrape gap, 7 day-of-week buckets, and a COMPUTED
-- qualifies_for_histogram flag (never a hardcoded vendor allowlist).
--
--   qualifies_for_histogram = history_days >= 42
--                         AND median_scrape_gap_hours <= 6
--                         AND organic_drop_count >= 15
--
-- The gate isolates vendors with enough watched history + tight-enough scrape
-- cadence + enough real drops to draw an honest 7-bucket histogram. Verified live
-- (2026-06-28) to return exactly {wwc, tsa, jf, pacific_east}:
--
--   * history_days = now - first successful scrape (observation span, NOT the
--     organic-drop span — a quiet vendor still has long history). The >= 42 cut is
--     razor-sharp on live data: the four qualifiers sit at 47-55 days; the next
--     vendor down is 34. history AND gap alone already isolate the four.
--   * median_scrape_gap_hours <= 6 splits the bimodal scrape cluster: qualifiers
--     run ~2-3h, daily vendors (tidal_gardens, aquasd, battlecorals) ~24h. NOT
--     == 1h — no vendor scrapes exactly hourly. Daily-cadence vendors are excluded
--     because first-seen-day approximates scrape-day too coarsely for a DOW claim.
--   * organic_drop_count >= 15 is the empty-histogram floor. With the current
--     fleet, history + gap already isolate the four, so this floor's live job is
--     DEFENSIVE: it blocks a future vendor that ages past 42d with hourly cadence
--     but ~0 real drops (e.g. Cornbred today: history 8d, gap 2.3h, organic 0 —
--     it will cross 42d history in ~2026-07 and must NOT then render an empty
--     7-bar chart). The threshold is 15, not the directive's literal 25: live
--     tsa = 22 organic drops, and the ratified qualifying set includes tsa, so 25
--     drops it. 15 admits tsa with margin and stays a meaningful ~2/bucket floor.
--     See CTK-204 results.md (2026-06-28) for the variant table + lead-backend flag.
--
-- DOW buckets use EXTRACT(DOW FROM first_seen_at AT TIME ZONE 'UTC') — 0=Sunday,
-- 6=Saturday. UTC for consistency with the existing newness surfaces (the guard
-- baseline + _arrival_day both bucket in UTC); a local-tz shift would silently
-- move drops across the midnight boundary and skew the histogram.
--
-- Deferred (NOT built here): flash-sale labeling, hour-of-day cadence — not
-- derivable from first_seen_at / listings_new alone (CTK-204 plan).
--
-- ─── Idempotency + apply path ───
--
-- Both are CREATE FUNCTION (new names). GRANT EXECUTE to migration 0052's grantee
-- set (service_role, authenticated, anon). Apply via
-- scripts/apply_migration_0062.py (mirrors apply_migration_0058.py:
-- scrapers.common.db.get_conn against NEON_DATABASE_URL per architecture-v1.md
-- decision #65). Re-running requires DROP first (CREATE, not CREATE OR REPLACE) —
-- the apply script DROPs both signatures before re-creating so it is re-runnable.


-- ─── Scope A — get_vendor_recent_drops — honest-organic feed for one vendor ───
CREATE FUNCTION get_vendor_recent_drops(
  p_vendor_slug text,
  p_window_days int DEFAULT 60,
  p_limit int DEFAULT NULL
)
RETURNS TABLE (
  id bigint,
  vendor_id smallint,
  raw_title text,
  current_price numeric,
  compare_at_price numeric,
  in_stock boolean,
  image_url text,
  product_url text,
  first_seen_at timestamptz,
  named_coral_id integer,
  match_confidence text,
  event text,
  event_at timestamptz,
  prior_price numeric,
  vendor_slug text,
  vendor_display_name text,
  named_coral_canonical_name text,
  named_coral_slug text,
  named_coral_origin_vendor text
)
LANGUAGE sql
STABLE
AS $$
  SELECT
    le.id, le.vendor_id, le.raw_title, le.current_price, le.compare_at_price, le.in_stock,
    le.image_url, le.product_url, le.first_seen_at, le.named_coral_id, le.match_confidence,
    le.event, le.event_at, le.prior_price, le.vendor_slug, le.vendor_display_name,
    le.named_coral_canonical_name, le.named_coral_slug, le.named_coral_origin_vendor
  FROM get_f7_arrivals_guarded(p_window_days * 24, ARRAY['just-listed']) le
  JOIN vendor_listings vl ON vl.id = le.id
  WHERE le.vendor_slug = p_vendor_slug
    AND vl.category IS DISTINCT FROM 'equipment'   -- INV-07
    AND vl.bulk_cluster = false                    -- INV-08
  ORDER BY le.first_seen_at DESC
  LIMIT p_limit;
$$;

GRANT EXECUTE ON FUNCTION get_vendor_recent_drops(text, int, int) TO service_role, authenticated, anon;


-- ─── Scope B — get_vendor_drop_cadence — one summary row, computed gate ───
CREATE FUNCTION get_vendor_drop_cadence(p_vendor_slug text)
RETURNS TABLE (
  history_days int,
  organic_drop_count int,
  last_organic_drop_at timestamptz,
  median_scrape_gap_hours numeric,
  dow_sun int,
  dow_mon int,
  dow_tue int,
  dow_wed int,
  dow_thu int,
  dow_fri int,
  dow_sat int,
  qualifies_for_histogram boolean
)
LANGUAGE sql
STABLE
AS $$
  WITH v AS (
    SELECT id FROM vendors WHERE slug = p_vendor_slug
  ),
  -- Watch history span: now - first successful scrape. Observation span, NOT the
  -- organic-drop span — a quiet vendor still carries long history. Sourced from
  -- scraper_runs (immune to listing pruning) and consistent with the gap CTE.
  watch AS (
    SELECT (now()::date - MIN(sr.finished_at)::date)::int AS history_days
    FROM scraper_runs sr
    JOIN v ON v.id = sr.vendor_id
    WHERE sr.status = 'success'
      AND sr.finished_at IS NOT NULL
  ),
  -- Honest-organic drops over the vendor's full watch history (window spans ~10y
  -- to cover everything since onboarding). guarded just-listed + INV-07 + INV-08.
  organic AS (
    SELECT
      le.first_seen_at,
      EXTRACT(DOW FROM le.first_seen_at AT TIME ZONE 'UTC')::int AS dow
    FROM get_f7_arrivals_guarded(24 * 3650, ARRAY['just-listed']) le
    JOIN vendor_listings vl ON vl.id = le.id
    WHERE le.vendor_slug = p_vendor_slug
      AND vl.category IS DISTINCT FROM 'equipment'   -- INV-07
      AND vl.bulk_cluster = false                    -- INV-08
  ),
  agg AS (
    SELECT
      COUNT(*)::int                            AS organic_drop_count,
      MAX(first_seen_at)                       AS last_organic_drop_at,
      COUNT(*) FILTER (WHERE dow = 0)::int     AS dow_sun,
      COUNT(*) FILTER (WHERE dow = 1)::int     AS dow_mon,
      COUNT(*) FILTER (WHERE dow = 2)::int     AS dow_tue,
      COUNT(*) FILTER (WHERE dow = 3)::int     AS dow_wed,
      COUNT(*) FILTER (WHERE dow = 4)::int     AS dow_thu,
      COUNT(*) FILTER (WHERE dow = 5)::int     AS dow_fri,
      COUNT(*) FILTER (WHERE dow = 6)::int     AS dow_sat
    FROM organic
  ),
  -- Median scrape gap (hours) over the last 14d of successful runs — the cadence
  -- regularity signal the histogram gate leans on.
  gaps AS (
    SELECT
      EXTRACT(EPOCH FROM (
        sr.finished_at - LAG(sr.finished_at) OVER (ORDER BY sr.finished_at)
      )) / 3600.0 AS gap_h
    FROM scraper_runs sr
    JOIN v ON v.id = sr.vendor_id
    WHERE sr.status = 'success'
      AND sr.finished_at IS NOT NULL
      AND sr.finished_at >= now() - interval '14 days'
  ),
  gap AS (
    SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY gap_h) AS median_gap_h
    FROM gaps
    WHERE gap_h IS NOT NULL
  )
  SELECT
    w.history_days,
    a.organic_drop_count,
    a.last_organic_drop_at,
    round(g.median_gap_h::numeric, 2) AS median_scrape_gap_hours,
    a.dow_sun, a.dow_mon, a.dow_tue, a.dow_wed, a.dow_thu, a.dow_fri, a.dow_sat,
    (
      w.history_days >= 42
      AND g.median_gap_h IS NOT NULL
      AND g.median_gap_h <= 6
      AND a.organic_drop_count >= 15
    ) AS qualifies_for_histogram
  FROM watch w
  CROSS JOIN agg a
  CROSS JOIN gap g;
$$;

GRANT EXECUTE ON FUNCTION get_vendor_drop_cadence(text) TO service_role, authenticated, anon;
