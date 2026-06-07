// /signup — direct-route fallback per site.md §4.6.
//
// Surface 2 LOCKED copy verbatim from /brand-manager Session 7 pre-session
// sweep. Static page — no revalidate, no Suspense, no data fetching. Server
// Component shell wraps the existing <SignupForm> client composition.
//
// Engineering call on the SignupForm prop API: the directive's literal
// source="standalone" doesn't match the locked email_signup_source ENUM (6
// values per architecture-v1.md §1.9.1 + types/email-signups.ts). Picked the
// directive's second-option shape — optional showLabel?: boolean default true
// — over extending source (which would require an ALTER TYPE migration that
// is out of Session 7 scope). showLabel={false} suppresses the internal
// "New arrivals in your inbox." <label> so the page H1 carries hierarchy;
// <Input aria-label="Email"> retains accessible-name coverage. source="other"
// is the catch-all DB value per plan.md task line 208 lock.
//
// Metadata vocabulary per site.md §6.1 / architecture-v1.md §6.1.

import type { Metadata } from 'next';
import { SignupForm } from '@/components/signup-form';

// Metadata wording verbatim from site.md §6.1 line 1710.
export const metadata: Metadata = {
  title: 'Sign up', // suffix via root title.template
  description:
    'Weekly digest of new coral drops, price changes, and arrivals across vendors. Free.',
  alternates: { canonical: '/signup' },
  openGraph: { url: '/signup', siteName: 'CoralTicker', type: 'website', locale: 'en_US' },
  twitter: { card: 'summary' },
};

export default function Signup() {
  return (
    <main className="px-6 py-12 max-w-3xl mx-auto">
      <h1 className="text-3xl md:text-4xl font-bold mb-8">
        New arrivals in your inbox.
      </h1>
      <SignupForm source="other" showLabel={false} />
    </main>
  );
}
