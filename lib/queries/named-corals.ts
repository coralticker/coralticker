// lib/queries/named-corals.ts
//
// Slug-based lookups against named_corals per architecture-v1.md §1.7 +
// decision #47 (slug immutable post-insert). Consumed by /coral/[slug]
// (per site.md §4.1) and provides the generateStaticParams source.
//
// Migrated CTK-043 cut-4 (2026-05-16) from supabase-js PostgREST builders to
// raw SQL via @neondatabase/serverless. Public NamedCoral shape preserved.

import { getNeonSql } from '@/lib/db/neon';

// Public contract: year_introduced + description stay on NamedCoral so
// downstream view + formatter consumers don't shift. Hold-position per
// Q-040-11 pattern — SELECT clause omits BOTH columns (hosted named_corals
// lacks them per session probe 2026-05-14; spec at architecture-v1.md §1.7
// + site.md §3.5.1 diverges from hosted reality), and we coerce to null at
// the cast site below. Restore the SELECT projection + drop the coerces when
// Q-040-12 broader hosted-vs-spec audit lands at /lead-architect
// post-CTK-040 close. Production impact: /coral/[slug] description-<p>
// branch + lineage-Year field always skip (null).
export interface NamedCoral {
  id: number;
  slug: string;
  canonical_name: string;
  coral_type: string | null;
  origin_vendor: string | null;
  year_introduced: number | null;
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
  return { ...row, year_introduced: null, description: null };
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
