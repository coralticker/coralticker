// Slug-based lookups against vendors. Consumed by /vendor/[slug] and provides
// the generateStaticParams source. Retired vendors (active=false) preserved in
// the row store but excluded from generateStaticParams by default.
//
// Slug-shape seam: public URLs are kebab-case; DB stores snake_case identifiers
// (scraper-config + R2 path convention). This module is the only normalization
// layer — kebab→snake on read, snake→kebab on emit. DB / scrapers / R2 paths
// stay snake.
//
// The /vendor/[slug] route flips to pure-dynamic at runtime when searchParams is
// read; wrapping query helpers in unstable_cache restores ISR semantics. Tags
// allow targeted revalidateTag invalidation downstream.

import { unstable_cache } from 'next/cache';
import { getNeonSql } from '@/lib/db/neon';

export interface Vendor {
  id: number;
  slug: string;
  display_name: string;
  base_url: string;
  platform: string;
  scrape_method: string | null;
  cadence_label: string | null;
  image_strategy: string | null;
  active: boolean;
}

export async function getVendorBySlug(slug: string): Promise<Vendor | null> {
  return unstable_cache(
    async () => {
      const sql = getNeonSql();
      const dbSlug = slug.replaceAll('-', '_');
      const rows = (await sql`
        SELECT
          id,
          slug,
          display_name,
          base_url,
          platform,
          scrape_method,
          cadence_label,
          image_strategy,
          active
        FROM vendors
        WHERE slug = ${dbSlug}
        LIMIT 1
      `) as unknown as Vendor[];

      return rows[0] ?? null;
    },
    ['getVendorBySlug', slug],
    { revalidate: 600, tags: [`vendor-${slug}`] },
  )();
}

// Raw snake-slug → display_name map for active vendors. The price-history chart
// end-labels resolve a vendor shorthand from the branding-guide canon table, but
// the four canon FULL-NAME vendors (and any un-canon vendor) fall through to the
// display_name — which get_coral_price_history doesn't project (it returns
// vendor_slug only). Keyed by the DB snake slug (NOT kebab-normalized) so it
// joins directly to the function's vendor_slug. Active-only is sufficient: a
// retired vendor's historical track still resolves via the canon shorthand map
// for the seven wired vendors; an un-canon retired vendor would miss, an
// accepted edge until /brand-manager extends the canon.
export async function getVendorDisplayNamesBySlug(): Promise<Record<string, string>> {
  return unstable_cache(
    async () => {
      const sql = getNeonSql();
      const rows = (await sql`
        SELECT slug, display_name
        FROM vendors
        WHERE active = true
      `) as unknown as { slug: string; display_name: string }[];
      const map: Record<string, string> = {};
      for (const row of rows) map[row.slug] = row.display_name;
      return map;
    },
    ['getVendorDisplayNamesBySlug'],
    { revalidate: 600, tags: ['vendors-index'] },
  )();
}

export async function getAllActiveVendorSlugs(): Promise<{ slug: string }[]> {
  const sql = getNeonSql();
  // `_..._test` sentinel-slug convention for test rows. Filter keeps the test
  // rows out of generateStaticParams even if `active=true` slips via a row-level
  // discipline lapse — defensive over the discipline invariant. ESCAPE char `!`
  // (not the SQL default `\`) so the LIKE pattern survives JS template-literal
  // cooking — backslash escapes collapse and would silently invert the filter to
  // "match everything".
  const rows = (await sql`
    SELECT slug
    FROM vendors
    WHERE active = true AND slug NOT LIKE '!_%' ESCAPE '!'
  `) as unknown as { slug: string }[];
  return rows.map((row) => ({ slug: row.slug.replaceAll('_', '-') }));
}

// Powers /vendors index page. Alphabetical by display_name for vendor-neutrality
// (no curated tier sort). Slug normalized snake → kebab on emit per module seam.
export async function getAllActiveVendors(): Promise<
  { slug: string; display_name: string; base_url: string }[]
> {
  return unstable_cache(
    async () => {
      const sql = getNeonSql();
      // Same sentinel-slug filter as getAllActiveVendorSlugs above; keeps test
      // rows off /vendors index.
      const rows = (await sql`
        SELECT slug, display_name, base_url
        FROM vendors
        WHERE active = true AND slug NOT LIKE '!_%' ESCAPE '!'
        ORDER BY display_name ASC
      `) as unknown as { slug: string; display_name: string; base_url: string }[];
      return rows.map((row) => ({
        slug: row.slug.replaceAll('_', '-'),
        display_name: row.display_name,
        base_url: row.base_url,
      }));
    },
    ['getAllActiveVendors'],
    { revalidate: 600, tags: ['vendors-index'] },
  )();
}
