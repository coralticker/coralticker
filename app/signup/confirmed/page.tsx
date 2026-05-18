// /signup/confirmed — post-confirmation landing per site.md §4.8.
//
// Surface 3 LOCKED copy verbatim from /brand-manager Session 7 pre-session
// sweep. Static page — no revalidate, no Suspense, no data fetching.
//
// First handshake-flavor "I" carve-out consumer per branding-guide.md line 98
// (gap-vs-handshake functional rule; success-acknowledgment is the first
// handshake example, this surface is the anchor). "as they list" lead-verb
// echoes branding-guide.md vocabulary per /brand-manager note.
//
// Ships at HTTP 200 on direct URL at v1. CTK-016 Resend wiring is not yet
// shipped, so no email currently points at this URL, but the surface is
// voice-correct + page-correct for direct visits.
//
// Metadata vocabulary per site.md §6.1 / architecture-v1.md §6.1.

import type { Metadata } from 'next';

// Metadata wording verbatim from site.md §6.1 line 1711. Description is
// empty because robots: noindex means the surface never appears in SERP —
// no wording to tune. Sitemap exclusion handled at CTK-017 (app/sitemap.ts)
// per site.md §6.3 line 1779.
export const metadata: Metadata = {
  title: 'Confirmed — CoralTicker',
  description: '',
  robots: { index: false, follow: true },
};

export default function SignupConfirmed() {
  return (
    <main className="px-6 py-12 max-w-3xl mx-auto">
      <h1 className="text-3xl md:text-4xl font-bold mb-6">
        You&apos;re subscribed.
      </h1>
      <p className="text-base leading-relaxed">
        I&apos;ll send new arrivals as they list.
      </p>
    </main>
  );
}
