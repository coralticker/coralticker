'use client';

// Route-level error boundary — catches Server Component throws across all
// views. App Router requires 'use client' for error boundaries. Retry click
// swaps visible copy to "Retrying." before invoking reset() — the one loading
// state that earns visible copy.
//
// The em-dash literal is a placeholder seam — last-successful-scrape time
// wiring lands in a downstream session.

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
