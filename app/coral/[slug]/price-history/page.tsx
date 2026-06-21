import type { Metadata } from 'next';
import { notFound } from 'next/navigation';
import {
  getAllNamedCoralSlugs,
  getNamedCoralBySlug,
  getCoralLastSeenAt,
} from '@/lib/queries/named-corals';
import {
  getCoralAvailability,
  getCoralInWindowVendorCount,
} from '@/lib/queries/listings';
import { getVendorDisplayNamesBySlug } from '@/lib/queries/vendors';
import {
  getCoralPriceByVendor,
  getCoralPriceEnvelope,
} from '@/lib/queries/coral-price';
import {
  computeDomain,
  groupByVendor,
  isThinHistory,
  thinObservation,
} from '@/lib/chart/price-history-geometry';
import { vendorShorthand } from '@/lib/format/vendor-label';
import { PageShell } from '@/components/ui/page-shell';
import { PageEyebrow } from '@/components/ui/page-eyebrow';
import { PageH1 } from '@/components/ui/page-h1';
import { SectionHeader } from '@/components/ui/section-header';
import { formatRelativeTime } from '@/lib/format/relative-time';
import { pluralize } from '@/lib/format/pluralize';
import { PriceHistoryChart } from './_components/price-history-chart';
import { ThinHistoryState } from './_components/thin-history-state';
import { PriceSummaryRow } from './_components/price-summary-row';

// Default lookback window (D-3 eyebrow shows "90 DAYS"). EXPLICIT 90, never null
// — null would trip the unbounded days×listings×LATERAL fan-out on both series
// functions (CTK-179 (c)); the page never wants that.
const WINDOW_DAYS = 90;

// Static + ISR: no searchParams here (unlike the parent /coral/[slug]), so the
// route prerenders and revalidates every 300s — matching the unstable_cache
// windows the price-series + availability queries carry.
export const revalidate = 300;

const MONTHS = [
  'JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN',
  'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC',
];
function monthDay(ms: number): string {
  const dt = new Date(ms);
  return `${MONTHS[dt.getUTCMonth()]!} ${dt.getUTCDate()}`;
}

export async function generateStaticParams(): Promise<{ slug: string }[]> {
  return getAllNamedCoralSlugs();
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  const { slug } = await params;
  const coral = await getNamedCoralBySlug(slug);
  if (!coral) {
    return {
      title: 'Coral not in seed list',
      description:
        "This coral isn't in the seed list yet. I'm working through the long tail.",
    };
  }
  // Self-canonical child route with its own intent-meta ("[coral] price history
  // / price trend") — NOT canonical'd back to the parent /coral/[slug] (D-1).
  // No JSON-LD on this route (no honest schema.org type for a price-trend view).
  return {
    title: `${coral.canonical_name} price history`,
    description: `Price history for ${coral.canonical_name}: the cross-vendor cheapest price and per-vendor price trend across reef coral vendors.`,
    alternates: { canonical: `/coral/${slug}/price-history` },
    openGraph: {
      url: `/coral/${slug}/price-history`,
      siteName: 'CoralTicker',
      type: 'website',
      locale: 'en_US',
    },
    twitter: { card: 'summary' },
  };
}

export default async function PriceHistoryPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const coral = await getNamedCoralBySlug(slug);
  if (!coral) notFound();

  const [envelope, vendorPoints, listings, displayNameBySlug, lastSeenAt, inWindowVendorCount] =
    await Promise.all([
      getCoralPriceEnvelope(coral.id, WINDOW_DAYS), // floor — heavy line, unchanged
      getCoralPriceByVendor(coral.id, WINDOW_DAYS), // per-vendor lines
      getCoralAvailability(coral.id), // summary row + thin fallback (in-stock only)
      getVendorDisplayNamesBySlug(), // end-label fallback names
      getCoralLastSeenAt(coral.id), // eyebrow freshness (last CHECKED, not last changed)
      getCoralInWindowVendorCount(coral.id), // stock-unfiltered all-OOS vendor fallback
    ]);

  const tracks = groupByVendor(vendorPoints);
  const now = new Date();
  const nowMs = now.getTime();
  const thin = isThinHistory(envelope, tracks);

  // Vendor N = vendors with a rendered line (honest-gap → a vendor only appears
  // if it had an in-stock priced day). Cascading fallback so a carried coral
  // never reads "0 VENDORS": rendered tracks → in-stock availability vendors →
  // the stock-UNFILTERED in-window vendor count (the all-OOS case — getCoral-
  // Availability defaults to in-stock only, so an all-OOS coral has zero of the
  // first two; mirrors the parent /coral/[slug] all-OOS eyebrow).
  const availabilityVendors = new Set(listings.map((l) => l.vendorSlug)).size;
  const vendorN = tracks.length || availabilityVendors || inWindowVendorCount;

  // Eyebrow. Normal: N VENDORS · 90 DAYS · UPDATED {last-seen freshness}.
  // Freshness is last_seen_at (when the data was last CONFIRMED), NOT the last
  // price change — the latter reads "UPDATED 2 MONTHS AGO" beside a live row.
  // Thin: N VENDOR(S) · FIRST SEEN {earliest observed}.
  const eyebrowChunks = thin
    ? [
        `${vendorN} ${pluralize(vendorN, 'VENDOR', 'VENDORS')}`,
        thinFirstSeenChunk(tracks, listings, now),
      ]
    : [
        `${vendorN} ${pluralize(vendorN, 'VENDOR', 'VENDORS')}`,
        `${WINDOW_DAYS} DAYS`,
        ...(lastSeenAt
          ? [`UPDATED ${formatRelativeTime(lastSeenAt, now).toUpperCase()}`]
          : []),
      ];

  const domain = computeDomain(envelope, tracks, nowMs);

  // aria "current cheapest" comes from availability; the chart floor comes from
  // the envelope. The two can skew slightly across their separate 300s caches —
  // accepted for v1 (reconciling would couple the caches; not free). The summary
  // row + aria share the availability source, so they stay consistent with each
  // other.
  // > 0, not just non-null: a phantom currentPrice of 0 would surface as aria
  // "current cheapest $0" (CTK-162 /code-review #1, Tier 1A).
  const priced = listings.filter(
    (l) => l.inStock && l.currentPrice !== null && l.currentPrice > 0,
  );
  const cheapest = priced.length
    ? priced.reduce((a, b) =>
        (b.currentPrice as number) < (a.currentPrice as number) ? b : a,
      )
    : null;
  const ariaLabel = cheapest
    ? `Cross-vendor price history for ${coral.canonical_name}. Current cheapest $${(cheapest.currentPrice as number).toFixed(0)} at ${vendorShorthand(cheapest.vendorSlug, cheapest.vendorDisplayName)}.`
    : `Cross-vendor price history for ${coral.canonical_name}.`;

  // Thin observation: prefer the per-vendor point (a REAL min, never $0); else
  // fall back to availability (which CAN be null-price → "price on request",
  // never a fabricated $0).
  const thinObs = thin ? thinObservation(tracks) : null;
  const thinRender = thin
    ? thinObs
      ? { dateLabel: monthDay(Date.parse(`${thinObs.day}T00:00:00Z`)), price: thinObs.minPrice }
      : listings[0]
        ? {
            dateLabel: monthDay(Date.parse(listings[0].firstSeenAt)),
            price: listings[0].currentPrice,
          }
        : { dateLabel: '', price: null }
    : null;

  return (
    <PageShell as="article">
      <PageEyebrow chunks={eyebrowChunks} />
      <PageH1 className="mb-4">{coral.canonical_name}</PageH1>

      <SectionHeader className="mt-2">Cross-vendor price.</SectionHeader>

      {thin && thinRender ? (
        <ThinHistoryState observation={thinRender} />
      ) : (
        <>
          <PriceHistoryChart
            envelope={envelope}
            tracks={tracks}
            domain={domain}
            displayNameBySlug={displayNameBySlug}
            ariaLabel={ariaLabel}
          />
          {/* Legend (branding-guide §"Short-copy assets" price-history / D-3).
              Content/prose register — sentence case, NOT the uppercase-mono
              caption default (/brand-manager register correction). Terse copy
              swaps in under sm. */}
          <p className="text-sm leading-relaxed text-ink mt-3.5">
            <span className="hidden sm:inline">
              Heavy line: cheapest across vendors, per day. Thin lines: each vendor&rsquo;s cheapest in stock. (N) = listings at that vendor. Gap = none in stock.
            </span>
            <span className="sm:hidden">Gap = none in stock.</span>
          </p>
        </>
      )}

      {/* Size-normalization caption — content register, under the chart (NOT the
          footer). Unchanged from the per-listing build: the min is still a real
          per-listing price, so "I don't adjust for size" holds (arguably more apt
          now — a vendor's min jumps when its cheapest listing sells out). Copy
          PROVISIONAL pending /copy-writer + /brand-manager. */}
      <p className="text-sm leading-relaxed text-ink mt-4 max-w-[62ch]">
        Prices are per listing, as sold &mdash; I don&rsquo;t adjust for size. A bigger frag or colony costs more, so a price jump can mean a larger piece, not a pricier coral.
      </p>

      <PriceSummaryRow listings={listings} coral={coral} />
    </PageShell>
  );
}

// Thin-state FIRST SEEN chunk: earliest per-vendor day if present, else the
// earliest availability first_seen_at, else a bare marker. Guards empty series
// so formatRelativeTime never reads an undefined timestamp.
function thinFirstSeenChunk(
  tracks: ReturnType<typeof groupByVendor>,
  listings: { firstSeenAt: string }[],
  now: Date,
): string {
  const days = tracks.flatMap((t) => t.points.map((p) => Date.parse(`${p.day}T00:00:00Z`)));
  const fromListings = listings.map((l) => Date.parse(l.firstSeenAt));
  const all = [...days, ...fromListings];
  if (all.length === 0) return 'JUST STARTED TRACKING';
  const earliest = new Date(Math.min(...all));
  return `FIRST SEEN ${formatRelativeTime(earliest.toISOString(), now).toUpperCase()}`;
}
