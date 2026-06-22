// Pure NamedCoralRow -> NamedCoral mapper, factored out of getNamedCoralBySlug
// so the passthrough contract is unit-testable. named-corals.ts pulls in react,
// next/cache, and getNeonSql (which reads NEON_DATABASE_URL at import) behind
// '@/' runtime aliases — none of which the bare `node --test
// --experimental-strip-types` runner can load (the same wall search.ts hit).
// This module has zero RUNTIME imports (the NamedCoral type import is erased by
// strip-types), so the test loads it standalone.
//
// Contract: every row field flows through unchanged; description is always
// coerced to null — hosted named_corals has no description column, so the
// description-<p> branch on /coral/[slug] always skips. lore + genus (CTK-162)
// ride the spread like every other row field; null is a valid value for both.
//
// The row param is `Omit<NamedCoral, 'description'>` because NamedCoralRow is
// structurally exactly NamedCoral minus description — typing it off the exported
// interface avoids exporting the internal row type just for this seam.

import type { NamedCoral } from './named-corals.ts';

export function mapNamedCoralRow(
  row: Omit<NamedCoral, 'description'>,
): NamedCoral {
  return { ...row, description: null };
}
