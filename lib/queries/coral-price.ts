// Per-coral price time-series for the /coral/[slug]/price-history template
// (CTK-162 scope b, D-1 child route). Thin TS wrappers over the two STABLE
// Postgres functions in migration 0049 — the function is the shared contract,
// this is the per-consumer language wrapper (CTK-161 design-once; no re-derived
// ranking, no Python port).
//
// INV-01 is N/A here: both shapes are time-series POINTS, not formatDataRow()
// listing rows. The price-history page's vendor-listing list carries INV-01
// separately at its own slice.
//
// Type coercion at the @neondatabase/serverless boundary:
//   * numeric + bigint come back as STRINGS (see listings.ts rpc mappers) ->
//     Number() (price, minPrice, listingId, vendorId).
//   * timestamptz comes back as a JS Date (an absolute instant) -> .toISOString()
//     for a lossless ISO string (observed_at).
//   * a bare `date` would come back as a local-midnight JS Date that tz-shifts to
//     the wrong calendar day, so get_coral_price_envelope returns `day` as TEXT
//     (YYYY-MM-DD) from SQL instead — it arrives here already a clean string.

import { unstable_cache } from 'next/cache';
import { getNeonSql } from '@/lib/db/neon';

// ── get_coral_price_history — per-listing step series ──────────────────────

export interface CoralPricePoint {
  listingId: number;
  vendorId: number;
  vendorSlug: string;
  observedAt: string; // ISO timestamptz
  price: number | null; // numeric; null = price-unknown observation
  inStock: boolean; // travels per point for OOS-gap rendering
}

interface RpcPricePointRow {
  listing_id: number | string;
  vendor_id: number | string;
  vendor_slug: string;
  // timestamptz -> JS Date at runtime; string only if a future change casts it.
  observed_at: Date | string;
  price: number | string | null;
  in_stock: boolean;
}

// One row per price_history observation, keyed per listing (two listings of the
// same coral from one vendor stay separate honest tracks). windowDays null =
// full history; else the trailing N-day window. Ordered (listing_id,
// observed_at) by the function — the render walks each listing's points in time
// order to draw its step line.
export async function getCoralPriceHistory(
  namedCoralId: number,
  windowDays: number | null = null,
): Promise<CoralPricePoint[]> {
  return unstable_cache(
    async () => {
      const sql = getNeonSql();
      const rows = (await sql`
        SELECT listing_id, vendor_id, vendor_slug, observed_at, price, in_stock
        FROM get_coral_price_history(${namedCoralId}::int, ${windowDays}::int)
      `) as unknown as RpcPricePointRow[];

      return rows.map((r) => ({
        listingId: Number(r.listing_id),
        vendorId: Number(r.vendor_id),
        vendorSlug: r.vendor_slug,
        observedAt:
          r.observed_at instanceof Date ? r.observed_at.toISOString() : r.observed_at,
        price: r.price != null ? Number(r.price) : null,
        inStock: r.in_stock,
      }));
    },
    // Bump the prefix when the row shape changes — the Data Cache persists
    // across deploys, so stale entries keep serving the old shape up to 300s.
    ['getCoralPriceHistoryV1', String(namedCoralId), String(windowDays ?? '_')],
    {
      revalidate: 300,
      tags: [`coral-${namedCoralId}-price-history`],
    },
  )();
}

// ── get_coral_price_envelope — cross-vendor daily-min floor (LOCF) ──────────

export interface CoralEnvelopePoint {
  day: string; // YYYY-MM-DD
  minPrice: number; // cheapest in-stock price across listings that day
}

interface RpcEnvelopeRow {
  // `day` is TEXT from SQL (YYYY-MM-DD) — see the boundary note up top; arrives
  // as a clean string, no Date round trip.
  day: string;
  min_price: number | string;
}

// The headline line: cheapest in-stock price across the coral's listings per
// calendar day, with LOCF over the sparse change-only price_history. Days where
// every listing is OOS/null are absent (honest gap, not a zero) — the function
// emits no row, so a gap in the returned days IS a real all-OOS gap the render
// can break the line across. windowDays bounds the series start only; the LOCF
// still reaches before the window so the opening level is carried in.
export async function getCoralPriceEnvelope(
  namedCoralId: number,
  windowDays: number | null = null,
): Promise<CoralEnvelopePoint[]> {
  return unstable_cache(
    async () => {
      const sql = getNeonSql();
      const rows = (await sql`
        SELECT day, min_price
        FROM get_coral_price_envelope(${namedCoralId}::int, ${windowDays}::int)
      `) as unknown as RpcEnvelopeRow[];

      return rows.map((r) => ({
        day: r.day,
        minPrice: Number(r.min_price),
      }));
    },
    ['getCoralPriceEnvelopeV1', String(namedCoralId), String(windowDays ?? '_')],
    {
      revalidate: 300,
      tags: [`coral-${namedCoralId}-price-envelope`],
    },
  )();
}
