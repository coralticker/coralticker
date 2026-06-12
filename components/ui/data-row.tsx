// Semantic <del> on price-drop-new old value + invalidated value — screen
// readers announce "deleted," which matches the brand-canon "was $X" framing
// honestly. A presentational line-through class would not.

import { Fragment } from 'react';
import { AccentDot } from '@/components/ui/accent-dot';
import { RelativeTime } from '@/components/ui/relative-time';

export type DataRowFieldValue =
  | string
  | { kind: 'relative-time'; timestamp: string }
  | { kind: 'price-drop-new'; oldValue: string; newValue: string }
  | { kind: 'vendor-markdown'; oldValue: string; newValue: string }
  | { kind: 'invalidated'; value: string }
  | { kind: 'italic'; value: string };

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
    return (
      <span className="font-mono">
        <del className="font-normal">{value.value}</del>
      </span>
    );
  }
  // Italic per branding-guide §"Content emphasis pattern" — scientific
  // binomial carve-out. <em> over a styling class so screen readers announce
  // emphasis honestly; mono register preserved for data-row consistency.
  if (value.kind === 'italic') {
    return (
      <span className="font-mono">
        <em>{value.value}</em>
      </span>
    );
  }
  if (value.kind === 'price-drop-new') {
    return (
      <span className="font-mono">
        <del className="font-normal">{value.oldValue}</del>{' '}
        <span className="text-forest font-bold">{value.newValue}</span>
      </span>
    );
  }
  // vendor-markdown shares price-drop-new's DOM. Explicit branch — not a
  // fall-through — so future canon-divergence is a one-line edit.
  if (value.kind === 'vendor-markdown') {
    return (
      <span className="font-mono">
        <del className="font-normal">{value.oldValue}</del>{' '}
        <span className="text-forest font-bold">{value.newValue}</span>
      </span>
    );
  }
  // Exhaustiveness check — `_exhaustive: never` fails typecheck if a new
  // DataRowFieldValue kind lands without a branch here, forcing explicit
  // handling. Mirrors formatValue() in lib/format/data-row.ts.
  const _exhaustive: never = value;
  throw new Error(`RenderValue: unhandled value kind ${JSON.stringify(_exhaustive)}`);
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
