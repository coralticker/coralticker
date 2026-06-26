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

// "Part A — …" / "Part B — …" are act dividers, not ordinary sections. The copy
// is locked as `## Part X — …` (can't swap to a custom component), so detect the
// leading "Part <letter> —" on the h2 text and render the heavier divider variant.
// leadingText guards the array case (inline formatting would make children an
// array); these headers are plain text today, but the regex must read a string.
function leadingText(children: ReactNode): string {
  if (typeof children === 'string') return children;
  if (Array.isArray(children) && typeof children[0] === 'string') return children[0];
  return '';
}
const PART_DIVIDER_RE = /^Part [A-Z]\s+—/;

// Heavier than SectionHeader (small, gray bottom-rule): larger bold text under a
// near-black top rule, with a wide gap above so the two acts read as acts on scan.
function PartDivider({ children }: { children?: ReactNode }) {
  return (
    <h2 className="mt-16 mb-2 pt-6 border-t border-ink text-xl md:text-2xl font-bold text-ink">
      {children}
    </h2>
  );
}

export const mdxComponents = {
  h2: ({ children }: { children?: ReactNode }) =>
    PART_DIVIDER_RE.test(leadingText(children)) ? (
      <PartDivider>{children}</PartDivider>
    ) : (
      // Guide prose overrides SectionHeader's baked text-sm (a data-system size,
      // smaller than body) up to a real prose header — text-lg md:text-xl wins
      // over text-sm by Tailwind's size ordering. Keeps the primitive's bold +
      // 1px under-rule (the brand's section-divider language, §"Section
      // transitions"); only the size was wrong. /brand-manager-ratified 2026-06-26.
      <SectionHeader className="mt-11 text-lg md:text-xl">{children}</SectionHeader>
    ),
  p: ({ children }: { children?: ReactNode }) => (
    <p className="text-base leading-relaxed text-ink mb-4">{children}</p>
  ),
  a: MdxLink,
  // Lists: Tailwind preflight zeroes markers + padding, so restore them here.
  // Markers hang in the pl-6 indent (list-outside) so multi-line items align.
  // Tight list items aren't <p>-wrapped, so the text rhythm lives on <li>.
  // NOTE: <SocialLinks> renders its own <ul> from inside the component (not via
  // this map), so it's unaffected by the ul styling below.
  ol: ({ children }: { children?: ReactNode }) => (
    <ol className="list-decimal pl-6 mb-4 space-y-2 marker:text-ink">{children}</ol>
  ),
  // Em-dash marker (not a default disc) — echoes the brand's data-row separator
  // so the list reads intentional. Arbitrary list-style-type string ('— ', the _
  // is Tailwind's space); near-black marker. (Ordered list stays decimal.)
  ul: ({ children }: { children?: ReactNode }) => (
    <ul className="list-['—_'] pl-6 mb-4 space-y-2 marker:text-ink">{children}</ul>
  ),
  li: ({ children }: { children?: ReactNode }) => (
    <li className="text-base leading-relaxed text-ink pl-1">{children}</li>
  ),
  // GFM comparison table (Part A). Understated editorial table, not a data grid:
  // mono-uppercase header row in the data-system register, hairline border-line
  // rules, left-aligned, cells top-aligned so wrapped multi-line cells read.
  table: ({ children }: { children?: ReactNode }) => (
    <table className="w-full my-6 text-sm border-collapse">{children}</table>
  ),
  th: ({ children }: { children?: ReactNode }) => (
    <th className="text-left align-bottom font-mono text-xs uppercase tracking-[0.08em] font-bold text-ink pb-2 pr-4 border-b border-line">
      {children}
    </th>
  ),
  td: ({ children }: { children?: ReactNode }) => (
    <td className="align-top py-2.5 pr-4 border-b border-line text-ink leading-snug">
      {children}
    </td>
  ),
  CoralEntry,
  // Direct MDX <CoralReference> binds (guide #2 §4/§5) sit between prose
  // paragraphs, so give the block bottom breathing room before prose resumes
  // (mb-4 = the body paragraph rhythm). Scoped here on purpose: CoralEntry uses
  // CoralReference directly (not via this map), so guide #1's wrapped entries —
  // which already get the entry container's py-6 — are unaffected.
  CoralReference: (props: { slug: string }) => (
    <div className="mb-4">
      <CoralReference {...props} />
    </div>
  ),
  SocialLinks,
};
