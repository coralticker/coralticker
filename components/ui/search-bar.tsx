// §CTK-058 <SearchBar> — site-nav search input
//
// Plain GET form submitting to /search?q= (D-058-3) — zero client JS; Enter
// submits the single-input form natively. Mounts in <SiteNav> bare-gap-
// separated between the link run and SIGNUP per the INV-02 round-2 variant A
// lock (branding-guide L286): a control is the third bare-gap non-peer
// species (wordmark = brand-anchor, SIGNUP = commit-CTA, input = control);
// the forest mid-dot run binds navigating IA peers ONLY. Chrome lives on the
// <Input variant="nav-underline"> primitive per the single-point-of-brand-
// enforcement rule (site.md §0.2 #5).
//
// NOT prefilled with the current q (plan component-section, /review-plan
// fold #4): prefill needs useSearchParams in sitewide client chrome + its
// Suspense-boundary drag; the locked H1 `Results for "{q}".` owns the query
// echo. Prefill graduates with v2's client surface.
//
// Placeholder SEARCH is written literally uppercase — CSS text-transform
// doesn't reliably reach placeholders (guide L286). role="search" per the
// plan a11y floor; aria-label on the input since no visible label survives
// the chrome lock.

import { Input } from '@/components/ui/input';

export function SearchBar() {
  return (
    <form action="/search" role="search">
      <Input
        name="q"
        type="search"
        aria-label="Search"
        placeholder="SEARCH"
        variant="nav-underline"
      />
    </form>
  );
}
