// Wording is hardcoded per `kind`; no text prop. Suppression logic lives at
// the consumer (e.g., <ListingCard>), not at the primitive.

export type CaveatLabelKind = 'match-name-based';
// Phase 4 extends:
//   | 'lineage-confirmed' | 'name-matched-unverified'

interface CaveatLabelProps {
  kind: CaveatLabelKind;
}

const COPY: Record<CaveatLabelKind, string> = {
  'match-name-based': 'Match: name-based',
};

export function CaveatLabel({ kind }: CaveatLabelProps) {
  return <span className="text-sm">{COPY[kind]}</span>;
}
