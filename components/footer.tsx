// §3.5.4 <Footer> — every view, including Phase 4 auth-gated views
// Per branding-guide.md §"Surface boundary" + §"Wordmark + tagline lockup" footer rule:
//   - Wordmark + disclaimer line is the entire footer composition
//   - No tagline in footer (lives at hero only on hero surfaces)
//   - No "Built by Jon" on product-voice surfaces (lives on /about + R2R + Discord intros)
//   - Plex Mono lowercase / sentence case in inkFaint for the disclaimer line
//     (branding-guide.md §"Mono uppercase register" footer-chrome carve-out)
//
// CTK-049 S1: lastScrape binds to scraper_runs.finished_at MAX via
// lib/queries/scraper-runs.ts; renders as relative-time per L283 canon.
// Em-dash fallback only when no successful scrape exists in DB.
//
// CTK-049 S1c: round-2 polish per /brand-manager amendments at
// branding-guide.md L326. (1) Disclaimer is prose-register: period after
// "vendors." terminates segment-1; single space (not forest mid-dot) to
// the freshness phrase. Forest mid-dot is reserved for telegraphic chrome
// (eyebrows / pagination / sort-filter per §"Mono uppercase register"
// L211) where facts are not period-terminated; period + mid-dot reads as
// double-terminator. (2) Wordmark one typographic step larger than
// disclaimer (text-base over text-sm) — restores brand-anchor primacy
// against Plex Mono optical-size bias that otherwise lets the long
// disclaimer dominate. items-baseline on the flex row aligns wordmark
// baseline to disclaimer baseline across the size step.
//
// CTK-049 S1d: round-3 mobile-degradation amendment per branding-guide.md
// L326. At <640px the two disclaimer segments break to separate rows
// (wordmark row 1 / "Not affiliated with vendors." row 2 / "Last scrape:
// {timestamp}" row 3). The freshness phrase earns its own beat at mobile
// widths where the prose wraps anyway; forcing the break at the sentence
// boundary (segment-1's period) is cleaner than letting the wrap land
// mid-fragment. Implementation: <br className="sm:hidden" /> renders as a
// line break at <640px and display:none at ≥640px. Desktop single-line
// composition unchanged.

import { Wordmark } from '@/components/ui/wordmark';
import { getLastScrapeAt } from '@/lib/queries/scraper-runs';
import { formatRelativeTime } from '@/lib/format/relative-time';

export async function Footer() {
  const lastScrapeAt = await getLastScrapeAt();
  const lastScrape = lastScrapeAt
    ? formatRelativeTime(lastScrapeAt, new Date())
    : '—';

  return (
    <footer className="px-6 py-6 mt-12">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="text-base">
          <Wordmark variant="nav" />
        </span>
        <span className="font-mono text-sm text-ink/60">
          Not affiliated with vendors.<br className="sm:hidden" /> Last scrape: {lastScrape}
        </span>
      </div>
    </footer>
  );
}
