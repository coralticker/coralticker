// Class-aware type-label resolver per branding-guide.md §"Type label casing
// (data-field register)". Three classes, three casings:
//   - acronyms (SPS, LPS)              → ALL-CAPS
//   - category words (Zoa, Chalice, …) → Title Case
//   - scientific binomials (Acropora tenuis) → italic (per §"Content emphasis
//     pattern" — italic carve-out is exactly "editorial scientific binomials")
//
// Blanket .toUpperCase() / .toLowerCase() is the failure mode this guards
// against. DB values are display-form already (matching seed-curation
// convention); the resolver maps raw → display + italic flag without losing
// information.
//
// Unknown values fall through to a raw-passthrough branch per the drift-add
// discipline in branding-guide.md §"Drift-add discipline for originator values"
// (same pattern applies here — new type values get a class assignment when
// first seen).

export interface TypeLabelRender {
  display: string;
  italic: boolean;
}

const ACRONYMS = new Set<string>(['SPS', 'LPS']);

const CATEGORY_WORDS = new Set<string>([
  'Zoa',
  'Chalice',
  'Clam',
  'Anemone',
  'Softie',
  'Mushroom',
]);

// Scientific binomial = exactly two whitespace-separated tokens, first
// Capitalized, second all-lowercase (Genus species). Excludes hybrid
// shorthand like "Acropora sp." (period-terminated species token) — that's
// not a formal binomial.
function isBinomial(raw: string): boolean {
  const parts = raw.trim().split(/\s+/);
  if (parts.length !== 2) return false;
  const [genus, species] = parts as [string, string];
  return /^[A-Z][a-z]+$/.test(genus) && /^[a-z]+$/.test(species);
}

export function formatTypeLabel(raw: string): TypeLabelRender {
  const trimmed = raw.trim();
  // Acronym check first — case-insensitive membership against the canonical
  // upper-case form, so an upstream lowercase drift doesn't bypass the class.
  if (ACRONYMS.has(trimmed.toUpperCase())) {
    return { display: trimmed.toUpperCase(), italic: false };
  }
  if (isBinomial(trimmed)) {
    return { display: trimmed, italic: true };
  }
  // Category-word check against canonical Title-Case form for the same
  // case-insensitive drift-tolerance reason.
  for (const word of CATEGORY_WORDS) {
    if (word.toLowerCase() === trimmed.toLowerCase()) {
      return { display: word, italic: false };
    }
  }
  // Unknown value — passthrough raw. Drift-add at first-exercise per
  // branding-guide.md membership-list maintenance rule.
  return { display: trimmed, italic: false };
}
