// /about — static brand surface per site.md §4.7.
//
// First product-side surface using the "Jon" literal per branding-guide.md
// line 97 personal-voice scope. Static page — no revalidate, no Suspense, no
// data fetching. Vendor full names per branding-guide.md line 119 (no "WWC"
// or "PEA" shorthand in product-voice copy). Copy verbatim from
// /brand-manager Session 7 pre-session sweep.
//
// Metadata vocabulary per site.md §6.1 / architecture-v1.md §6.1.
//
// CTK-136 round-3-final price-methodology disclosure (Surface 2): the "One more
// thing, on prices…" paragraph wired below per the directive lock 2026-06-10
// (copy/round-3/price-methodology-final.md). Static <p>, no data.

import type { Metadata } from 'next';
import { SocialLinks } from './_components/social-links';
import { PageShell } from '@/components/ui/page-shell';
import { PageH1 } from '@/components/ui/page-h1';

// Metadata wording verbatim from site.md §6.1 line 1709. Voice rule per
// site.md §6.1 line 1717: no "Jon" at metadata altitude — product-voice
// register across all surfaces' meta. Personal-voice work lives at the
// page body below, not at the SERP card.
export const metadata: Metadata = {
  title: 'About', // suffix via root title.template
  description: 'Who runs CoralTicker, why, and what it is.',
  alternates: { canonical: '/about' },
  openGraph: { url: '/about', siteName: 'CoralTicker', type: 'website', locale: 'en_US' },
  twitter: { card: 'summary' },
};

export default function About() {
  return (
    <PageShell as="section">
      <PageH1 className="mb-8">
        About CoralTicker.
      </PageH1>
      <div className="text-base leading-relaxed space-y-4">
        <p>
          CoralTicker watches a handful of reef coral vendors and surfaces every new
          listing in one feed. If you&apos;re the kind of reefer who refreshes World
          Wide Corals and Top Shelf Aquatics waiting for a drop, this exists so
          you don&apos;t have to.
        </p>
        <p>
          I&apos;m Jon. Reefer. Data engineer. I built CoralTicker because I kept
          missing listings. It&apos;s a personal project, not a startup. No team,
          no investors, no roadmap pressure. I add vendors when there&apos;s signal
          they&apos;re worth tracking. I ship features that fix something I&apos;d
          actually use.
        </p>
        <p>
          CoralTicker doesn&apos;t sell coral. The links go to the vendor&apos;s own
          site — that&apos;s where the listing lives.
        </p>
        <p>
          One more thing, on prices. A crossed-out &quot;before&quot; here is one of
          two things: a price I recorded earlier while tracking the vendor, or the
          vendor&apos;s own regular price, shown as I found it. The two don&apos;t
          always line up — so where I&apos;ve tracked a listing myself, that&apos;s
          the number I show. It&apos;s just what I&apos;ve recorded — and a new
          listing won&apos;t have much of a history with me yet.
        </p>
        <p>
          If you&apos;ve got feedback, an alert idea, or a vendor I should add,
          here&apos;s where to reach me.
        </p>
        <SocialLinks />
      </div>
    </PageShell>
  );
}
