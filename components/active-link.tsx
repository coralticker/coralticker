// <ActiveLink> — client leaf for <SiteNav> active-route styling.
//
// The only client behavior in the nav: usePathname() to compute active
// state. Extracted so <SiteNav> can be a Server Component — usePathname()
// needs client JS, but only the link active-state does, so the rest of the
// nav no longer pays the whole-nav 'use client' bundle cost.
//
// Match policy: active when pathname === href OR any matchPrefixes entry is
// a prefix of pathname. matchPrefixes is a DISTINCT stem from href, not an
// href-prefix toggle — VENDORS href is /vendors but its detail stem is
// /vendor/, so an href-prefix match would never fire. CORALS href is
// /corals with stem /coral/. Pass the stem explicitly per link.

'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

// linkClass is also consumed by the wordmark in the Server-Component shell
// (hover-only, brand-anchor exempt from active state) — exported for reuse.
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
