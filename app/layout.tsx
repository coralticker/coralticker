import './globals.css';
import type { Metadata } from 'next';
import type { ReactNode } from 'react';
import { plexSans, plexMono } from './fonts';
import { Wordmark } from '@/components/ui/wordmark';
import { Footer } from '@/components/footer';
import { RelativeTimeProvider } from '@/components/ui/relative-time';

export const metadata: Metadata = {
  title: 'CoralTicker',
  description: 'Drop alerts and price tracking for reef hobbyists.',
};

export default function RootLayout({
  children,
}: {
  children: ReactNode;
}) {
  return (
    <html lang="en" className={`${plexSans.variable} ${plexMono.variable}`}>
      <body className="font-sans bg-cream text-ink min-h-screen flex flex-col">
        <nav className="px-6 py-4">
          <Wordmark variant="nav" />
        </nav>
        <RelativeTimeProvider>
          <main className="flex-1">{children}</main>
        </RelativeTimeProvider>
        <Footer />
      </body>
    </html>
  );
}
