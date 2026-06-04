import { unstable_cache } from 'next/cache';
import { getNeonSql } from '@/lib/db/neon';
import { CORAL_RECENCY_DAYS, MS_PER_DAY } from '@/lib/queries/listings';

// description stays on NamedCoral with a null-coerce at the cast site —
// hosted named_corals lacks the column; the description-<p> branch on
// /coral/[slug] always skips. year_introduced removed entirely per CTK-092 /
// Q-040-11 hold-position path-a (Tier 4 trigger-gated revisit CTK absorbs
// schema-add when seed-data populability + year-shape ratify).
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

export async function getNamedCoralBySlug(slug: string): Promise<NamedCoral | null> {
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
}

export async function getAllNamedCoralSlugs(): Promise<{ slug: string }[]> {
  const sql = getNeonSql();
  const rows = (await sql`
    SELECT slug
    FROM named_corals
    WHERE active = true
  `) as unknown as { slug: string }[];
  return rows;
}

// CTK-057: powers /corals index page. Flat alphabetical by canonical_name
// (vendor-neutrality precedent, mirrors getAllActiveVendors). Dormancy gate:
// only corals with at-least-one in-window listing render — a row must never
// route to an empty /coral/[slug]. The window derives from the imported
// CORAL_RECENCY_DAYS (lib/queries/listings.ts) — the same constant that gates
// the getCoralAvailability populated branch, so listing-side window drift is
// impossible. Deliberately NO in_stock filter — getCoralAvailability renders
// OOS rows (inventory-recon surface), so the listing-side window is parity.
// The VENDOR-side EXISTS guards (active + sentinel-slug, CTK-095 Axis 3
// belt-and-suspenders; ESCAPE '!' — backslash collapses in JS template cooking
// and would invert the filter) are deliberately STRICTER than the destination:
// getCoralAvailability carries no vendor filter, so a coral whose only
// in-window listings belong to a deactivated or sentinel vendor stays off the
// index by design rather than advertising retired inventory. That
// destination-side asymmetry (the detail page would still render such rows)
// is tracked at /reef-lead intake (CTK pending as of 2026-06-04; cite the
// number here once assigned). Window evaluates at query time inside the
// cached fn; drift ≤ 10 min on a 7-day window per getVendorInventory
// precedent.
export async function getAllNamedCoralsWithListings(): Promise<
  { slug: string; canonical_name: string }[]
> {
  return unstable_cache(
    async () => {
      const sql = getNeonSql();
      const windowStart = new Date(
        Date.now() - CORAL_RECENCY_DAYS * MS_PER_DAY,
      ).toISOString();
      const rows = (await sql`
        SELECT nc.slug, nc.canonical_name
        FROM named_corals nc
        WHERE nc.active = true
          AND nc.slug NOT LIKE '!_%' ESCAPE '!'
          AND EXISTS (
            SELECT 1
            FROM vendor_listings vl
            JOIN vendors v ON v.id = vl.vendor_id
            WHERE vl.named_coral_id = nc.id
              AND vl.last_seen_at > ${windowStart}
              AND v.active = true
              AND v.slug NOT LIKE '!_%' ESCAPE '!'
          )
        ORDER BY nc.canonical_name ASC
      `) as unknown as { slug: string; canonical_name: string }[];
      return rows;
    },
    ['getAllNamedCoralsWithListings'],
    { revalidate: 600, tags: ['corals-index'] },
  )();
}

// NO recency cap — deliberately ignores the 7-day in-window predicate that
// gates the populated branch, so the empty-branch eyebrow can name the
// historical last-seen across all prior listings of this coral. The freshness
// substrate is vendor_listings.last_seen_at; named_corals has no last_seen_at
// column. Returns null when zero historical rows exist (seed-list entry never
// surfaced a vendor listing); the page renders bare `NOT LISTED` then.
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
