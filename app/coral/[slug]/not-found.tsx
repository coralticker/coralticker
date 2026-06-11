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

import type { Metadata } from 'next';
import { NotFoundShell } from '@/components/ui/not-found-shell';

// 404 copy duplicated at ../page.tsx generateMetadata null-branch — edit both
// or neither. This export is the authority (paints the rendered head; the
// null-branch is RSC-flight-only, verified next@15.5.18); if ever deleting
// one, keep this one.
export const metadata: Metadata = {
  title: 'Coral not in seed list', // suffix via root title.template
  description:
    "This coral isn't in the seed list yet. I'm working through the long tail.",
};

export default function CoralNotFound() {
  return (
    <NotFoundShell
      title="This coral isn't in the seed list yet."
      body="I'm working through the long tail; check the new arrivals to see what's listed today."
      backHref="/new"
      backLabel="← back to new arrivals"
    />
  );
}
