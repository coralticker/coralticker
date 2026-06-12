'use client';

// Hidden <input name="source"> threads attribution to the Server Action.
//
// Submit-pending: button stays disabled with the "Subscribe" label unchanged
// (silent loading per branding-guide §"Loading-state copy"). Success and
// already-subscribed states replace the form inline (no navigation); errors
// surface inline in the aria-live region with the form mounted for retry.
//
// showLabel suppresses the duplicate internal section label for standalone
// consumers where a page-H1 already carries that hierarchy. The
// <Input aria-label="Email"> retains accessible-name coverage when the
// <label> is suppressed.

import { useActionState } from 'react';
import { useFormStatus } from 'react-dom';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { signupAction, type SignupActionResult } from '@/app/signup/actions';
import type { EmailSignupSource } from '@/types/email-signups';

interface SignupFormProps {
  source: EmailSignupSource;
  showLabel?: boolean;
}

const SECTION_LABEL = 'New arrivals in your inbox.';
const EXPECTATION_TEXT =
  'One email each morning — new arrivals, price drops, and back-in-stock across vendors. Free.';
const PLACEHOLDER = 'you@example.com';
const SUBMIT_LABEL = 'Subscribe';
const SUCCESS_TEXT =
  "Thanks. Check your email — spam folder too. If it's there, drag it to your inbox so the next one isn't.";
const ALREADY_SUBSCRIBED_TEXT =
  'Already on the list. Check your email for the next digest.';

const INITIAL_STATE: SignupActionResult | null = null;

function SubmitButton() {
  const { pending } = useFormStatus();
  return (
    <Button type="submit" disabled={pending} aria-busy={pending}>
      {SUBMIT_LABEL}
    </Button>
  );
}

export function SignupForm({ source, showLabel = true }: SignupFormProps) {
  const [result, formAction] = useActionState(signupAction, INITIAL_STATE);

  if (result?.ok) {
    return (
      <div
        role="status"
        aria-live="polite"
        className="text-sm text-ink"
      >
        {result.alreadySubscribed ? ALREADY_SUBSCRIBED_TEXT : SUCCESS_TEXT}
      </div>
    );
  }

  return (
    <form action={formAction} className="flex flex-col gap-3" noValidate>
      {showLabel && (
        <label htmlFor="signup-email" className="text-sm text-ink">
          {SECTION_LABEL}
        </label>
      )}
      <div className="flex flex-col sm:flex-row gap-2">
        <div className="flex-1">
          <Input
            id="signup-email"
            name="email"
            type="email"
            aria-label="Email"
            placeholder={PLACEHOLDER}
            required
          />
        </div>
        <SubmitButton />
      </div>
      <p className="text-sm text-ink">{EXPECTATION_TEXT}</p>
      <input type="hidden" name="source" value={source} />
      <div
        aria-live="polite"
        className="min-h-[1.25rem] text-sm text-ink"
      >
        {result && !result.ok ? result.error : null}
      </div>
    </form>
  );
}
