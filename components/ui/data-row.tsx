// §3.2 <DataRow>
// Renders the em-dash data row per branding-guide.md §"Em-dash data row format".
//   **Field.** value — **Field.** value — **Field.** value
// Bold Plex Sans labels, forest em-dash separators, Plex Mono values.
// Value-kinds: string | { kind: 'relative-time', timestamp }
//            | { kind: 'price-drop-new', oldValue, newValue }
//            | { kind: 'invalidated', value }
// per site.md Decision H + CTK-070 OOS state-marker extension.
//
// price-drop-new uses semantic <del> for the strikethrough old value per a11y
// floor (§5.2) — Q2 engineer-call at Session 4 open (site.md §4.3 + Q-040-2
// directive). Screen readers announce "deleted" on encountering <del>, which
// matches the brand-canon "was $X" lead-sentence framing more honestly than
// a presentational line-through class.
//
// invalidated (CTK-070) services the OOS state-marker per branding-guide.md
// §"State markers" — **Out-of-stock state-marker.** paragraph (canon fold
// landed 2026-05-22). L197 generalized strikethrough from "value replaced"
// → "value-replaced or value-invalidated"; same primitive shape (regular
// weight + semantic <del> + near-black) services both kinds. No forest on
// invalidated — preserves the 5-job accent lock at L165-173.
//
// Stays RSC; <RelativeTime> client leaf renders inside when value.kind === 'relative-time'.

import { Fragment } from 'react';
import { AccentDot } from '@/components/ui/accent-dot';
import { RelativeTime } from '@/components/ui/relative-time';

export type DataRowFieldValue =
  | string
  | { kind: 'relative-time'; timestamp: string }
  | { kind: 'price-drop-new'; oldValue: string; newValue: string }
  | { kind: 'invalidated'; value: string };

export interface DataRowField {
  label: string;
  value: DataRowFieldValue;
}

interface DataRowProps {
  fields: DataRowField[];
  matchIndicator?: boolean;
}

function RenderValue({ value }: { value: DataRowFieldValue }) {
  if (typeof value === 'string') {
    return <span className="font-mono">{value}</span>;
  }
  if (value.kind === 'relative-time') {
    return (
      <span className="font-mono">
        <RelativeTime timestamp={value.timestamp} />
      </span>
    );
  }
  if (value.kind === 'invalidated') {
    // CTK-070: OOS state-marker per branding-guide.md §"State markers" L197
    // generalized strikethrough — regular weight, near-black, semantic <del>.
    // No forest accent (preserves 5-job lock); brand-canon names this as "the
    // field is invalidated rather than replaced" — same primitive shape as
    // price-drop-new's old-value <del> minus the bold-forest new-value pair.
    return (
      <span className="font-mono">
        <del className="font-normal">{value.value}</del>
      </span>
    );
  }
  // price-drop-new: regular-weight strikethrough old (near-black) + bold forest new.
  // Semantic <del> for the old value — a11y register matches brand-canon
  // "was $X, now $Y" framing (screen readers announce "deleted" on <del>).
  return (
    <span className="font-mono">
      <del className="font-normal">{value.oldValue}</del>{' '}
      <span className="text-forest font-bold">{value.newValue}</span>
    </span>
  );
}

export function DataRow({ fields, matchIndicator }: DataRowProps) {
  return (
    <div className="text-sm leading-relaxed">
      {matchIndicator ? (
        <>
          <AccentDot variant="wishlist-match" aria-label="Wishlist match" />{' '}
        </>
      ) : null}
      {fields.map((field, i) => (
        <Fragment key={i}>
          {i > 0 ? <span aria-hidden="true" className="text-forest"> — </span> : null}
          <strong className="font-bold">{field.label}.</strong>{' '}
          <RenderValue value={field.value} />
        </Fragment>
      ))}
    </div>
  );
}
