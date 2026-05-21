'use client';

// app/global-error.tsx — Root-layout-throw fallback.
//
// Fires when the root layout (app/layout.tsx) itself throws, so this surface
// has to render its own <html lang="en"> + <body> — it sits outside the layout
// tree and cannot inherit it. App Router requires 'use client' for error
// boundaries.
//
// Copy verbatim from branding-guide.md L77-80 downtime template
// ("Scrapers are down. I'm fixing it. Last update: {timestamp}."); em-dash
// placeholder stands in until last-successful-scrape timestamp wiring lands
// (downstream session, same seam as app/error.tsx). Retry button mirrors
// app/error.tsx:39-42 shape — "Retrying." swap-state per branding-guide.md L88.
//
// Folded in 2026-05-21 per /brand-manager INV-02 pre-first-implementation-session
// gate for CTK-015 (coordination-invariants.md INV-02 checkpoint 1 of 3).

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
              : "Scrapers are down. I'm fixing it. Last update: —."}
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
