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
    return (
      <span className="font-mono">
        <del className="font-normal">{value.value}</del>
      </span>
    );
  }
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
