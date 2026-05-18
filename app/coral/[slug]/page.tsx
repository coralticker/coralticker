// /coral/[slug] — per-named-coral cross-vendor availability per site.md §4.1
//
// Server Component rendering:
//   1. Page H1 (canonical_name) — Plex Sans 700, large
//   2. Lineage row — <DataRow> with drop-on-NULL field filter over
//      {coral_type, origin_vendor, year_introduced}. View-level filter
//      constructs `fields` from the non-null subset; <DataRow> API unchanged.
//   3. Description <p> — when named_corals.description != null
//   4. State-dynamic section transition — "Currently available." (>=1 listing)
//      / "Currently unavailable." (0 listings). 1px under-rule persists both states.
//      (Round 8 design-tool final 2026-05-13.)
//   5. Vendor availability list — <VendorAvailabilityRow> per listing,
//      first_seen_at DESC ordering applied inside getCoralAvailability().
//   6. Citations footer — when source_urls.length > 0. Voice-aligned introducer
//      ("Sources.") + body-text-sized link list. Off-domain links carry
//      target="_blank" rel="noopener noreferrer".
//
// generateStaticParams() returns active named_corals.slug. During matcher-dormancy
// (no seeded slugs yet — CTK-029 populates), returns [] → zero prerendered
// routes; Next.js 15 default `dynamicParams = true` handles unknown requests at
// runtime via ISR-on-demand, and not-found.tsx fires for slugs absent from
// named_corals (graceful 404 per Decision-at-Scaffold (b)).
//
// Empty-state vs. not-found are two distinct surfaces:
//   - not-found.tsx fires when slug is absent from named_corals (dormancy / typo)
//   - empty state (this file) fires when slug is present but zero current listings
//     (header flips to "Currently unavailable." + voice-aligned body line)
//
// ISR revalidate = 1800 per §1.2 + §4.1 lock (30 min).

import type { Metadata } from 'next';
import { notFound } from 'next/navigation';
import {
  getAllNamedCoralSlugs,
  getNamedCoralBySlug,
  type NamedCoral,
} from '@/lib/queries/named-corals';
import { getCoralAvailability } from '@/lib/queries/listings';
import { DataRow, type DataRowField } from '@/components/ui/data-row';
import { VendorAvailabilityRow } from './_components/vendor-availability-row';

export const revalidate = 1800;

interface PageProps {
  params: Promise<{ slug: string }>;
}

export async function generateStaticParams(): Promise<{ slug: string }[]> {
  return getAllNamedCoralSlugs();
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { slug } = await params;
  const coral = await getNamedCoralBySlug(slug);
  if (!coral) {
    return {
      title: 'Coral not in seed list — CoralTicker',
      description:
        "This coral isn't in the seed list yet. I'm working through the long tail.",
    };
  }
  // Metadata wording verbatim from site.md §6.1 line 1707.
  return {
    title: `${coral.canonical_name} — current vendor availability — CoralTicker`,
    description: `Current vendor availability and pricing for ${coral.canonical_name}. Drop alerts across reef coral vendors.`,
  };
}

function buildLineageFields(coral: NamedCoral): DataRowField[] {
  const fields: DataRowField[] = [];
  if (coral.coral_type !== null) {
    fields.push({ label: 'Type', value: coral.coral_type });
  }
  if (coral.origin_vendor !== null) {
    fields.push({ label: 'Origin', value: coral.origin_vendor });
  }
  if (coral.year_introduced !== null) {
    fields.push({ label: 'Year', value: String(coral.year_introduced) });
  }
  return fields;
}

const EMPTY_FALLBACK =
  "Nothing in stock right now. I'll surface it when it lists.";

export default async function CoralPage({ params }: PageProps) {
  const { slug } = await params;
  const coral = await getNamedCoralBySlug(slug);
  if (!coral) notFound();

  const listings = await getCoralAvailability(coral.id);
  const lineageFields = buildLineageFields(coral);
  const hasListings = listings.length > 0;
  const sectionHeader = hasListings
    ? 'Currently available.'
    : 'Currently unavailable.';

  return (
    <main className="px-6 py-12 max-w-3xl mx-auto">
      <h1 className="text-3xl md:text-4xl font-bold mb-4">
        {coral.canonical_name}
      </h1>

      {lineageFields.length > 0 ? (
        <div className="mb-6">
          <DataRow fields={lineageFields} />
        </div>
      ) : null}

      {coral.description !== null ? (
        <p className="text-base leading-relaxed mb-8">{coral.description}</p>
      ) : null}

      <div className="mt-10 mb-2">
        <h2 className="text-sm font-bold pb-2 border-b border-ink/20">
          {sectionHeader}
        </h2>
      </div>

      {hasListings ? (
        <div>
          {listings.map((listing) => (
            <VendorAvailabilityRow key={listing.id} listing={listing} />
          ))}
        </div>
      ) : (
        <p role="status" className="text-base text-ink py-6">
          {EMPTY_FALLBACK}
        </p>
      )}

      {coral.source_urls !== null && coral.source_urls.length > 0 ? (
        <footer className="mt-12 text-sm">
          <h2 className="text-sm font-bold pb-2 mb-2 border-b border-ink/20">
            Sources.
          </h2>
          <ul className="space-y-1">
            {coral.source_urls.map((url) => (
              <li key={url}>
                <a
                  href={url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="underline break-words"
                >
                  {url}
                </a>
              </li>
            ))}
          </ul>
        </footer>
      ) : null}
    </main>
  );
}
