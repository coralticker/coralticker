// MDX component map for /guides bodies. Markdown prose maps to the site's
// register (sentence-case content wrapping data-system chrome); the net-new
// authoring components (<CoralEntry>, <CoralReference>, <SocialLinks>) are
// exposed so copy-writer places them inline. No generic-blog chrome (no TOC,
// share-row, byline) is mapped — only what the surface uses.

import type { ReactNode } from 'react';
import Link from 'next/link';
import { SectionHeader } from '@/components/ui/section-header';
import { SocialLinks } from '@/components/ui/social-links';
import { CoralEntry } from './_components/coral-entry';
import { CoralReference } from './_components/coral-reference';

// Internal links use <Link> (client nav + crawlable); external open in a new tab.
// Both render the plain neutral-underline content link (§Color system — no forest).
function MdxLink({ href = '', children }: { href?: string; children?: ReactNode }) {
  const linkClass = 'text-ink underline underline-offset-2 decoration-1';
  if (href.startsWith('/')) {
    return (
      <Link href={href} className={linkClass}>
        {children}
      </Link>
    );
  }
  return (
    <a href={href} className={linkClass} target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  );
}

export const mdxComponents = {
  h2: ({ children }: { children?: ReactNode }) => (
    <SectionHeader className="mt-11">{children}</SectionHeader>
  ),
  p: ({ children }: { children?: ReactNode }) => (
    <p className="text-base leading-relaxed text-ink mb-4">{children}</p>
  ),
  a: MdxLink,
  CoralEntry,
  CoralReference,
  SocialLinks,
};
