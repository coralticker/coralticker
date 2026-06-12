// Direct per-request SQL — no unstable_cache (unbounded q key cardinality), no
// React cache() wrapper (single call site), no Suspense split (the three
// queries share one Promise.all; an eyebrow/body split would double-fetch
// without a shared cache wrapper). The searchParams read makes the route
// dynamic.
//
// noindex — results pages stay out of the index; the canonical discovery
// surfaces (/corals, /vendors, feeds) keep the SEO weight.

import type { Metadata } from 'next';
import type { ReactNode } from 'react';
import Link from 'next/link';
import { GroupDivider } from '@/components/group-divider';
import { ListingCard } from '@/components/listing-card';
import { DataRow, type DataRowField } from '@/components/ui/data-row';
import { PageEyebrow } from '@/components/ui/page-eyebrow';
import { PageH1 } from '@/components/ui/page-h1';
import {
  DIVIDER_THRESHOLD,
  buildBucketedRows,
} from '@/lib/format/group-bucket';
import { buildLineageFields } from '@/lib/format/lineage-fields';
import { pluralize } from '@/lib/format/pluralize';
import {
  clampSearchEcho,
  parseSearchQuery,
} from '@/lib/queries/listing-params';
import type { Listing } from '@/lib/queries/listings';
import {
  SEARCH_LISTINGS_LIMIT,
  searchCorals,
  searchListings,
  searchVendors,
  type CoralSearchHit,
  type VendorSearchHit,
} from '@/lib/queries/search';

interface PageProps {
  // string[] when the URL carries duplicate ?q= keys — both consumers below
  // first-value through the same guard as parseSearchQuery.
  searchParams: Promise<{ q?: string | string[] }>;
}

// Per-query title in the SERP convention `{specific} — CoralTicker`; the empty
// frame keeps the static title. noindex either way — but the title still
// governs tab chrome / history / link previews.
export async function generateMetadata({
  searchParams,
}: PageProps): Promise<Metadata> {
  const sp = await searchParams;
  const q = parseSearchQuery(sp.q);
  return {
    // suffix via root title.template
    title:
      q === null ? 'Search' : `Results for "${clampSearchEcho(sp.q)}"`,
    robots: { index: false, follow: true },
  };
}

const rowLinkClass =
  'font-bold underline underline-offset-[3px] decoration-1 hover:decoration-2';

// Classification lives positionally at section level — never per-row.
//
// `mt-12 first:mt-0`: the sections render inside a single wrapper <div> below,
// so the first RENDERED label (false-conditional siblings emit nothing) is the
// wrapper's :first-child and zeroes its top margin; the rest keep mt-12.
function SectionLabel({ children }: { children: ReactNode }) {
  return (
    <h2 className="font-mono text-xs font-normal uppercase tracking-[0.08em] text-ink border-b border-line pb-2 mt-12 first:mt-0">
      {children}
    </h2>
  );
}

// Page-local text-row shell shared by the CORALS + VENDORS dictionary classes.
// DELIBERATELY not promoted to a sitewide primitive: these are text-only
// search rows, and a shared component would fire the mockup gate and collide
// with the wider row-shell (ListingRowFrame/thumb-row) calculus. Kept here,
// scoped to /search.
function SearchTextRow({
  href,
  name,
  children,
}: {
  href: string;
  name: string;
  children?: ReactNode;
}) {
  return (
    <div className="py-6 border-b border-line">
      <p className="text-base leading-snug">
        <Link href={href} className={rowLinkClass}>
          {name}
        </Link>
      </p>
      {children}
    </div>
  );
}

// Dictionary row: text-only (no image slot — the curated dictionary has no
// imagery and an empty cream box would imply it does), bold canonical-name
// link to /coral/[slug], em-dash data row with Type. + Origin. + Matched. on
// alias-side hits only (stored alias text as-is, field-presence graceful
// degradation).
function CoralRow({ hit }: { hit: CoralSearchHit }) {
  const fields: DataRowField[] = buildLineageFields({
    coral_type: hit.coralType,
    origin_vendor: hit.originVendor,
  });
  if (hit.matchedAlias !== null) {
    fields.push({ label: 'Matched', value: hit.matchedAlias });
  }

  return (
    <SearchTextRow href={`/coral/${hit.slug}`} name={hit.canonicalName}>
      {fields.length > 0 ? (
        <div className="mt-2">
          <DataRow fields={fields} />
        </div>
      ) : null}
    </SearchTextRow>
  );
}

function VendorRow({ hit }: { hit: VendorSearchHit }) {
  return <SearchTextRow href={`/vendor/${hit.slug}`} name={hit.displayName} />;
}

// Day-bucket dividers at 12+ cards, INCLUDING the leading divider when the top
// bucket isn't today (leading-divider carve-out; the no-Today-header base rule
// re-applies when the top bucket IS today). Buckets key on firstSeenAt — the
// surface's ordering timestamp (eventAt is null on this surface by
// construction). The leading carve-out + future-day suppression live inside
// buildBucketedRows, so the page just renders the annotated labels.
function ListingsRows({ listings }: { listings: Listing[] }) {
  if (listings.length < DIVIDER_THRESHOLD) {
    return (
      <>
        {listings.map((l) => (
          <ListingCard key={l.id} listing={l} />
        ))}
      </>
    );
  }

  const now = new Date();
  const out: ReactNode[] = [];
  buildBucketedRows(listings, (l) => l.firstSeenAt, now).forEach(({ row, label }, i) => {
    if (label !== null) {
      out.push(<GroupDivider key={`div-${i}`} label={label} />);
    }
    out.push(<ListingCard key={row.id} listing={row} />);
  });
  return <>{out}</>;
}

export default async function SearchPage({ searchParams }: PageProps) {
  const sp = await searchParams;
  const rawQ = sp.q;
  const q = parseSearchQuery(rawQ);

  // Null/empty q: the page frame with the (nav) input and no result
  // sections — not an error.
  if (q === null) {
    return <section className="px-6 py-12 max-w-3xl mx-auto" />;
  }

  const [corals, vendors, listingResult] = await Promise.all([
    searchCorals(q),
    searchVendors(q),
    searchListings(q),
  ]);
  const { listings, overflow } = listingResult;

  // Eyebrow: per-class enumeration in section order, zero classes omitted, no
  // freshness chunk (dictionary/vendor rows carry no timestamp). At the
  // listings cap the count chunk renders `50+ LISTINGS` — the `+` marks a
  // floor per disclosure-symmetry. All-empty renders `0 RESULTS`.
  const chunks: string[] = [];
  if (corals.length > 0) {
    chunks.push(`${corals.length} ${pluralize(corals.length, 'CORAL', 'CORALS')}`);
  }
  if (vendors.length > 0) {
    chunks.push(`${vendors.length} ${pluralize(vendors.length, 'VENDOR', 'VENDORS')}`);
  }
  if (overflow) {
    chunks.push(`${SEARCH_LISTINGS_LIMIT}+ LISTINGS`);
  } else if (listings.length > 0) {
    chunks.push(
      `${listings.length} ${pluralize(listings.length, 'LISTING', 'LISTINGS')}`,
    );
  }
  const noMatch = chunks.length === 0;

  return (
    <section className="px-6 py-12 max-w-3xl mx-auto">
      <PageEyebrow chunks={noMatch ? ['0 RESULTS'] : chunks} />
      {/* H1 owns the query echo — raw (un-normalized) q in curly quotes,
          clamped per clampSearchEcho. The no-match line below deliberately
          doesn't repeat it. */}
      <PageH1 className="mb-8">
        Results for &ldquo;{clampSearchEcho(rawQ!)}&rdquo;.
      </PageH1>

      {noMatch ? (
        // No-match copy — honest-zero class, no I-voice.
        <p role="status" className="text-base leading-relaxed text-ink py-6">
          No matches. Browse the curated list at{' '}
          <Link href="/corals" className="underline underline-offset-[3px]">
            corals
          </Link>
          , or by vendor at{' '}
          <Link href="/vendors" className="underline underline-offset-[3px]">
            vendors
          </Link>
          .
        </p>
      ) : (
        // Single wrapper so SectionLabel's `first:mt-0` targets the first
        // RENDERED label as :first-child — the empty-section conditionals emit
        // nothing, so the first present label wins.
        <div>
          {corals.length > 0 ? (
            <>
              <SectionLabel>CORALS</SectionLabel>
              {corals.map((hit) => (
                <CoralRow key={hit.id} hit={hit} />
              ))}
            </>
          ) : null}

          {vendors.length > 0 ? (
            <>
              <SectionLabel>VENDORS</SectionLabel>
              {vendors.map((hit) => (
                <VendorRow key={hit.slug} hit={hit} />
              ))}
            </>
          ) : null}

          {listings.length > 0 ? (
            <>
              <SectionLabel>LISTINGS</SectionLabel>
              <ListingsRows listings={listings} />
            </>
          ) : null}
        </div>
      )}
    </section>
  );
}
