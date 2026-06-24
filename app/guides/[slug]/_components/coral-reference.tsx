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
import { distinctInStockVendorCount } from '@/lib/format/vendor-count';
import { marketLineState } from '@/lib/format/market-line-state';
import { PRICE_ON_REQUEST } from '@/lib/format/listing-price';

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

  // Current-availability count = distinct IN-STOCK vendors (CTK-187), shared with
  // the /coral/[slug] eyebrow via distinctInStockVendorCount so the two surfaces
  // can't drift on the in-stock rule (the divergence the old vendorN cascade —
  // tracks.length || availabilityVendors || inWindowVendorCount — invited; its
  // all-OOS fallback to the carrier count was exactly the Tier-1B "1 VENDOR"
  // defect). getCoralAvailability(coral.id) here is in-stock-only, so this counts
  // the rendered vendors; the helper's inStock filter is a belt-and-suspenders
  // guard. inWindowVendorCount (stock-unfiltered, 7-day recency window) survives
  // ONLY as the all-OOS vs. truly-not-listed fork — an all-OOS coral has 0
  // in-stock vendors but >0 in-window carriers; a never-listed/stale coral has 0
  // of both.
  //
  // The isAllOOS FORMULA differs from the parent /coral/[slug] on purpose — do
  // NOT "align" them: the coral page can carry OOS rows in its listings array via
  // ?include-oos=1, so it derives all-OOS from the rendered set + an in-window
  // count; this guide surface is in-stock-only (no toggle), so 0 in-stock vendors
  // + >0 in-window carriers is the whole signal. Same three states, different
  // inputs.
  const inStockVendorCount = distinctInStockVendorCount(listings);
  const isAllOOS = inStockVendorCount === 0 && inWindowVendorCount > 0;
  const vendorChunk = `${inStockVendorCount} ${pluralize(inStockVendorCount, 'VENDOR', 'VENDORS')}`;

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

  // Current-availability state drives the whole market line (CTK-187 /code-review
  // #1; wording /brand-manager-LOCKED 2026-06-24). Classify ONCE on the shared
  // helper, then render. The three no-price states (not-listed / all-oos /
  // price-on-request) render the SAME thin or non-thin — thin only changes the
  // `available` render below (range vs. thin-note). All three no-price states
  // drop the range chunk: a range's home is the price-history surface (labeled
  // {W}-DAY HISTORY); an unlabeled range here reads as an actionable price.
  const hasBuyablePrice = cheapestNow !== null && rowFields.length > 0;
  const state = marketLineState({ inStockVendorCount, isAllOOS, hasBuyablePrice });

  // not-listed: truly absent (0 in-stock vendors, 0 in-window carriers). Matches
  // the parent /coral/[slug] NOT LISTED arm (branding-guide §"/guides/[slug]"
  // state 3). Own body — the carriers genuinely aren't there.
  if (state === 'not-listed') {
    const lastSeen = lastSeenAt ? formatRelativeTime(lastSeenAt, now) : null;
    return (
      <div className="mt-3.5">
        <MarketChrome chunks={['NOT CURRENTLY LISTED']} />
        <p className="text-base leading-relaxed text-ink">
          No vendor has it listed right now
          {lastSeen ? ` — last seen ${lastSeen}` : ''}. I&rsquo;ll surface it when it lists again.
        </p>
        {phLink}
      </div>
    );
  }

  // all-OOS: in-window carriers exist, all out of stock. Bare state word, thin
  // AND non-thin unified (reverses the earlier [FIRST SEEN, ALL OUT OF STOCK]
  // thin choice). Own body — the listings exist, they're just out of stock.
  if (state === 'all-oos') {
    return (
      <div className="mt-3.5">
        <MarketChrome chunks={['ALL OUT OF STOCK']} />
        <p className="text-base leading-relaxed text-ink">
          Every listing&rsquo;s out of stock right now. I&rsquo;ll flag it when it&rsquo;s back in stock.
        </p>
        {phLink}
      </div>
    );
  }

  // price-on-request: in stock, no posted price (non-auction cut-to-order /
  // event-drop, current_price null) — MUST NOT read as out of stock. Body links
  // "the listing" to the single in-stock listing when there's exactly one; the
  // no-link fallback reuses the shared PRICE_ON_REQUEST token (don't re-mint).
  if (state === 'price-on-request') {
    const inStockListings = listings.filter((l) => l.inStock);
    const single = inStockListings.length === 1 ? inStockListings[0]! : null;
    return (
      <div className="mt-3.5">
        <MarketChrome chunks={[vendorChunk, PRICE_ON_REQUEST]} />
        <p className="text-base leading-relaxed text-ink">
          {single ? (
            <>
              In stock now &mdash;{' '}
              <a
                href={single.productUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="text-ink underline underline-offset-2 decoration-1"
              >
                check the listing
              </a>{' '}
              for the price.
            </>
          ) : (
            <>In stock now &mdash; {PRICE_ON_REQUEST}.</>
          )}
        </p>
        {phLink}
      </div>
    );
  }

  // available (the only state left): a buyable price exists. Thin history →
  // thin-note + promoted price; otherwise the normal market line with the range.
  if (isThinHistory(envelope, tracks)) {
    const firstSeenChunk = firstSeenAt
      ? `FIRST SEEN ${formatRelativeTime(firstSeenAt, now).toUpperCase()}`
      : 'JUST STARTED TRACKING';
    return (
      <div className="mt-3.5">
        <MarketChrome chunks={[vendorChunk, firstSeenChunk]} />
        <p className="text-base leading-relaxed text-ink">
          Not enough history yet to show a range. I&rsquo;ll plot it as this coral lists again.
        </p>
        <p className="font-mono text-2xl font-bold text-ink mt-3">{promotedPrice}</p>
        <div className="mt-1">
          <DataRow fields={rowFields} />
        </div>
        {phLink}
      </div>
    );
  }

  // Has a real range. Floor min/max over the window (≥2 envelope days here).
  const floors = envelope.map((e) => e.minPrice);
  const rangeMin = Math.min(...floors);
  const rangeMax = Math.max(...floors);

  // Normal: in stock now, with a real range. Promoted price (centerpiece) + canon
  // 14px DataRow (Cheapest now./Listed now. — Vendor. — First seen.). The
  // rangeMin/Max compute just above is the sole remaining consumer of the
  // envelope floors (/code-review #4 simplification — the no-price states above
  // dropped the range chunk).
  return (
    <div className="mt-3.5">
      <MarketChrome
        chunks={[
          vendorChunk,
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
