// Em-dash fallback only when no successful scrape exists in DB.
//
// Disclaimer is prose-register: period after "vendors." terminates
// segment-1; single space (not forest mid-dot) to the freshness phrase.
// Forest mid-dot is reserved for telegraphic chrome (eyebrows / pagination
// / sort-filter per §"Mono uppercase register") where facts are not
// period-terminated; period + mid-dot reads as a double-terminator.
//
// At <640px the two disclaimer segments break to separate rows; forcing the
// break at the sentence boundary (segment-1's period) is cleaner than
// letting the wrap land mid-fragment. <br className="sm:hidden" /> renders
// as a line break at <640px and display:none at ≥640px.

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
        <small className="font-mono text-sm">
          Not affiliated with vendors.<br className="sm:hidden" /> Last checked: {lastScrape}
        </small>
      </div>
    </footer>
  );
}
