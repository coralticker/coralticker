// lib/queries/vendors.ts
//
// Slug-based lookups against vendors per architecture-v1.md §1.3. Consumed
// by /vendor/[slug] (per site.md §4.5) and provides the generateStaticParams
// source. Retired vendors (active=false) preserved in the row store per
// arch-v1 §1.3 but excluded from generateStaticParams by default.
//
// Migrated CTK-043 cut-4 (2026-05-16) from supabase-js PostgREST builders to
// raw SQL via @neondatabase/serverless.
//
// Slug-shape seam (CTK-044, 2026-05-17): public URLs are kebab-case
// (site.md §7.3); DB stores snake_case identifiers (scraper-config + R2
// path convention). This module is the only normalization layer — kebab→snake
// on read, snake→kebab on emit. DB / scrapers / R2 paths stay snake.
//
// unstable_cache wrap (CTK-046 ISR-regression fold, 2026-05-18): the
// /vendor/[slug] route flipped to pure-dynamic at runtime when searchParams
// was added (Cache-Control: private, no-cache, no-store on Jon-localhost
// probe). Wrapping query helpers in unstable_cache restores ISR semantics
// per site.md §4.5 + §1.2 (revalidate = 600 / 10 min). Tags allow targeted
// revalidateTag invalidation downstream (no consumers yet at v1).

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

export async function getAllActiveVendorSlugs(): Promise<{ slug: string }[]> {
  const sql = getNeonSql();
  const rows = (await sql`
    SELECT slug
    FROM vendors
    WHERE active = true
  `) as unknown as { slug: string }[];
  return rows.map((row) => ({ slug: row.slug.replaceAll('_', '-') }));
}
