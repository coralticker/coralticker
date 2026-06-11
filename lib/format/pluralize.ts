// lib/format/pluralize.ts
//
// Count-driven noun selection with an EXPLICIT plural form — not suffix-based.
// Chrome count-nouns include multi-word heads (`PRICE DROP` → `PRICE DROPS`,
// not `PRICE DROPSS` / `PRICE DROP S`) and irregulars a naive +"s" would
// mangle, so the caller passes both forms. Singular renders only at exactly 1;
// 0 and N>1 both take the plural (`0 CORALS`, `2 CORALS`).
//
// Returns the noun only — the caller owns the count + spacing
// (`${n} ${pluralize(n, 'CORAL', 'CORALS')}`), matching the in-place ternaries
// it replaces so the eyebrow-chunk composition is unchanged.
export function pluralize(count: number, singular: string, plural: string): string {
  return count === 1 ? singular : plural;
}
