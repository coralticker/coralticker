-- CTK-124 Session 3b — get_recent_price_drops(integer) body revision:
-- deterministic ORDER BY tiebreak + LIMIT removal (cap relocates to the
-- view layer) + markdown-arm 5% floor mirroring the card gate.
--
-- CREATE OR REPLACE — signature and RETURNS are unchanged from 0033/0034
-- state, so no DROP is needed and per-signature grants survive (GRANT
-- still re-asserted below per convention). Three body changes:
--
--   (a) Final ORDER BY gains a unique tiebreak: r.event_at DESC,
--       r.listing_id. event_at alone is massively non-unique — the 0033
--       cold-start backfill stamped 4,065 onsets with the same apply-
--       moment timestamp, so row order within that cohort was planner-
--       dependent and could differ call-to-call. listing_id is unique
--       per output row (one-row-per-listing dedup), so the pair is a
--       total order: two consecutive calls return the identical id
--       sequence.
--
--   (b) LIMIT removed. The 0033 LIMIT 250 truncated BEFORE the view-
--       layer wrapper applied sort + category — price-asc was sorting
--       the newest-250 by event_at (cheapest-of-the-newest, not
--       cheapest), and category filters sampled within the same global
--       newest-250. The cap relocates to the view-layer wrapper AFTER
--       filter/sort (lib/queries/listings.ts), where it truncates the
--       right set. The window predicates bound the uncapped output
--       (probe 2026-06-06: ~1,794-row ceiling, shrinking as the seed
--       cohort ages out).
--
--       SEQUENCING — INVERTED from the usual apply-pre-push order: the
--       frontend wrapper cap deploys FIRST (a no-op against the still-
--       capped RPC), THEN this migration applies. Applying first would
--       uncap /deals at ~1,794 rows for the deploy gap. The apply moment
--       coordinates with the frontend deploy; this migration's own push
--       follows normally.
--
--   (c) Markdown arm gains the 5% floor: compare_at_price >=
--       current_price * 1.05, INCLUSIVE >=, not strict > — mirroring the
--       card gate at components/listing-card.tsx:12 exactly
--       (compareAtPrice >= currentPrice * 1.05). The point is
--       count == render: every row the RPC counts into the /deals
--       eyebrow renders a price-treatment card, so sub-5% token
--       markdowns can no longer inflate the count with bare-price rows.
--       SQL-side this needs no IEEE754 workaround: compare_at_price and
--       current_price are numeric, and numeric * numeric-literal
--       arithmetic is exact, so an exactly-5% row admits
--       deterministically (the JS gate computes in floats; divergence is
--       possible only at the exact boundary and only by float noise —
--       accepted, not worked around).
--       Probe 2026-06-06: 0 of 1,814 in-window markdown rows fall below
--       the floor today — the change is a structural pin on the
--       count == render invariant, not a live-data cut.
--
-- INV-05 predicates (in_stock = true AND auction_end_time IS NULL, both
-- arms), event_at projection, ROW_NUMBER one-row-per-listing dedup with
-- price-dropped precedence — all carried verbatim from 0033. Drop arm
-- body remains 0028-canon LAG CTE.
--
-- Idempotent: CREATE OR REPLACE; re-running rebinds the same body.
-- Apply via scripts/apply_migration_0035.py.

CREATE OR REPLACE FUNCTION get_recent_price_drops(p_window_days integer)
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
    -- Arm 1 — CT-observed drops. Body verbatim from 0028's canon LAG
    -- CTE; interval parameterized to p_window_days (0033).
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
    -- Arm 2 — active vendor markdowns with attested onset in-window,
    -- at or above the 5% card-gate floor (change (c)).
    SELECT
      vl.id                  AS listing_id,
      NULL::numeric          AS prior_price,
      vl.markdown_started_at AS event_at,
      2                      AS precedence_rank
    FROM vendor_listings vl
    WHERE vl.compare_at_price >= vl.current_price * 1.05
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
  ORDER BY r.event_at DESC, r.listing_id                  -- change (a): total order
$$;

-- Privileges survive CREATE OR REPLACE; re-asserted per convention for
-- audit adjacency (per-signature, as 0033 established).
GRANT EXECUTE ON FUNCTION get_recent_price_drops(integer) TO service_role, authenticated, anon;
