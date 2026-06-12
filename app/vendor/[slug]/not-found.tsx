// Fires when getVendorBySlug() returns null (slug typo or vendor never seeded).
// Next.js 15 default `dynamicParams = true` lets unknown slugs reach the page
// at runtime; the page calls notFound() on null and this surface renders.
// Distinct from retired-vendor case (vendors.active = false), which keeps the
// vendor row + renders an inline fallback at page.tsx — not this surface.

import type { Metadata } from 'next';
import { NotFoundShell } from '@/components/ui/not-found-shell';

// 404 copy duplicated at ../page.tsx generateMetadata null-branch — edit both
// or neither. This export is the authority (paints the rendered head; the
// null-branch is RSC-flight-only); if ever deleting one, keep this one.
export const metadata: Metadata = {
  title: 'Vendor not found', // suffix via root title.template
  description: "That vendor isn't on CoralTicker yet.",
};

export default function VendorNotFound() {
  return (
    <NotFoundShell
      title="That vendor isn't on CoralTicker yet."
      body="I don't cover every reef vendor. See the ones I do."
      backHref="/vendors"
      backLabel="← back to vendors"
    />
  );
}
