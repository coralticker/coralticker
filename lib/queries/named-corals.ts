import { unstable_cache } from 'next/cache';
import { getNeonSql } from '@/lib/db/neon';

// year_introduced + description stay on NamedCoral so downstream view +
// formatter consumers don't shift, but the SELECT clause omits both columns:
// hosted named_corals lacks them (the spec at architecture-v1.md §1.7 + site.md
// §3.5.1 diverges from hosted reality). Coerced to null at the cast site below
// pending the broader hosted-vs-spec audit. Production impact: /coral/[slug]
// description-<p> branch + lineage-Year field always skip (null).
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
