// §3.2.1 <DataRowSkeleton> — paired loading-state primitive
// "The skeleton is the voice" — labels render as static text, values as animated
// pulse-bar placeholders. Same DataRowField[] shape inherited from <DataRow>.
//
// Brand discipline (per Decision M + Decision F):
//   - Pulse-bar placeholder color is NEUTRAL GRAY, not forest. Pulse is not one of
//     forest's 5 jobs (branding-guide.md §"Color system").
//   - Labels stay Plex Sans bold (same register as <DataRow> labels).
//   - role="status" + aria-busy="true"; aria-label synthesized from field labels.
//   - prefers-reduced-motion: reduce → static structural skeleton (Tailwind
//     animate-pulse honors the media query via app/globals.css block).
//   - No width/pulse/count/density props — no escape hatch.
//
// Ships against text spec only at Session 1a (no design-tool PDF render);
// /brand-manager coherence-sweep fires at Session 3 `/new` first-feed-render
// per Gate-1 flag 2.

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
