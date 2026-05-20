// §3.5.4 <Footer> — every view, including Phase 4 auth-gated views
// Per branding-guide.md §"Surface boundary" + §"Wordmark + tagline lockup" footer rule:
//   - Wordmark + disclaimer line is the entire footer composition
//   - No tagline in footer (lives at hero only on hero surfaces)
//   - No "Built by Jon" on product-voice surfaces (lives on /about + R2R + Discord intros)
//   - Plex Mono lowercase / sentence case in inkFaint for the disclaimer line
//     (branding-guide.md §"Mono uppercase register" footer-chrome carve-out)
//
// CTK-049 S1: mid-dot extracted to its own forest-colored span (matches
// app/vendor/[slug]/_components/pagination-nav.tsx:100 pattern per
// branding-guide.md L211 forest-mid-dot separator canon — footer was the
// drift). lastScrape binds to scraper_runs.finished_at MAX via
// lib/queries/scraper-runs.ts; renders as relative-time per L283 canon.
// Em-dash fallback only when no successful scrape exists in DB.

import { Wordmark } from '@/components/ui/wordmark';
import { getLastScrapeAt } from '@/lib/queries/scraper-runs';
import { formatRelativeTime } from '@/lib/format/relative-time';

export async function Footer() {
  const lastScrapeAt = await getLastScrapeAt();
  const lastScrape = lastScrapeAt
    ? formatRelativeTime(lastScrapeAt, new Date())
    : '—';

  return (
    <footer className="px-6 py-6 mt-12 text-sm">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <Wordmark variant="nav" />
        <span className="font-mono text-ink/60">
          Not affiliated with vendors.
          <span aria-hidden="true" className="text-forest">{' · '}</span>
          Last scrape: {lastScrape}
        </span>
      </div>
    </footer>
  );
}
