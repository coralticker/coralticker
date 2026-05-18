// app/coral/[slug]/not-found.tsx — graceful 404 per Decision-at-Scaffold (b)
//
// Fires when getNamedCoralBySlug() returns null (slug typo, retired entry, or
// matcher-dormancy — slug not yet in seed list). Next.js 15 default
// `dynamicParams = true` lets unknown slugs reach the page at runtime; the page
// calls notFound() on null and this surface renders.
//
// Copy locked verbatim 2026-05-14 via /brand-manager + /copy-writer pre-session
// per CTK-040 Session 5 directive + branding-guide.md line 98 carve-out
// ("dormancy-not-found" added to the "I" voice surface list).

import Link from 'next/link';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Coral not in seed list — CoralTicker',
  description:
    "This coral isn't in the seed list yet. I'm working through the long tail.",
};

export default function CoralNotFound() {
  return (
    <main className="px-6 py-12 max-w-3xl mx-auto">
      <h1 className="text-3xl md:text-4xl font-bold mb-6">
        This coral isn&apos;t in the seed list yet.
      </h1>
      <p className="text-base leading-relaxed mb-8">
        I&apos;m working through the long tail; check the new arrivals to see
        what&apos;s listed today.
      </p>
      <p className="text-base">
        <Link href="/new" className="underline">
          &larr; back to new arrivals
        </Link>
      </p>
    </main>
  );
}
