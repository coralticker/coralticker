// CTK-162 D-4 Variant B — beat 2 of a /guides coral entry: the live market line
// (the payoff). The single net-new composition for /guides. Beat 1 (name-link +
// lore) is MDX/copy-writer's, owned by the <CoralEntry> wrapper; this component
// renders ONLY the data bind — never a hand-typed price.
//
// Mapped to existing functions (design-once, no fresh price_history query):
//   cheapest-now + vendor + label flex  → getCoralAvailability (single-vendor-safe)
//   observed range + thin detection      → get_coral_price_envelope (0049 floor)
//   vendor count N (range-window)        → get_coral_price_by_vendor (0050) tracks
//   first-seen (LIFETIME, not windowed)  → getCoralFirstSeenAt
//   last-seen (OOS gap line)             → getCoralLastSeenAt
//
// Two honest-gap states reuse the price-history page's gap voice: (a) OOS-with-
// history — range shows, NO buyable price; (b) thin-history — no range, a single
// current listing may still render. Never a stale price (Tier-1A trust floor).

import { Fragment, type ReactNode } from 'react';
import Link from 'next/link';
import { DataRow } from '@/components/ui/data-row';
import { getNamedCoralBySlug, getCoralFirstSeenAt, getCoralLastSeenAt } from '@/lib/queries/named-corals';
import { getCoralAvailability, getCoralInWindowVendorCount } from '@/lib/queries/listings';
import {
  getCoralPriceEnvelope,
  getCoralPriceByVendor,
  PRICE_HISTORY_WINDOW_DAYS,
} from '@/lib/queries/coral-price';
import { groupByVendor, isThinHistory } from '@/lib/chart/price-history-geometry';
import { buildCoralReferenceFields } from '@/lib/format/coral-reference-fields';
import { formatRelativeTime } from '@/lib/format/relative-time';
import { pluralize } from '@/lib/format/pluralize';

// Per-coral micro-chrome — distinct from <PageEyebrow> (the page-level KIND ·
// UPDATED line). Mono-uppercase + forest mid-dot; the range chunk drops tracking
// so its en-dash sits tight (near-black, distinct from the spaced forest dot).
function MarketChrome({ chunks }: { chunks: ReactNode[] }) {
  return (
    <p className="font-mono text-xs uppercase tracking-[0.08em] text-ink mb-1.5">
      {chunks.map((c, i) => (
        <Fragment key={i}>
          {i > 0 && (
            <span aria-hidden="true" className="text-forest">
              {' · '}
            </span>
          )}
          {c}
        </Fragment>
      ))}
    </p>
  );
}

function rangeChunk(min: number, max: number): ReactNode {
  // En-dash, no surrounding spaces, near-black, tracking-normal (D-4 Q2).
  return (
    <span className="normal-case tracking-normal">{`$${Math.round(min)}–$${Math.round(max)}`}</span>
  );
}

export async function CoralReference({ slug }: { slug: string }) {
  const coral = await getNamedCoralBySlug(slug);
  // Defensive: an MDX-authored slug not in the active seed list. Render the honest
  // gap rather than a broken bind — loud enough to catch in the eyeball pass.
  if (!coral) {
    return (
      <div className="mt-3.5">
        <MarketChrome chunks={['NOT IN CATALOG']} />
        <p className="text-base leading-relaxed text-ink">
          I don&rsquo;t track this one yet.
        </p>
      </div>
    );
  }

  const WINDOW = PRICE_HISTORY_WINDOW_DAYS;
  const [listings, envelope, vendorPoints, firstSeenAt, lastSeenAt, inWindowVendorCount] =
    await Promise.all([
      getCoralAvailability(coral.id),
      getCoralPriceEnvelope(coral.id, WINDOW),
      getCoralPriceByVendor(coral.id, WINDOW),
      getCoralFirstSeenAt(coral.id),
      getCoralLastSeenAt(coral.id),
      getCoralInWindowVendorCount(coral.id), // stock-unfiltered all-OOS vendor fallback
    ]);

  const now = new Date();
  const tracks = groupByVendor(vendorPoints);

  // N = vendors with a rendered (in-stock-priced) line in the range window.
  // Three-stage cascade IN LOCKSTEP with the price-history page (page.tsx L133):
  // rendered tracks → in-stock availability vendors → stock-unfiltered in-window
  // count. The third stage is load-bearing for the OOS/thin branches: an all-OOS
  // coral has zero tracks AND zero in-stock availability vendors, so without it
  // the chrome would read a false "0 VENDORS" (the Tier-1B defect already fixed on
  // the sibling surface — the two must agree on the same coral).
  const availabilityVendors = new Set(listings.map((l) => l.vendorSlug)).size;
  const vendorN = tracks.length || availabilityVendors || inWindowVendorCount;
  const vendorLabel = pluralize(vendorN, 'VENDOR', 'VENDORS');

  // Buyable-now floor for the promoted price (> 0, never a phantom $0).
  const priced = listings.filter(
    (l) => l.inStock && l.currentPrice !== null && l.currentPrice > 0,
  );
  const cheapestNow = priced.length
    ? Math.min(...priced.map((l) => l.currentPrice as number))
    : null;
  // Promoted price matches the DataRow's exact figure ($44.99, not a rounded
  // $45) so the centerpiece and the canon row never read as two prices. The
  // chrome RANGE stays rounded — a range is inherently approximate.
  const promotedPrice = cheapestNow !== null ? `$${cheapestNow.toFixed(2)}` : null;

  const rowFields = buildCoralReferenceFields(listings, firstSeenAt);
  const phLink = (
    <p className="text-sm mt-2.5">
      <Link
        href={`/coral/${slug}/price-history`}
        className="text-ink underline underline-offset-2 decoration-1"
      >
        See price history
      </Link>
    </p>
  );

  // Thin history: too few observations to show a range. A single current listing
  // can still render (Listed now.); otherwise just the thin-note gap line.
  if (isThinHistory(envelope, tracks)) {
    const firstSeenChunk = firstSeenAt
      ? `FIRST SEEN ${formatRelativeTime(firstSeenAt, now).toUpperCase()}`
      : 'JUST STARTED TRACKING';
    return (
      <div className="mt-3.5">
        <MarketChrome chunks={[`${vendorN} ${vendorLabel}`, firstSeenChunk]} />
        <p className="text-base leading-relaxed text-ink">
          Not enough history yet to show a range. I&rsquo;ll plot it as this coral lists again.
        </p>
        {cheapestNow !== null && rowFields.length > 0 && (
          <>
            <p className="font-mono text-2xl font-bold text-ink mt-3">
              {promotedPrice}
            </p>
            <div className="mt-1">
              <DataRow fields={rowFields} />
            </div>
          </>
        )}
        {phLink}
      </div>
    );
  }

  // Has a real range. Floor min/max over the window (≥2 envelope days here).
  const floors = envelope.map((e) => e.minPrice);
  const rangeMin = Math.min(...floors);
  const rangeMax = Math.max(...floors);

  // OOS-with-history: range still shows, freshness flips to NOT IN STOCK, NO
  // buyable price renders — gap line in the price-history gap voice.
  if (cheapestNow === null || rowFields.length === 0) {
    const lastSeen = lastSeenAt ? formatRelativeTime(lastSeenAt, now) : null;
    return (
      <div className="mt-3.5">
        <MarketChrome
          chunks={[`${vendorN} ${vendorLabel}`, rangeChunk(rangeMin, rangeMax), 'NOT IN STOCK']}
        />
        <p className="text-base leading-relaxed text-ink">
          No vendor has it listed right now
          {lastSeen ? ` — last seen ${lastSeen}` : ''}. I&rsquo;ll surface it when it lists again.
        </p>
        {phLink}
      </div>
    );
  }

  // Normal: in stock now, with history. Promoted price (centerpiece) + canon
  // 14px DataRow (Cheapest now./Listed now. — Vendor. — First seen.).
  return (
    <div className="mt-3.5">
      <MarketChrome
        chunks={[
          `${vendorN} ${vendorLabel}`,
          rangeChunk(rangeMin, rangeMax),
          `${WINDOW} DAYS`,
        ]}
      />
      <p className="font-mono text-2xl font-bold text-ink">{promotedPrice}</p>
      <div className="mt-1">
        <DataRow fields={rowFields} />
      </div>
      {phLink}
    </div>
  );
}
