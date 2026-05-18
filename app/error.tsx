'use client';

// §0.2 #4 — Route-level error boundary.
//
// Catches Server Component throws across all views. App Router requires
// 'use client' for error boundaries. Initial fallback uses the "I'm fixing it"
// downtime register per branding-guide.md §"Downtime / error copy"
// (first-person carve-out at line 98). Retry click swaps visible copy to
// "Retrying." before invoking reset() — the one loading state that earns
// visible copy per §"Loading-state copy".
//
// {timestamp} surfaces last-successful-scrape time at runtime via
// getLastScrapeTimestamp() helper landing in a downstream session. Session 1b
// renders an em-dash literal as the placeholder seam.

import { useState } from 'react';
import { Button } from '@/components/ui/button';

interface ErrorProps {
  error: Error & { digest?: string };
  reset: () => void;
}

export default function GlobalError(_props: ErrorProps) {
  const [retrying, setRetrying] = useState(false);

  function handleRetry() {
    setRetrying(true);
    _props.reset();
  }

  return (
    <div role="alert" className="max-w-prose mx-auto py-16 px-4">
      <p className="text-base text-ink">
        {retrying
          ? 'Retrying.'
          : "Something's off here. I'm fixing it. Last update: —."}
      </p>
      <div className="mt-4">
        <Button type="button" disabled={retrying} onClick={handleRetry}>
          Try again
        </Button>
      </div>
    </div>
  );
}
