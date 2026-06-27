import { cache } from 'react';
import { unstable_cache } from 'next/cache';
import { getNeonSql } from '@/lib/db/neon';
import { CORAL_RECENCY_DAYS, MS_PER_DAY } from '@/lib/queries/listings';

export interface NamedCoral {
  id: number;
  slug: string;
  canonical_name: string;
  coral_type: string | null;
  genus: string | null;
  lore: string | null;
  origin_vendor: string | null;
  source_urls: string[] | null;
  requires_vendor_prefix: boolean;
  active: boolean;
  has_ever_listed: boolean;
}

// React cache() wrap: /coral/[slug] is dynamic and calls this twice per hit
// (generateMetadata + the page body) — two live Neon roundtrips for the same
// row. cache() dedups within a single request render; chosen over
// unstable_cache because per-request duplication is the defect — no
// cross-request TTL semantics needed on near-static seed rows.
export const getNamedCoralBySlug = cache(
  async (slug: string): Promise<NamedCoral | null> => {
    const sql = getNeonSql();
    const rows = (await sql`
      SELECT
        id,
        slug,
        canonical_name,
        coral_type,
        genus,
        lore,
        origin_vendor,
        source_urls,
        requires_vendor_prefix,
        active,
        -- has_ever_listed: the IDENTICAL EXISTS clause getIndexableCoralSlugs
        -- uses for sitemap inclusion (one predicate, two surfaces — keep in
        -- lockstep, no drift, or sitemap/robots desync). Drives the page-level
        -- noindex for never-listed (lore-only, thin) corals via coralPageRobots
        -- in generateMetadata. The sentinel-VENDOR exclusion (v.slug NOT LIKE,
        -- ESCAPE '!' — backslash collapses in JS template cooking) mirrors the
        -- /corals index lateral. Deliberately NO v.active guard: a coral whose
        -- only listings belong to a RETIRED vendor still renders real historical
        -- content via getCoralAvailability (no v.active filter, listings.ts), so
        -- it is non-thin and stays indexable — v.active is browse-curation, not a
        -- thin-content signal, and gating on it would break ever-listed
        -- monotonicity on vendor retirement.
        EXISTS (
          SELECT 1
          FROM vendor_listings vl
          JOIN vendors v ON v.id = vl.vendor_id
          WHERE vl.named_coral_id = nc.id
            AND v.slug NOT LIKE '!_%' ESCAPE '!'
        ) AS has_ever_listed
      FROM named_corals nc
      WHERE nc.slug = ${slug}
        AND nc.active = true
      LIMIT 1
    `) as unknown as NamedCoral[];

    const row = rows[0];
    if (!row) return null;
    return row;
  },
);

export async function getAllNamedCoralSlugs(): Promise<{ slug: string }[]> {
  const sql = getNeonSql();
  const rows = (await sql`
    SELECT slug
    FROM named_corals
    WHERE active = true
  `) as unknown as { slug: string }[];
  return rows;
}

// Evergreen-end-state, now landed: sitemap-scoped slug set = every active coral
// that has EVER had a vendor listing (monotonic — once listed, always indexable),
// NOT the full active seed list getAllNamedCoralSlugs returns. The prior in-window
// gate flagged this as a TODO ("once scope b/c land the page stops being thin for
// never-listed corals"); CTK-185(a)'s lore render + the price-history/guides
// surfaces are that content, so an ever-listed coral page is non-thin even when
// currently OOS — it carries the lore beat PLUS a real availability/price ladder
// (current or historical). Indexable regardless of recency. Dropping the in-window
// clause makes the gate monotonic: a coral can no longer flicker in and out of the
// sitemap as its listings age past the window (the soft-404 churn the window
// gate's coupling fought is gone with the window).
//
// Never-listed seed corals (lore-only, no listing ever) are the genuinely-thin
// case. Those are handled by PAGE-level noindex (generateMetadata reads
// has_ever_listed → coralPageRobots), NOT by sitemap omission alone — sitemap
// presence and robots indexability are the SAME has_ever_listed predicate read
// from two surfaces (getNamedCoralBySlug carries the IDENTICAL EXISTS clause).
// Keep them in lockstep or sitemap/robots desync. Excluding thin pages here
// still avoids the soft-404 signal to Google (CTK-162 scope d, PR #21
// /code-review F1).
//
// Sentinel guards mirror the /corals index lateral: nc.slug + v.slug NOT LIKE
// '!_%' ESCAPE '!' ('!' escape char — backslash collapses in JS template
// cooking). Sentinel-vendor exclusion in the EXISTS means a coral whose only
// listings belong to a sentinel vendor is correctly not-ever-listed. NO v.active
// guard (see getNamedCoralBySlug's EXISTS comment): retired-vendor-only corals
// keep real historical content via getCoralAvailability, so they stay indexable.
export async function getIndexableCoralSlugs(): Promise<{ slug: string }[]> {
  const sql = getNeonSql();
  const rows = (await sql`
    SELECT nc.slug
    FROM named_corals nc
    WHERE nc.active = true
      AND nc.slug NOT LIKE '!_%' ESCAPE '!'
      AND EXISTS (
        SELECT 1
        FROM vendor_listings vl
        JOIN vendors v ON v.id = vl.vendor_id
        WHERE vl.named_coral_id = nc.id
          AND v.slug NOT LIKE '!_%' ESCAPE '!'
      )
  `) as unknown as { slug: string }[];
  return rows;
}

// Sitemap-scoped slug set for the price-history CHILD route
// (/coral/[slug]/price-history). A coral qualifies iff its price-history page
// renders a real chart, not the thin "not enough history yet" state — i.e.
// get_coral_price_envelope(id, 90) returns >= 2 rows (>= 2 distinct days with an
// in-stock priced floor). That is the EXACT inverse of the frontend
// isThinHistory check (envelope <= 1 day AND no vendor >= 2 points): the
// envelope carries a row for every day any vendor is in-stock-priced, so <= 1
// envelope day means no vendor can have 2 points either. Reusing the same SQL
// function the chart consumes means this gate can't drift from the render.
//
// Listing thin pages would be a soft-404 signal to Google — same exclusion
// rationale as getIndexableCoralSlugs (PR #21 /code-review F1), but the predicate
// is history-DEPTH, not current-stock: a coral with rich history that is OOS
// today still renders a real historical trend, so it stays IN the price-history
// sitemap (and the parent-page back-link prevents the SEO orphan if its parent
// were ever absent from getIndexableCoralSlugs).
export async function getPriceHistorySitemapSlugs(): Promise<{ slug: string }[]> {
  const sql = getNeonSql();
  const rows = (await sql`
    SELECT nc.slug
    FROM named_corals nc
    WHERE nc.active = true
      AND (SELECT count(*) FROM get_coral_price_envelope(nc.id, 90)) >= 2
    ORDER BY nc.slug
  `) as unknown as { slug: string }[];
  return rows;
}

// Powers /corals index page. Flat alphabetical by canonical_name
// (vendor-neutrality, mirrors getAllActiveVendors). Dormancy gate: only corals
// with at-least-one in-window listing render — a row must never route to an
// empty /coral/[slug]. The window derives from the imported CORAL_RECENCY_DAYS —
// the same constant that gates the getCoralAvailability populated branch, so
// constant-level window drift is closed. The gate carries in_stock = true per
// the **Default-render parity** rule (branding-guide §"State markers") — parity
// is measured against the destination's DEFAULT (bare-URL) render, not the
// toggled-on view: a coral whose only in-window listing is OOS drops off the
// index until it restocks. Parity holds at query time, not continuously: /corals
// is genuinely ISR, so its page cache STACKS on this data cache — an index row
// lags the DB by up to ~two 300s windows while the destination (fully dynamic,
// data cache only) lags at most ~one. Accepted: equal cadence is the floor, not
// atomicity. Deliberate divergence from the /vendors index's 600: vendor rows
// aren't stock-gated, so no skew class exists there.
// The VENDOR-side lateral guards (active + sentinel-slug; ESCAPE '!' — backslash
// collapses in JS template cooking and would invert the filter) are deliberately
// STRICTER than the destination: getCoralAvailability carries no vendor filter,
// so a coral whose only in-window listings belong to a deactivated or sentinel
// vendor stays off the index by design rather than advertising retired
// inventory. That destination-side asymmetry (the detail page would still render
// such rows) is owned by the vendor-guard sibling. Reciprocal coupling note (core
// triple + both deliberate asymmetries) at getCoralAvailability's header — edit
// the lateral's predicate → check there, and vice versa. Window evaluates at
// query time inside the cached fn; drift ≤ 5 min on a 7-day window.
// Single inner JOIN LATERAL: the lateral is BOTH the dormancy gate (zero
// qualifying rows → no lateral row → the inner join drops the coral) and the
// thumbnail pick. The prefer-image sort `(vl.image_url IS NOT NULL) DESC` floats
// image-bearing rows first, so a coral whose in-window rows all lack images
// still lists, image_url null (page renders the bare bg-wash box). vl.id DESC
// tiebreak: first_seen_at is DB DEFAULT now(), transaction-stable across a
// scrape run's single-transaction batch insert, so same-coral ties are routine —
// without the pin the LIMIT 1 pick (and the thumbnail) flaps across
// revalidations.
// Bump the key prefix when the cached row shape widens — Data Cache persists
// across deploys, and stale-shape entries deserialize new fields as undefined
// for up to the revalidate window. A cadence-only retune takes no bump.
// Single source for the /corals index data-cache cadence. The page-side `export
// const revalidate` (app/corals/page.tsx) MUST stay a literal (Next statically
// analyzes segment config), so the tandem can't be import-coupled there;
// scripts/coral-predicate-coupling.test.ts pins the page literal to this value
// instead.
export const CORALS_INDEX_REVALIDATE_S = 300;

interface CoralIndexRow {
  slug: string;
  canonical_name: string;
  coral_type: string | null;
  origin_vendor: string | null;
  image_url: string | null;
}

export async function getAllNamedCoralsWithListings(): Promise<
  CoralIndexRow[]
> {
  return unstable_cache(
    async () => {
      const sql = getNeonSql();
      const windowStart = new Date(
        Date.now() - CORAL_RECENCY_DAYS * MS_PER_DAY,
      ).toISOString();
      const rows = (await sql`
        SELECT nc.slug, nc.canonical_name, nc.coral_type, nc.origin_vendor,
               img.image_url
        FROM named_corals nc
        JOIN LATERAL (
          -- Prefer-image sort: image-bearing rows float first, so image_url
          -- is null only when NO in-window in-stock row has an image — the
          -- inner join still keeps the coral (dormancy gate is row existence,
          -- not image existence).
          SELECT vl.image_url
          FROM vendor_listings vl
          JOIN vendors v ON v.id = vl.vendor_id
          WHERE vl.named_coral_id = nc.id
            AND vl.last_seen_at > ${windowStart}
            AND vl.in_stock = true
            AND vl.is_auction = false
            AND v.active = true
            AND v.slug NOT LIKE '!_%' ESCAPE '!'
          ORDER BY (vl.image_url IS NOT NULL) DESC, vl.first_seen_at DESC, vl.id DESC
          LIMIT 1
        ) img ON true
        WHERE nc.active = true
          AND nc.slug NOT LIKE '!_%' ESCAPE '!'
        ORDER BY nc.canonical_name ASC
      `) as unknown as CoralIndexRow[];
      return rows;
    },
    // V5 (CTK-042): the image-lateral set narrows (auction rows gated via
    // is_auction = false). Same lockstep rationale as getVendorInventoryV6 —
    // the Data Cache persists across deploys, so bump forces a clean re-query
    // rather than serving an auction-sourced thumbnail until revalidate.
    ['getAllNamedCoralsWithListingsV5'],
    // Tandem with the /corals page const, matching the /coral/[slug] destination
    // cadence (skew note at the header).
    { revalidate: CORALS_INDEX_REVALIDATE_S, tags: ['corals-index'] },
  )();
}

// NO recency cap — deliberately ignores the 7-day in-window predicate that gates
// the populated branch, so the empty-branch eyebrow can name the historical
// last-seen across all prior listings of this coral. The freshness substrate is
// vendor_listings.last_seen_at; named_corals has no last_seen_at column. Returns
// null when zero historical rows exist (seed-list entry never surfaced a vendor
// listing); the page renders bare `NOT LISTED` then.
export async function getCoralLastSeenAt(
  namedCoralId: number,
): Promise<string | null> {
  return unstable_cache(
    async () => {
      const sql = getNeonSql();
      const rows = (await sql`
        SELECT MAX(last_seen_at) AS last_seen_at
        FROM vendor_listings
        WHERE named_coral_id = ${namedCoralId}
      `) as unknown as { last_seen_at: string | null }[];

      return rows[0]?.last_seen_at ?? null;
    },
    ['getCoralLastSeenAt', String(namedCoralId)],
    { revalidate: 1800, tags: [`named-coral-${namedCoralId}-last-seen`] },
  )();
}

// Lifetime first-seen anchor for the /guides market line "First seen." field —
// the EARLIEST first_seen_at across every listing of this coral, LIFETIME (no
// recency cap, like getCoralLastSeenAt). The price-history first-seen anchor
// (diff.py:419 writes a price_history row on the "new" decision at the listing's
// first_seen_at), surfaced here off vendor_listings.first_seen_at rather than a
// raw price_history scan — same substrate getCoralLastSeenAt rides. Returns null
// when no listing has ever surfaced (seed-list entry, no vendor row). NOT
// windowed: range + vendor count are windowed, first-seen is lifetime.
export async function getCoralFirstSeenAt(
  namedCoralId: number,
): Promise<string | null> {
  return unstable_cache(
    async () => {
      const sql = getNeonSql();
      const rows = (await sql`
        SELECT MIN(first_seen_at) AS first_seen_at
        FROM vendor_listings
        WHERE named_coral_id = ${namedCoralId}
      `) as unknown as { first_seen_at: string | null }[];

      return rows[0]?.first_seen_at ?? null;
    },
    ['getCoralFirstSeenAt', String(namedCoralId)],
    { revalidate: 1800, tags: [`named-coral-${namedCoralId}-first-seen`] },
  )();
}
