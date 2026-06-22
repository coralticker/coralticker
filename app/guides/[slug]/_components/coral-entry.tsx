// CTK-162 D-4 Variant B — the two-beat /guides coral entry. Thin layout wrapper:
// the hairline-separated entry container + beat 1 (bold coral-name link → lore),
// then <CoralReference> for beat 2 (the live market line). NOT a boxed card, no
// thumbnail — bare hairline rows keep the surface inside the site's data system
// (the anti-content-farm discipline, INV-02).
//
// Authoring (MDX): <CoralEntry slug="jf-homewrecker" /> — no children. The lore
// sentence (beat 1's hook) defaults to the coral's editorial named_corals.lore
// column (ratified verbatim, CTK-162 decision #85), so copy-writer edits lore in
// one place (the DB) and it renders on both /guides and /coral/[slug]. MDX MAY
// still pass children to override the DB default for a guide-specific framing:
// <CoralEntry slug="…">a one-off line</CoralEntry>. The name-link text resolves
// from canonical_name (not hand-typed) so the name + /coral URL can't drift from
// the catalog. Top hairline per entry; the trailing <SectionHeader> closes the
// list.

import type { ReactNode } from 'react';
import Link from 'next/link';
import { getNamedCoralBySlug } from '@/lib/queries/named-corals';
import { CoralReference } from './coral-reference';

export async function CoralEntry({
  slug,
  children,
}: {
  slug: string;
  children?: ReactNode;
}) {
  const coral = await getNamedCoralBySlug(slug);
  // MDX children override the DB default; with none, fall back to the coral's lore
  // column. Both null is still a valid entry — the market line below carries it,
  // so render no lore beat rather than an empty gap.
  const lore = children ?? coral?.lore ?? null;

  return (
    <div className="py-6 border-t border-line">
      <h3 className="text-lg font-bold leading-tight m-0">
        {coral ? (
          <Link
            href={`/coral/${slug}`}
            className="text-ink underline underline-offset-2 decoration-1"
          >
            {coral.canonical_name}
          </Link>
        ) : (
          <span className="text-ink">{slug}</span>
        )}
      </h3>
      {/* The [&>p]:m-0 reset is for the children case — MDX wraps authored lore in
          a <p> (the components.p map); the DB-lore case is a plain string, so the
          reset is a harmless no-op there. */}
      {lore && (
        <div className="text-base leading-snug text-ink mt-1 [&>p]:m-0 [&>p]:leading-snug">
          {lore}
        </div>
      )}
      <CoralReference slug={slug} />
    </div>
  );
}
