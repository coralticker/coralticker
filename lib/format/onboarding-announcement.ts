// CTK-214 — the "now tracking" new-vendor onboarding announcement.
//
// Bare-node-safe leaf (no next/* or @/) — imported by the email digest
// (lib/email/digest.ts) AND the standalone Discord cron (scripts/discord-digest.ts),
// both of which strip-types under plain `node --experimental-strip-types`. Same
// constraint + rationale as lib/format/data-row.ts (memory project_bare_node_import_graph).
// The /new strip (a Next RSC) imports it too.
//
// Copy is canon (branding-guide.md §"Short-copy assets" — "now tracking"); this
// leaf owns the canonical STRINGS + the per-tier classification so the three
// render surfaces can't drift. Each channel applies its own styling (HTML
// <strong>, Discord **bold**, React JSX) on top; the literal words + the
// per-tier shape live here once.
//
// HONEST-FRAMING INVARIANT (load-bearing): `n` is ALWAYS the browseable in-stock
// catalog size (the count the Browse link lands on), explicitly NOT "new
// arrivals." Lose that distinction and the announcement re-introduces the exact
// cold-start lie CTK-198/CTK-213 suppress.

export interface OnboardingVendor {
  vendorSlug: string;
  displayName: string;
  // Browseable in-stock catalog size (honest-framing count). NOT "new arrivals".
  n: number;
}

// Tier thresholds (branding-guide §"now tracking" Lifecycle):
//   1 vendor      -> single   ("Now tracking." / "{V} — {N} pieces")
//   2-4 vendors   -> batched  ("Now tracking." / "{K} new vendors:" / per-row)
//   >=5 vendors   -> collapse ("Now tracking {K} new vendors:" / comma names)
// The collapse form drops per-vendor counts ENTIRELY (no bare number -> no
// arrivals misread), so a vendor wave can't dominate the digest.
export const COLLAPSE_THRESHOLD = 5;

export type OnboardingBlock =
  | { tier: 'none' }
  | { tier: 'single'; vendor: OnboardingVendor }
  | { tier: 'batched'; count: number; vendors: OnboardingVendor[] }
  | { tier: 'collapse'; count: number; vendors: OnboardingVendor[] };

export function classifyOnboarding(vendors: OnboardingVendor[]): OnboardingBlock {
  if (vendors.length === 0) return { tier: 'none' };
  if (vendors.length === 1) return { tier: 'single', vendor: vendors[0]! };
  if (vendors.length < COLLAPSE_THRESHOLD) {
    return { tier: 'batched', count: vendors.length, vendors };
  }
  return { tier: 'collapse', count: vendors.length, vendors };
}

// ---- Canonical strings — the ONLY place the words live -------------------

// Single + batched lead. Period is canon (declarative, present-tense; carries
// newness with no date to go stale per the recency-free lock).
export const NOW_TRACKING = 'Now tracking.';

// `pieces` is baked in here so the batched form repeats the noun per row BY
// CONSTRUCTION — dropping it (RUTR) re-opens the catalog-size-vs-new-arrivals
// misread. `name` arrives pre-escaped for the channel (HTML-escaped /
// Discord-md-escaped); the /new strip passes the raw displayName (React escapes).
// The em-dash + " pieces" noun are identical across channels.
export function vendorPieces(name: string, n: number): string {
  return `${name} — ${n} pieces`;
}

// Batched sub-headline under "Now tracking." (2-4 onboards).
export function batchedHeadline(count: number): string {
  return `${count} new vendors:`;
}

// Collapse lead (>=5 onboards) — folds "Now tracking" + the count into one line,
// no separate per-vendor rows follow (comma-list only, no counts).
export function collapseHeadline(count: number): string {
  return `Now tracking ${count} new vendors:`;
}
