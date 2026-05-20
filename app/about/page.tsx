// /about — static brand surface per site.md §4.7.
//
// First product-side surface using the "Jon" literal per branding-guide.md
// line 97 personal-voice scope. Static page — no revalidate, no Suspense, no
// data fetching. Vendor full names per branding-guide.md line 119 (no "WWC"
// or "PEA" shorthand in product-voice copy). Copy verbatim from
// /brand-manager Session 7 pre-session sweep.
//
// Metadata vocabulary per site.md §6.1 / architecture-v1.md §6.1.

import type { Metadata } from 'next';
import { SocialLinks } from './_components/social-links';

// Metadata wording verbatim from site.md §6.1 line 1709. Voice rule per
// site.md §6.1 line 1717: no "Jon" at metadata altitude — product-voice
// register across all surfaces' meta. Personal-voice work lives at the
// page body below, not at the SERP card.
export const metadata: Metadata = {
  title: 'About — CoralTicker',
  description: 'Who runs CoralTicker, why, and what it is.',
};

export default function About() {
  return (
    <main className="px-6 py-12 max-w-3xl mx-auto">
      <h1 className="text-3xl md:text-4xl font-bold mb-8">
        About CoralTicker.
      </h1>
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
          If you&apos;ve got feedback, an alert idea, or a vendor I should add,
          here&apos;s where to reach me.
        </p>
        <SocialLinks />
      </div>
    </main>
  );
}
