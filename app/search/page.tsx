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
  bucketLabel,
  bucketTransition,
} from '@/lib/format/group-bucket';
import { resolveOriginVendor } from '@/lib/format/origin-vendor';
import { formatTypeLabel } from '@/lib/format/type-label';
import {
  SEARCH_QUERY_MAX_LENGTH,
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

// H1 + <title> query echo — raw (un-normalized) q, but clamped: trimmed +
// sliced to the parser's 80-char cap so an arbitrarily long ?q= can't blow
// out the title bar or the H1 line (close-out fold #3; matching only ever
// sees the first 80 normalized chars anyway). Array guard mirrors
// parseSearchQuery — first value wins, so the echo names the value that
// drove matching.
function clampEcho(rawQ: string | string[] | undefined): string {
  const single = Array.isArray(rawQ) ? rawQ[0] : rawQ;
  return (single ?? '').trim().slice(0, SEARCH_QUERY_MAX_LENGTH);
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
    title:
      q === null
        ? 'Search — CoralTicker'
        : `Results for "${clampEcho(sp.q)}" — CoralTicker`,
    robots: { index: false, follow: true },
  };
}

const rowLinkClass =
  'font-bold underline underline-offset-[3px] decoration-1 hover:decoration-2';

// Section label per D-058-5 #1 (guide L282): mono-uppercase over a 1px
// ink/30 under-rule, left-aligned to the data edge. Classification lives
// positionally at section level — never per-row.
function SectionLabel({
  first,
  children,
}: {
  first?: boolean;
  children: ReactNode;
}) {
  return (
    <h2
      className={`font-mono text-xs font-normal uppercase tracking-[0.08em] text-ink border-b border-ink/30 pb-2 ${
        first ? 'mt-0' : 'mt-12'
      }`}
    >
      {children}
    </h2>
  );
}

// Dictionary row per the ratified round-1 mock: text-only (no image slot —
// the curated dictionary has no imagery and an empty cream box would imply
// it does), bold canonical-name link to /coral/[slug], em-dash data row with
// Type. (three-class casing resolver) + Origin. (originator full-name
// resolver, sentinel-suppressed) + Matched. on alias-side hits only (guide
// L327 — stored alias text as-is, field-presence graceful degradation).
function CoralRow({ hit }: { hit: CoralSearchHit }) {
  const fields: DataRowField[] = [];
  if (hit.coralType) {
    const type = formatTypeLabel(hit.coralType);
    fields.push({
      label: 'Type',
      value: type.italic ? { kind: 'italic', value: type.display } : type.display,
    });
  }
  if (hit.originVendor) {
    const origin = resolveOriginVendor(hit.originVendor);
    if (!('suppress' in origin && origin.suppress)) {
      fields.push({ label: 'Origin', value: origin.display });
    }
  }
  if (hit.matchedAlias !== null) {
    fields.push({ label: 'Matched', value: hit.matchedAlias });
  }

  return (
    <div className="py-6 border-b border-ink/30">
      <p className="text-base leading-snug">
        <Link href={`/coral/${hit.slug}`} className={rowLinkClass}>
          {hit.canonicalName}
        </Link>
      </p>
      {fields.length > 0 ? (
        <div className="mt-2">
          <DataRow fields={fields} />
        </div>
      ) : null}
    </div>
  );
}

// Vendor row — same text-only thin-row shape; bold display-name link to
// /vendor/[slug].
function VendorRow({ hit }: { hit: VendorSearchHit }) {
  return (
    <div className="py-6 border-b border-ink/30">
      <p className="text-base leading-snug">
        <Link href={`/vendor/${hit.slug}`} className={rowLinkClass}>
          {hit.displayName}
        </Link>
      </p>
    </div>
  );
}

// Listings render through <ListingCard> verbatim — price-drop/vendor-markdown
// state-markers ride the in-row fields; rows link out per natural behavior
// (the frame's product_url anchor). Day-bucket dividers at 12+ cards per the
// feed-surface rule, INCLUDING the leading divider when the top bucket isn't
// today (D-058-5 #4, guide L396 leading-divider carve-out — /search is its
// first consumer; the no-Today-header base rule re-applies when the top
// bucket IS today). Buckets key on firstSeenAt — the surface's ordering
// timestamp (eventAt is null on this surface by construction).
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
  for (let i = 0; i < listings.length; i++) {
    const curr = listings[i]!;
    const prev = i > 0 ? listings[i - 1]! : null;
    if (prev === null) {
      // Leading carve-out: bucketTransition against now answers "is the top
      // bucket a different local day than today." Different-AND-AHEAD (a
      // future-dated top row — midnight Neon-vs-Vercel clock skew reaches
      // it) suppresses instead of throwing: bucketLabel's dayDiff <= 0
      // throw is a caller contract, so the past-day check rides the label
      // computation caller-side (/code-review fold #2; the lib-level
      // totality fix is the Tier 3 bundle CTK's).
      if (bucketTransition(now.toISOString(), curr.firstSeenAt)) {
        const currDate = new Date(curr.firstSeenAt);
        const isPastDay =
          new Date(currDate.getFullYear(), currDate.getMonth(), currDate.getDate()).getTime() <
          new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
        if (isPastDay) {
          out.push(
            <GroupDivider key="div-lead" label={bucketLabel(curr.firstSeenAt, now)} />,
          );
        }
      }
    } else if (bucketTransition(prev.firstSeenAt, curr.firstSeenAt)) {
      out.push(
        <GroupDivider key={`div-${i}`} label={bucketLabel(curr.firstSeenAt, now)} />,
      );
    }
    out.push(<ListingCard key={curr.id} listing={curr} />);
  }
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
    chunks.push(`${corals.length} ${corals.length === 1 ? 'CORAL' : 'CORALS'}`);
  }
  if (vendors.length > 0) {
    chunks.push(`${vendors.length} ${vendors.length === 1 ? 'VENDOR' : 'VENDORS'}`);
  }
  if (overflow) {
    chunks.push(`${SEARCH_LISTINGS_LIMIT}+ LISTINGS`);
  } else if (listings.length > 0) {
    chunks.push(
      `${listings.length} ${listings.length === 1 ? 'LISTING' : 'LISTINGS'}`,
    );
  }
  const noMatch = chunks.length === 0;

  return (
    <section className="px-6 py-12 max-w-3xl mx-auto">
      <PageEyebrow chunks={noMatch ? ['0 RESULTS'] : chunks} />
      {/* H1 owns the query echo — raw (un-normalized) q in curly quotes,
          prose register, declarative period (D-058-5 #3, guide L296),
          clamped per clampEcho. The no-match line below deliberately
          doesn't repeat it. */}
      <h1 className="text-3xl md:text-4xl font-bold mb-8">
        Results for &ldquo;{clampEcho(rawQ!)}&rdquo;.
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
        <>
          {corals.length > 0 ? (
            <>
              <SectionLabel first>CORALS</SectionLabel>
              {corals.map((hit) => (
                <CoralRow key={hit.id} hit={hit} />
              ))}
            </>
          ) : null}

          {vendors.length > 0 ? (
            <>
              <SectionLabel first={corals.length === 0}>VENDORS</SectionLabel>
              {vendors.map((hit) => (
                <VendorRow key={hit.slug} hit={hit} />
              ))}
            </>
          ) : null}

          {listings.length > 0 ? (
            <>
              <SectionLabel first={corals.length === 0 && vendors.length === 0}>
                LISTINGS
              </SectionLabel>
              <ListingsRows listings={listings} />
            </>
          ) : null}
        </>
      )}
    </section>
  );
}
