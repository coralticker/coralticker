// /signup/confirmed — post-confirmation landing per site.md §4.8.
//
// Surface 3 LOCKED copy verbatim from /brand-manager Session 7 pre-session
// sweep. Static page — no revalidate, no Suspense, no data fetching.
//
// First handshake-flavor "I" carve-out consumer per branding-guide.md line 98
// (gap-vs-handshake functional rule; success-acknowledgment is the first
// handshake example, this surface is the anchor). Lead paragraph superseded
// 2026-06-11 by the brand-ratified daily-digest expectation line ("one email
// each morning") — the original "as they list" wording predated the digest.
//
// Ships at HTTP 200 on direct URL at v1. CTK-016 Resend wiring is not yet
// shipped, so no email currently points at this URL, but the surface is
// voice-correct + page-correct for direct visits.
//
// Metadata vocabulary per site.md §6.1 / architecture-v1.md §6.1.
//
// CTK-136 round-3-final price-methodology disclosure (Surface 1): the "I track
// what each vendor charges over time…" line wired below per the directive lock
// 2026-06-10 (copy/round-3/price-methodology-final.md). Static <p>, no data.

import type { Metadata } from 'next';
import Link from 'next/link';
import { PageShell } from '@/components/ui/page-shell';
import { PageH1 } from '@/components/ui/page-h1';

// Metadata wording verbatim from site.md §6.1 line 1711. Description is
// empty because robots: noindex means the surface never appears in SERP —
// no wording to tune. Sitemap exclusion handled at CTK-017 (app/sitemap.ts)
// per site.md §6.3 line 1779.
export const metadata: Metadata = {
  title: 'Confirmed', // suffix via root title.template
  description: '',
  robots: { index: false, follow: true },
};

export default function SignupConfirmed() {
  return (
    <PageShell as="section">
      <PageH1 className="mb-6">
        You&apos;re subscribed.
      </PageH1>
      <p className="text-base leading-relaxed">
        I&apos;ll send one email each morning — new arrivals, price drops, and
        back-in-stock from the vendors I cover.
      </p>
      <p className="text-base leading-relaxed mt-4">
        I track what each vendor charges over time — so you can see how a price
        has moved, not just today&apos;s number.
      </p>
      <p className="text-base leading-relaxed mt-4">
        Until then,{' '}
        <Link href="/new" className="underline underline-offset-[3px] decoration-1">
          see what&apos;s already listed
        </Link>
        .
      </p>
    </PageShell>
  );
}
