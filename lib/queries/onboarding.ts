// CTK-214 — the /new "now tracking" strip's read query. SEPARATE from
// getRecentArrivals (lib/queries/listings.ts) on purpose: the strip's {N} is the
// browseable in-stock catalog size and MUST NOT leak into the page eyebrow's
// "N ARRIVALS" count (honest-framing invariant). Two queries, two counts.

import { unstable_cache } from 'next/cache';
import { getNeonSql } from '@/lib/db/neon';

// Hard cap from onboarded_at (branding-guide §"now tracking" Lifecycle): a vendor
// that stays silent this long stops riding the strip even WITHOUT an organic drop,
// so "Now tracking" never lingers as stale chrome.
export const ONBOARDING_STRIP_MAX_DAYS = 7;
const MS_PER_DAY = 86_400_000;

export interface OnboardingStripVendor {
  vendorSlug: string;
  displayName: string;
  n: number;
  // = LEAST(email_at, discord_at) — the EARLIEST announce on any channel
  // (backend-locked, migration 0069). The strip appears synced to first announce;
  // the 7-day cap below counts from here.
  onboardedAt: string;
}

interface StripRow {
  vendor_slug: string;
  display_name: string;
  n: number;
  onboarded_at: string;
}

// get_onboarding_strip_state() already does the BINARY drops backend-side:
// announced on >=1 channel, NOT yet organically retired (first_organic_drop_at
// IS NULL), and n > 0 (no dead "0 pieces" click). The frontend owns ONLY the
// time cap (a policy knob), applied per-request below.
async function queryOnboardingStrip(): Promise<OnboardingStripVendor[]> {
  const sql = getNeonSql();
  const rows = (await sql`
    SELECT vendor_slug, display_name, n, onboarded_at
    FROM get_onboarding_strip_state()
  `) as unknown as StripRow[];
  return rows.map((r) => ({
    vendorSlug: r.vendor_slug,
    displayName: r.display_name,
    n: r.n,
    onboardedAt: r.onboarded_at,
  }));
}

export async function getOnboardingStrip(
  now: Date = new Date(),
): Promise<OnboardingStripVendor[]> {
  // Versioned key (convention: getRecentArrivalsV7 etc.) — the Data Cache persists
  // across deploys, so a future widening of the selected/returned shape must bump
  // -v1 to force a clean re-query rather than deserialize new fields as undefined
  // (memory feedback_unstable_cache_shape_change). The tag stays unversioned so a
  // revalidateTag('onboarding-strip') still targets it across versions.
  const vendors = await unstable_cache(queryOnboardingStrip, ['onboarding-strip-v1'], {
    revalidate: 300,
    tags: ['onboarding-strip'],
  })();
  // 7-day cap applied AFTER the cache read so the boundary is wall-clock accurate,
  // not frozen at cache-fill time. The cached payload is the small fresh-onboard
  // set (a handful of rows); this filter trims the time-expired tail per request.
  const cutoff = now.getTime() - ONBOARDING_STRIP_MAX_DAYS * MS_PER_DAY;
  return vendors.filter((v) => Date.parse(v.onboardedAt) >= cutoff);
}
