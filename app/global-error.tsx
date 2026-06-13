'use client';

// Root-layout-throw fallback — fires when the root layout (app/layout.tsx)
// itself throws, so this surface has to render its own <html lang="en"> +
// <body>: it sits outside the layout tree and cannot inherit it. App Router
// requires 'use client' for error boundaries.
//
// The em-dash placeholder stands in until last-successful-scrape timestamp
// wiring lands (same seam as app/error.tsx).

import { useState } from 'react';
import { plexSans, plexMono } from './fonts';
import { Button } from '@/components/ui/button';

interface GlobalErrorProps {
  error: Error & { digest?: string };
  reset: () => void;
}

export default function GlobalError({ reset }: GlobalErrorProps) {
  const [retrying, setRetrying] = useState(false);

  function handleRetry() {
    setRetrying(true);
    reset();
  }

  return (
    <html lang="en" className={`${plexSans.variable} ${plexMono.variable}`}>
      <body className="font-sans bg-cream text-ink min-h-screen flex flex-col">
        <div role="alert" className="max-w-prose mx-auto py-16 px-4">
          <p className="text-base text-ink">
            {retrying
              ? 'Retrying.'
              : "The feed's not updating. I'm fixing it. Last update: —."}
          </p>
          <div className="mt-4">
            <Button type="button" disabled={retrying} onClick={handleRetry}>
              Try again
            </Button>
          </div>
        </div>
      </body>
    </html>
  );
}
