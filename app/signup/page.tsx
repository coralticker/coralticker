// showLabel was chosen over a new source ENUM value: "standalone" doesn't match
// the locked email_signup_source ENUM, and extending it would require an
// ALTER TYPE migration. showLabel={false} suppresses the internal "New arrivals
// in your inbox." <label> so the page H1 carries hierarchy; <Input
// aria-label="Email"> retains accessible-name coverage. source="other" is the
// catch-all DB value.

import type { Metadata } from 'next';
import { SignupForm } from '@/components/signup-form';
import { PageShell } from '@/components/ui/page-shell';
import { PageH1 } from '@/components/ui/page-h1';

export const metadata: Metadata = {
  title: 'Sign up', // suffix via root title.template
  description:
    'Daily digest of new coral drops, price changes, and arrivals across vendors. Free.',
  alternates: { canonical: '/signup' },
  openGraph: { url: '/signup', siteName: 'CoralTicker', type: 'website', locale: 'en_US' },
  twitter: { card: 'summary' },
};

export default function Signup() {
  return (
    <PageShell as="section">
      <PageH1 className="mb-8">
        New arrivals in your inbox.
      </PageH1>
      <SignupForm source="other" showLabel={false} />
    </PageShell>
  );
}
