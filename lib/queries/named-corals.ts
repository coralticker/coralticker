import { cache } from 'react';
import { unstable_cache } from 'next/cache';
import { getNeonSql } from '@/lib/db/neon';
import { CORAL_RECENCY_DAYS, MS_PER_DAY } from '@/lib/queries/listings';

// description stays on NamedCoral with a null-coerce at the cast site — hosted
// named_corals lacks the column; the description-<p> branch on /coral/[slug]
// always skips.
export interface NamedCoral {
  id: number;
  slug: string;
  canonical_name: string;
  coral_type: string | null;
  origin_vendor: string | null;
  description: string | null;
  source_urls: string[] | null;
  requires_vendor_prefix: boolean;
  active: boolean;
}

interface NamedCoralRow {
  id: number;
  slug: string;
  canonical_name: string;
  coral_type: string | null;
  origin_vendor: string | null;
  source_urls: string[] | null;
  requires_vendor_prefix: boolean;
  active: boolean;
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
        origin_vendor,
        source_urls,
        requires_vendor_prefix,
        active
      FROM named_corals
      WHERE slug = ${slug}
        AND active = true
      LIMIT 1
    `) as unknown as NamedCoralRow[];

    const row = rows[0];
    if (!row) return null;
    return { ...row, description: null };
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
