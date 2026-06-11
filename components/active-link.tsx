// <ActiveLink> — client leaf for <SiteNav> active-route styling.
//
// The only client behavior in the nav: usePathname() to compute active
// state. Extracted so <SiteNav> can be a Server Component (CTK-064) —
// wordmark, mid-dot separators, and the GET-form <SearchBar> are pure
// markup and no longer pay the whole-nav 'use client' bundle cost.
//
// Match policy (Jon-confirmed CTK-064: detail pages light their index):
//   active when pathname === href OR any matchPrefixes entry is a prefix
//   of pathname. matchPrefixes is a DISTINCT stem from href, not an
//   href-prefix toggle — VENDORS href is /vendors but its detail stem is
//   /vendor/, so an href-prefix match would never fire. CORALS href is
//   /corals with stem /coral/. Pass the stem explicitly per link.
//
// Q-3 underline treatment (CTK-048 INV-02) lives here: active renders
// activeLinkClass (steady underline) + aria-current="page"; inactive
// renders linkClass (hover/focus underline). usePathname() is available
// during App-Router SSR, so first paint carries correct active state —
// no post-hydration flicker.

'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

// Q-3 (CTK-048 INV-02): active-route underline-offset-[3px] decoration-1;
// inactive surfaces the same underline on hover/focus only. linkClass is
// also consumed by the wordmark in the Server-Component shell (hover-only,
// brand-anchor exempt from active state) — exported for that reuse.
export const linkClass =
  'hover:underline focus-visible:underline underline-offset-[3px] decoration-1';
const activeLinkClass = 'underline underline-offset-[3px] decoration-1';

interface ActiveLinkProps {
  href: string;
  label: string;
  /** Distinct route stems that should also light this link (e.g. ['/vendor']
   *  for VENDORS → /vendor/[slug]). Matched via prefix, separate from href. */
  matchPrefixes?: string[];
  /** Extra classes that always apply, prepended to link/active class (e.g.
   *  SIGNUP's font run, which the middle-cluster <ul> supplies for its own). */
  className?: string;
}

export function ActiveLink({ href, label, matchPrefixes, className }: ActiveLinkProps) {
  const pathname = usePathname();
  const isActive =
    pathname === href ||
    (matchPrefixes?.some((prefix) => pathname.startsWith(prefix)) ?? false);

  const base = className ? `${className} ` : '';

  return (
    <Link
      href={href}
      aria-current={isActive ? 'page' : undefined}
      className={`${base}${isActive ? activeLinkClass : linkClass}`}
    >
      {label}
    </Link>
  );
}
