import type { Metadata } from 'next';

// Page-level indexability decision for /coral/[slug], read in generateMetadata.
//
// A never-listed coral (lore-only, no vendor listing ever) renders only its
// one-line lore (CTK-185(a)) — genuinely thin content that would dilute the
// domain if indexed, so it gets `index: false`. `follow: true` so the in-body
// crawlable links (Featured-in guides, the /corals index) still pass equity.
//
// An ever-listed coral is non-thin even when OOS today — lore beat PLUS a real
// availability/price ladder (current or historical) — so it stays indexable:
// this returns undefined and generateMetadata omits the robots key, letting Next
// default to index,follow.
//
// has_ever_listed is the SAME predicate getIndexableCoralSlugs uses for sitemap
// inclusion (see lib/queries/named-corals.ts) — sitemap presence and robots
// indexability are one predicate read from two surfaces. Keep them in lockstep.
export function coralPageRobots(
  hasEverListed: boolean,
): Metadata['robots'] | undefined {
  return hasEverListed ? undefined : { index: false, follow: true };
}
