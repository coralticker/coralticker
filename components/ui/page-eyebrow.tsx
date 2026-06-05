import { Fragment } from 'react';

interface PageEyebrowProps {
  chunks: string[];
}

export function PageEyebrow({ chunks }: PageEyebrowProps) {
  return (
    <p className="text-xs uppercase tracking-[0.08em] font-mono text-ink mb-4">
      {chunks.map((chunk, i) => (
        <Fragment key={i}>
          {i > 0 && <span aria-hidden="true" className="text-forest"> · </span>}
          {chunk}
        </Fragment>
      ))}
    </p>
  );
}

export function PageEyebrowSkeleton() {
  return (
    <p
      className="text-xs uppercase tracking-[0.08em] font-mono mb-4"
      aria-busy="true"
      role="status"
      aria-label="Loading eyebrow"
    >
      &nbsp;
    </p>
  );
}
