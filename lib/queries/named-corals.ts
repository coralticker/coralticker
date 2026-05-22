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

// CTK-070: empty-branch freshness for /coral/[slug] empty eyebrow
// `NOT LISTED · LAST SEEN X AGO` per site.md §4.1 step 1 + Decision Q. NO
// recency cap — deliberately ignores the 7-day in-window predicate that
// determined emptiness, so the eyebrow can name the historical last-seen
// across all prior listings of this coral. The freshness substrate is
// vendor_listings.last_seen_at (named_corals has no last_seen_at column).
// Returns null when zero historical rows exist (seed-list entry never
// surfaced a vendor listing); page-side renders bare `NOT LISTED` with no
// `· LAST SEEN X AGO` chunk per the L216 canon empty-branch rule.
export async function getCoralLastSeenAt(
  namedCoralId: number,
): Promise<string | null> {
  const sql = getNeonSql();
  const rows = (await sql`
    SELECT MAX(last_seen_at) AS last_seen_at
    FROM vendor_listings
    WHERE named_coral_id = ${namedCoralId}
  `) as unknown as { last_seen_at: string | null }[];

  return rows[0]?.last_seen_at ?? null;
}
