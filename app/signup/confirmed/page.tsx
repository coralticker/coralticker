// "I" carve-out handshake-flavor surface — success-acknowledgment owns the
// first-person voice here.

import type { Metadata } from 'next';
import Link from 'next/link';
import { PageShell } from '@/components/ui/page-shell';
import { PageH1 } from '@/components/ui/page-h1';

// Description is empty because robots: noindex means the surface never appears
// in SERP — no wording to tune.
export const metadata: Metadata = {
  title: 'Confirmed', // suffix via root title.template
  description: '',
  robots: { index: false, follow: true },
};

export default function SignupConfirmed() {
  return (
    <PageShell as="section">
      <PageH1 className="mb-6">
        You&apos;re subscribed.
      </PageH1>
      <p className="text-base leading-relaxed">
        I&apos;ll send one email each morning — new arrivals, price drops, and
        back-in-stock from the vendors I cover.
      </p>
      <p className="text-base leading-relaxed mt-4">
        I track what each vendor charges over time — so you can see how a price
        has moved, not just today&apos;s number.
      </p>
      <p className="text-base leading-relaxed mt-4">
        Until then,{' '}
        <Link href="/new" className="underline underline-offset-[3px] decoration-1">
          see what&apos;s already listed
        </Link>
        .
      </p>
    </PageShell>
  );
}
