// Site-nav search input. Plain GET form submitting to /search?q= — zero client
// JS; Enter submits the single-input form natively. Mounts in <SiteNav>
// bare-gap-separated between the link run and SIGNUP: a control is the third
// bare-gap non-peer species (wordmark = brand-anchor, SIGNUP = commit-CTA,
// input = control); the forest mid-dot run binds navigating IA peers ONLY.
//
// NOT prefilled with the current q: prefill needs useSearchParams in sitewide
// client chrome + its Suspense-boundary drag; the locked H1 `Results for "{q}".`
// owns the query echo.
//
// Placeholder SEARCH is written literally uppercase — CSS text-transform
// doesn't reliably reach placeholders. aria-label on the input since no visible
// label survives the chrome lock.

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
