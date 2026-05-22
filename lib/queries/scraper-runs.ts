// getLastScrapeAt is consumed by components/footer.tsx to render the footer
// freshness signal — function name doesn't telegraph the footer-render use
// case, so naming the consumer here saves a grep at 11pm.
//
// Column choice rationale: `finished_at` (Phase A persist end-time) is the
// user-facing "data is this fresh" signal. `phase_b_finished_at` (Phase B
// image-mirror end-time) is cosmetic (R2 rehost) and may hard-cancel at the
// 60-min workflow timeout without invalidating the listing data. The freshness
// clock reads "data fresh as of N hours ago," not "all images mirrored."
// status='success' filter excludes failed / partial runs from the clock.

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

export async function getLatestScrapeFinishedAt(
  vendorId: number,
): Promise<string | null> {
  return unstable_cache(
    async () => {
      const sql = getNeonSql();
      const rows = (await sql`
        SELECT MAX(finished_at) AS latest_finished_at
        FROM scraper_runs
        WHERE vendor_id = ${vendorId}
          AND status = 'success'
          AND finished_at IS NOT NULL
      `) as unknown as { latest_finished_at: string | null }[];

      return rows[0]?.latest_finished_at ?? null;
    },
    ['getLatestScrapeFinishedAt', String(vendorId)],
    { revalidate: 600, tags: [`scraper-runs-vendor-${vendorId}`] },
  )();
}
