-- CTK-124 — /deals union scope + window: markdown_started_at column +
-- cold-start backfill + get_recent_price_drops(p_window_days integer)
-- union RPC (CT-observed drops UNION active vendor markdowns).
--
-- Three statements ship here:
--
--   1. ALTER TABLE vendor_listings ADD COLUMN markdown_started_at
--      timestamptz — nullable, no default. Observation-attestation
--      semantics: the value means "when CoralTicker first observed this
--      listing's compare_at_price episode begin," NOT when the vendor
--      actually set the markdown. Capture wiring lands in
--      scrapers/common/diff.py (same push): onset writes on the
--      DB-observed NULL -> non-NULL compare_at_price transition, clears
--      on non-NULL -> NULL, and stays untouched on mid-episode value
--      drift (a markdown deepening from 20% to 30% off is the same
--      episode, not a new one).
--
--   2. Cold-start backfill — SET markdown_started_at = now() WHERE
--      compare_at_price > current_price AND markdown_started_at IS NULL.
--      Same attestation semantics: rows already marked down at apply
--      time get "first attested" = migration time. Honest by
--      construction (we genuinely first observed them now); the
--      alternative (exclude pre-capture markdowns until a fresh delta)
--      would blank the markdown arm for the median listing whose
--      compare_at_price never transitions. IS NULL guard makes re-runs
--      idempotent — a re-apply never resets live onsets.
--      Probe 2026-06-06 (read-only, pre-apply): 1,785 live markdown rows
--      fleet-wide; 1,566 of them TSA at avg 41.4% off — storewide
--      compare-at anchoring, not a sale event. These seed-attested rows
--      age out of the 7-day reader window naturally; only genuine
--      NULL -> non-NULL transitions re-enter after that.
--
--   3. CREATE get_recent_price_drops(p_window_days integer) — two-arm
--      union, NEW SIGNATURE ALONGSIDE the live zero-arg function.
--
-- ─── Overload two-step (zero-arg deliberately NOT dropped) ───
--
-- Postgres identifies functions by name + argument types, so
-- get_recent_price_drops() and get_recent_price_drops(integer) coexist.
-- The live frontend (lib/queries/listings.ts, four statements) calls the
-- zero-arg signature and ORDER BYs its observed_at column; dropping or
-- reshaping it here would 500 /deals from apply until the CTK-124
-- Session 2 frontend deploy. Same code/DB deploy-race class migration
-- 0028's header documents for get_recent_arrivals; same resolution:
--
--     0033 (this migration) — ships the one-arg union function.
--     CTK-124 Session 2     — frontend binds DEALS_WINDOW_DAYS to the
--                             one-arg signature; deploy.
--     0034 (follow-up)      — DROP FUNCTION get_recent_price_drops()
--                             (zero-arg) after a verify cycle. Named in
--                             CTK-124 plan.md; closure-gate carries it.
--
-- p_window_days has NO DEFAULT, for two reasons: (a) a defaulted one-arg
-- overload makes the zero-arg call ambiguous at resolution time while
-- both signatures exist; (b) the window single-sources from the exported
-- DEALS_WINDOW_DAYS constant in lib/queries/listings.ts (CTK-124 D-1,
-- Jon-ratified 7d 2026-06-04) — a DB-side default would be a second,
-- silently divergable copy of that constant (CTK-057 fold precedent:
-- constants are exported and parameter-bound, never duplicated).
--
-- ─── Union shape ───
--
-- Arm 1 (CT-observed drops): LAG-window CTE body verbatim from migration
-- 0028's get_recent_price_drops, with the hardcoded interval '24 hours'
-- parameterized to (p_window_days * interval '1 day'). Window-binds-both-
-- arms ratified by Jon 2026-06-06 — the drop arm widens alongside the
-- markdown arm; a coral that dropped 6 days ago is on /deals.
--
-- Arm 2 (active vendor markdowns): vendor_listings rows where
-- compare_at_price > current_price AND markdown_started_at falls inside
-- the window. Rows with NULL markdown_started_at never qualify (NULL
-- comparison is NULL) — pre-capture markdowns are excluded until the
-- backfill or a live transition attests them. prior_price is NULL on
-- this arm (frontend contract: markdown-only rows carry the slash in
-- compare_at_price; no fabricated prior).
--
-- Both arms: in_stock = true AND auction_end_time IS NULL — INV-05
-- reader-side predicate (coordination-invariants.md INV-05; arm-scoped
-- citation precedent at migration 0028's header).
--
-- Dedup: one row per listing via ROW_NUMBER, price-dropped precedence
-- per migration 0028 canon (precedence_rank, then event_at DESC). NOTE —
-- this retires the multi-event-per-listing semantic 0028 preserved for
-- the zero-arg function (a listing dropping twice in-window showed
-- twice); under a 7-day window the duplicate rows are noise, and the
-- CTK-124 plan mandates one row per listing.
--
-- RETURNS shape: zero-arg shape with observed_at RENAMED event_at (drop
-- arm: ph.observed_at; markdown arm: markdown_started_at). compare_at_
-- price stays in the projection.
--
-- LIMIT 250 (zero-arg carried 100): Q3 measure-before-set probe
-- 2026-06-06 — deduped union estimate 1,794 listings (drop arm 1,540
-- distinct + markdown arm 1,785 - overlap 1,531), dominated by the TSA
-- anchor cohort above. Clears the ratified ~70 threshold; 250 is the
-- ratified ceiling. Day-1 output still truncates until the seed cohort
-- ages out of the window (~7 days post-apply); steady-state expected
-- well under the cap. New function, no compat constraint on the value.
--
-- No price_history write path changes — that table stays (price,
-- in_stock)-only per architecture decision #7 + INV-05 related-contract;
-- markdown events are vendor_listings column state, not history rows.
--
-- Idempotent: ADD COLUMN IF NOT EXISTS; backfill guarded by IS NULL;
-- DROP IF EXISTS scoped to the (integer) signature only (re-running
-- rebinds the union function without touching the live zero-arg).
-- Apply via scripts/apply_migration_0033.py (0028 script shape).

-- ─── 1. Onset column ───
ALTER TABLE vendor_listings
  ADD COLUMN IF NOT EXISTS markdown_started_at timestamptz;

-- ─── 2. Cold-start backfill (observation-attestation seed) ───
UPDATE vendor_listings
SET markdown_started_at = now()
WHERE compare_at_price > current_price
  AND markdown_started_at IS NULL;

-- ─── 3. Union RPC — one-arg overload alongside the live zero-arg ───
DROP FUNCTION IF EXISTS get_recent_price_drops(integer);

CREATE FUNCTION get_recent_price_drops(p_window_days integer)
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
  prior_price numeric,
  event_at timestamptz,
  vendor_slug text,
  vendor_display_name text,
  named_coral_canonical_name text,
  named_coral_slug text,
  named_coral_origin_vendor text
)
LANGUAGE sql
STABLE
AS $$
  WITH drop_events AS (
    -- Arm 1 — CT-observed drops. Body verbatim from 0028's zero-arg
    -- function; interval parameterized to p_window_days.
    SELECT
      e.listing_id,
      e.prior_price,
      e.observed_at AS event_at,
      1             AS precedence_rank
    FROM (
      SELECT
        ph.listing_id,
        ph.price AS new_price,
        LAG(ph.price) OVER (PARTITION BY ph.listing_id ORDER BY ph.observed_at) AS prior_price,
        ph.observed_at
      FROM price_history ph
    ) e
    JOIN vendor_listings vl ON vl.id = e.listing_id
    WHERE e.observed_at > now() - (p_window_days * interval '1 day')
      AND e.new_price IS NOT NULL
      AND e.prior_price IS NOT NULL
      AND e.new_price < e.prior_price
      AND vl.current_price IS NOT NULL
      AND vl.in_stock = true                              -- INV-05 (arm-scoped)
      AND vl.auction_end_time IS NULL                     -- INV-05 (arm-scoped)
  ),
  markdown_events AS (
    -- Arm 2 — active vendor markdowns with attested onset in-window.
    SELECT
      vl.id                  AS listing_id,
      NULL::numeric          AS prior_price,
      vl.markdown_started_at AS event_at,
      2                      AS precedence_rank
    FROM vendor_listings vl
    WHERE vl.compare_at_price > vl.current_price
      AND vl.markdown_started_at > now() - (p_window_days * interval '1 day')
      AND vl.in_stock = true                              -- INV-05 (arm-scoped)
      AND vl.auction_end_time IS NULL                     -- INV-05 (arm-scoped)
  ),
  ranked AS (
    -- One row per listing; price-dropped precedence per 0028 canon.
    SELECT
      u.*,
      ROW_NUMBER() OVER (
        PARTITION BY u.listing_id
        ORDER BY u.precedence_rank, u.event_at DESC
      ) AS rn
    FROM (
      SELECT * FROM drop_events
      UNION ALL
      SELECT * FROM markdown_events
    ) u
  )
  SELECT
    vl.id, vl.vendor_id, vl.raw_title, vl.current_price, vl.compare_at_price, vl.in_stock,
    vl.image_url, vl.product_url, vl.first_seen_at, vl.named_coral_id, vl.match_confidence,
    r.prior_price, r.event_at,
    v.slug              AS vendor_slug,
    v.display_name      AS vendor_display_name,
    nc.canonical_name   AS named_coral_canonical_name,
    nc.slug             AS named_coral_slug,
    nc.origin_vendor    AS named_coral_origin_vendor
  FROM ranked r
  JOIN vendor_listings vl ON vl.id = r.listing_id
  JOIN vendors v ON v.id = vl.vendor_id
  LEFT JOIN named_corals nc ON nc.id = vl.named_coral_id
  WHERE r.rn = 1
  ORDER BY r.event_at DESC
  LIMIT 250;
$$;

-- GRANT explicitly on the (integer) signature per Q2 ack rider —
-- privileges attach per-signature, not per-name; the new overload gets
-- nothing from the zero-arg function's grant.
GRANT EXECUTE ON FUNCTION get_recent_price_drops(integer) TO service_role, authenticated, anon;
