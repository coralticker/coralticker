// §3.2 <DataRow>
// Renders the em-dash data row per branding-guide.md §"Em-dash data row format".
//   **Field.** value — **Field.** value — **Field.** value
// Bold Plex Sans labels, forest em-dash separators, Plex Mono values.
// Value-kinds: string | { kind: 'relative-time', timestamp } | { kind: 'price-drop-new', oldValue, newValue }
// per site.md Decision H.
//
// price-drop-new uses semantic <del> for the strikethrough old value per a11y
// floor (§5.2) — Q2 engineer-call at Session 4 open (site.md §4.3 + Q-040-2
// directive). Screen readers announce "deleted" on encountering <del>, which
// matches the brand-canon "was $X" lead-sentence framing more honestly than
// a presentational line-through class.
//
// Stays RSC; <RelativeTime> client leaf renders inside when value.kind === 'relative-time'.

import { Fragment } from 'react';
import { AccentDot } from '@/components/ui/accent-dot';
import { RelativeTime } from '@/components/ui/relative-time';

export type DataRowFieldValue =
  | string
  | { kind: 'relative-time'; timestamp: string }
  | { kind: 'price-drop-new'; oldValue: string; newValue: string };

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
