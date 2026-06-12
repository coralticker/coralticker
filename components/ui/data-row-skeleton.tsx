// Pulse-bar placeholder color is NEUTRAL GRAY, not forest — pulse is not one
// of forest's 5 jobs (branding-guide §"Color system"). prefers-reduced-motion:
// reduce → static structural skeleton (Tailwind animate-pulse honors the media
// query via app/globals.css block).

import { Fragment } from 'react';
import type { DataRowField } from '@/components/ui/data-row';

interface DataRowSkeletonProps {
  fields: DataRowField[];
}

export function DataRowSkeleton({ fields }: DataRowSkeletonProps) {
  const labelList = fields.map((f) => f.label).join(', ');
  return (
    <div
      role="status"
      aria-busy="true"
      aria-label={`Loading ${labelList}`}
      className="text-sm leading-relaxed"
    >
      {fields.map((field, i) => (
        <Fragment key={i}>
          {i > 0 ? <span className="text-forest"> — </span> : null}
          <strong className="font-bold">{field.label}.</strong>{' '}
          <span
            aria-hidden="true"
            className="inline-block h-4 w-24 align-middle bg-wash rounded-sm animate-pulse"
          />
        </Fragment>
      ))}
    </div>
  );
}
