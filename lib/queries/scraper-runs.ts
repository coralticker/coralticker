// lib/queries/scraper-runs.ts
//
// Footer freshness signal per CTK-049 Session 1 — most recent successful
// scrape completion across all vendors. Consumed by components/footer.tsx
// to render `Last scrape: {relative-time}` per branding-guide.md L283
// relative-time canon (binds every surface including footer freshness).
//
// Column choice: `finished_at` (Phase A end-time per CTK-024 design) over
// `phase_b_finished_at` (Phase B image-mirror end-time per CTK-038). Phase
// A persist-completion is the user-facing "data is this fresh" signal;
// Phase B image-mirror is cosmetic (R2 rehost) and may legitimately hard-
// cancel at the 60-min workflow timeout without invalidating the listing
// data. Footer reads "data fresh as of N hours ago," not "all images
// mirrored as of N hours ago." Status='success' filter excludes failed /
// partial runs from the freshness clock.
//
// unstable_cache wrap for ISR semantics: footer renders on every view, so
// the query must not block per-request. 5-min revalidate aligns with
// site.md §1.2 freshness target. Tag allows targeted invalidation
// downstream if a scrape-completion webhook ever wires in (no consumer
// at v1).

import { unstable_cache } from 'next/cache';
import { getNeonSql } from '@/lib/db/neon';

export async function getLastScrapeAt(): Promise<string | null> {
  return unstable_cache(
    async () => {
      const sql = getNeonSql();
      const rows = (await sql`
        SELECT MAX(finished_at) AS last_scrape_at
        FROM scraper_runs
        WHERE status = 'success'
          AND finished_at IS NOT NULL
      `) as unknown as { last_scrape_at: string | null }[];

      return rows[0]?.last_scrape_at ?? null;
    },
    ['getLastScrapeAt'],
    { revalidate: 300, tags: ['scraper-runs'] },
  )();
}
