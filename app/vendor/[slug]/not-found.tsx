// app/vendor/[slug]/not-found.tsx — graceful 404 per site.md §4.5 not-found row
//
// Fires when getVendorBySlug() returns null (slug typo or vendor never seeded).
// Next.js 15 default `dynamicParams = true` lets unknown slugs reach the page
// at runtime; the page calls notFound() on null and this surface renders.
//
// Copy locked verbatim 2026-05-14 via /brand-manager pre-session per CTK-040
// Session 6 directive (5-surface lock; branding-guide.md line 98 carve-out
// scope extended to include vendor-not-found per future-surface-inheritance
// clause). Distinct from retired-vendor case (vendors.active = false), which
// keeps the vendor row + renders an inline fallback at page.tsx — not this
// surface.

import Link from 'next/link';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Vendor not found — CoralTicker',
  description: "That vendor isn't on CoralTicker yet.",
};

export default function VendorNotFound() {
  return (
    <main className="max-w-3xl mx-auto px-6 py-16">
      <h1 className="text-3xl md:text-4xl font-bold mb-6">
        That vendor isn&apos;t on CoralTicker yet.
      </h1>
      <p className="text-base leading-relaxed mb-8">I add vendors deliberately.</p>
      <p className="text-base">
        <Link href="/new" className="underline">
          &larr; back to new arrivals
        </Link>
      </p>
    </main>
  );
}
