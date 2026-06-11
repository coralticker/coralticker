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
//
// Body re-derived 2026-05-30 per CTK-095 Session 4 / branding-guide.md L102 —
// cross-sibling tonal asymmetry (only L102 example asserting curation principle
// rather than admitting limitation) caught by Jon site-eyeball; replaced with
// scope-honest framing per L15 reframe-limitations-as-scope rule.

import type { Metadata } from 'next';
import { NotFoundShell } from '@/components/ui/not-found-shell';

// 404 copy duplicated at ../page.tsx generateMetadata null-branch — edit both
// or neither. This export is the authority (paints the rendered head; the
// null-branch is RSC-flight-only, verified next@15.5.18); if ever deleting
// one, keep this one.
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
