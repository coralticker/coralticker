import './globals.css';
import type { Metadata } from 'next';
import type { ReactNode } from 'react';
import Script from 'next/script';
import { plexSans, plexMono } from './fonts';
import { SiteNav } from '@/components/site-nav';
import { Footer } from '@/components/footer';
import { RelativeTimeProvider } from '@/components/ui/relative-time';

export const metadata: Metadata = {
  metadataBase: new URL('https://coralticker.com'),
  title: { template: '%s — CoralTicker', default: 'CoralTicker' },
  description: 'Drop alerts and price tracking for reef hobbyists.',
};

export default function RootLayout({
  children,
}: {
  children: ReactNode;
}) {
  return (
    <html lang="en" className={`${plexSans.variable} ${plexMono.variable}`}>
      <head>
        <Script
          defer
          data-domain="coralticker.com"
          src="https://plausible.io/js/script.js"
          strategy="afterInteractive"
        />
      </head>
      <body className="font-sans bg-cream text-ink min-h-screen flex flex-col">
        <SiteNav />
        <RelativeTimeProvider>
          <main className="flex-1">{children}</main>
          <Footer />
        </RelativeTimeProvider>
      </body>
    </html>
  );
}
