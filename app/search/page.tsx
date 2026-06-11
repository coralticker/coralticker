// /search — CTK-058 v1 three-class results page (plan D-058-2/3/4/5).
//
// Server Component, stacked sections per the Jon-ratified round-1 variant
// (a): CORALS (dictionary) / VENDORS / LISTINGS, each omitted entirely when
// empty. Direct per-request SQL — no unstable_cache (unbounded q key
// cardinality, D-058-4), no React cache() wrapper (single call site), no
// Suspense split (the three queries share one Promise.all; an eyebrow/body
// split would double-fetch without a shared cache wrapper). The searchParams
// read makes the route dynamic — correct posture per the CTK-046/126/127
// param-bearing-route precedent.
//
// noindex per plan §A11y/SEO — results pages stay out of the index; the
// canonical discovery surfaces (/corals, /vendors, feeds) keep the SEO
// weight.

import type { Metadata } from 'next';
import type { ReactNode } from 'react';
import Link from 'next/link';
import { GroupDivider } from '@/components/group-divider';
import { ListingCard } from '@/components/listing-card';
import { DataRow, type DataRowField } from '@/components/ui/data-row';
import { PageEyebrow } from '@/components/ui/page-eyebrow';
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
  // first-value through the same guard as parseSearchQuery (/code-review
  // fold #1).
  searchParams: Promise<{ q?: string | string[] }>;
}

// Per-query title in the guide L105 SERP convention `{specific} —
// CoralTicker` (close-out fold #2); the empty frame keeps the static title.
// noindex either way — results pages stay out of the index; SERP convention
// still governs the title shown in tab chrome / history / link previews.
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

// Section label per D-058-5 #1 (guide L282): mono-uppercase over a 1px
// `line` under-rule (CTK-129 served-neutral token), left-aligned to the
// data edge. Classification lives positionally at section level — never
// per-row.
//
// CTK-130 (#9): the "am I first?" bookkeeping (a hand-tracked prop threaded
// through three call sites) folds into the Tailwind first-child variant —
// `mt-12 first:mt-0`. The sections render inside a single wrapper <div> below,
// so the first RENDERED label (false-conditional siblings emit nothing) is the
// wrapper's :first-child and zeroes its top margin; the rest keep mt-12.
function SectionLabel({ children }: { children: ReactNode }) {
  return (
    <h2 className="font-mono text-xs font-normal uppercase tracking-[0.08em] text-ink border-b border-line pb-2 mt-12 first:mt-0">
      {children}
    </h2>
  );
}

// Page-local text-row shell shared by the CORALS + VENDORS dictionary classes
// (CTK-130 #10c). DELIBERATELY not promoted to a sitewide primitive: these are
// text-only search rows, and a shared component would fire INV-02 (the
// /brand-manager mockup gate) and collide with CTK-009 D2's wider row-shell
// (ListingRowFrame/thumb-row) calculus. Kept here, scoped to /search.
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

// Dictionary row per the ratified round-1 mock: text-only (no image slot —
// the curated dictionary has no imagery and an empty cream box would imply
// it does), bold canonical-name link to /coral/[slug], em-dash data row with
// Type. (three-class casing resolver) + Origin. (originator full-name
// resolver, sentinel-suppressed) + Matched. on alias-side hits only (guide
// L327 — stored alias text as-is, field-presence graceful degradation).
function CoralRow({ hit }: { hit: CoralSearchHit }) {
  // Type./Origin. via buildLineageFields — the casing + originator-resolution
  // + sentinel-suppression composition lives behind that builder's test
  // boundary; this row previously inlined an identical copy (CTK-140
  // /code-review fold — the builder's structural-subset param makes the
  // camelCase hit shape a two-key map away).
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

// Vendor row — same text-only thin-row shape; bold display-name link to
// /vendor/[slug].
function VendorRow({ hit }: { hit: VendorSearchHit }) {
  return <SearchTextRow href={`/vendor/${hit.slug}`} name={hit.displayName} />;
}

// Listings render through <ListingCard> verbatim — price-drop/vendor-markdown
// state-markers ride the in-row fields; rows link out per natural behavior
// (the frame's product_url anchor). Day-bucket dividers at 12+ cards per the
// feed-surface rule, INCLUDING the leading divider when the top bucket isn't
// today (D-058-5 #4, guide L437 leading-divider carve-out — /search is its
// first consumer; the no-Today-header base rule re-applies when the top
// bucket IS today). Buckets key on firstSeenAt — the surface's ordering
// timestamp (eventAt is null on this surface by construction).
//
// CTK-130: the leading carve-out + future-day suppression now live inside
// buildBucketedRows (bucketLabel totality returns null for same-day AND
// future-dated top rows), so the page just renders the annotated labels.
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
  // sections — not an error (D-058-4). The quiet empty frame is also where
  // example-query teaching would live if it ever opens (dormant per the
  // INV-02 close-out).
  if (q === null) {
    return <section className="px-6 py-12 max-w-3xl mx-auto" />;
  }

  const [corals, vendors, listingResult] = await Promise.all([
    searchCorals(q),
    searchVendors(q),
    searchListings(q),
  ]);
  const { listings, overflow } = listingResult;

  // Eyebrow per D-058-5 #2 (guide L296): per-class enumeration in section
  // order, zero classes omitted, single-chunk degradation acceptable, no
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
          prose register, declarative period (D-058-5 #3, guide L296),
          clamped per clampSearchEcho. The no-match line below deliberately
          doesn't repeat it. */}
      <h1 className="text-3xl md:text-4xl font-bold mb-8">
        Results for &ldquo;{clampSearchEcho(rawQ!)}&rdquo;.
      </h1>

      {noMatch ? (
        // Locked no-match copy verbatim (guide L100) — honest-zero class, no
        // I-voice, bracketed words render as underlined links.
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
        // RENDERED label as :first-child (CTK-130 #9) — the empty-section
        // conditionals emit nothing, so the first present label wins.
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
