// CTK-214 — the light "now tracking" onboarding strip for /new. One em-dash row
// per freshly-onboarded vendor, hairline + whitespace separation from the feed
// controls below. NO boxed banner / card / badge / icon (INV-02 close): the
// separation IS the honest framing in the layout. Reuses the data-row em-dash
// chrome (forest separator) + the existing underline browse-link affordance
// (app/_components/recent-drops-strip.tsx "view full feed →").
//
// HONEST FRAMING: {N} is the browseable in-stock catalog size (get_onboarding_
// strip_state) — explicitly NOT "new arrivals," and a SEPARATE query from the
// page eyebrow's N ARRIVALS (getRecentArrivals), so the catalog count can't leak
// into the arrivals count. Copy is canon (branding-guide §"now tracking" — the
// `/new` strip form: "Now tracking {Vendor} — {N} pieces. Browse →").
//
// Renders independently of the arrivals feed: it must show even when the feed is
// empty (arrivals.length === 0), and returns null cleanly when no vendor is on
// the strip. The Browse link lands on /vendor/[slug] — the page whose in-stock
// catalog equals the {N} shown (number seen == number you get).

import Link from 'next/link';
import { getOnboardingStrip } from '@/lib/queries/onboarding';

export async function OnboardingStrip() {
  const vendors = await getOnboardingStrip();
  if (vendors.length === 0) return null;

  return (
    <section aria-label="Newly tracked vendors" className="mb-8 pb-6 border-b border-line">
      <ul className="space-y-2">
        {vendors.map((v) => (
          <li key={v.vendorSlug} className="text-sm text-ink">
            Now tracking {v.displayName}
            <span aria-hidden="true" className="text-forest"> — </span>
            {v.n} pieces.{' '}
            <Link
              href={`/vendor/${v.vendorSlug}`}
              className="text-ink underline underline-offset-2 hover:no-underline"
            >
              Browse →
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
