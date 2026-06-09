// lib/email/templates/confirm-email.test.ts
//
// Locks the CTK-016 Leg 3 confirm-email content contract (Q-1/Q-2 ratified):
// the single CTA is the confirm link, there is NO /new link and NO unsubscribe
// link, the H1 + footer copy are verbatim, and the token reaches the CTA href.
//
//   node --test --experimental-strip-types lib/email/templates/*.test.ts

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { confirmEmail } from './confirm-email.ts';
import { confirmUrl } from '../token.ts';

const TOKEN = 'test-token-abc123';

test('subject is the ratified transactional line', () => {
  const { subject } = confirmEmail(TOKEN);
  assert.equal(subject, 'Confirm your email.');
});

test('single CTA points at confirmUrl(token); no other link present', () => {
  const { html } = confirmEmail(TOKEN);
  const href = confirmUrl(TOKEN);
  assert.ok(html.includes(href), 'CTA href must be confirmUrl(token)');

  // Exactly one <a href> — the confirm CTA. No /new, no unsubscribe.
  const hrefs = [...html.matchAll(/href="([^"]+)"/g)].map((m) => m[1]);
  assert.deepEqual(hrefs, [href], 'the only link must be the confirm CTA');
  assert.ok(!html.includes('/new'), 'no /new link (confirm-rate leak, Q-1)');
  assert.ok(!html.includes('/unsubscribe'), 'no unsubscribe link pre-confirm (Q-2)');
});

test('H1 + footer copy are verbatim; H1 is not the false "subscribed" claim', () => {
  const { html } = confirmEmail(TOKEN);
  assert.ok(html.includes('Confirm your email.'), 'H1 verbatim');
  assert.ok(
    html.includes("Didn't sign up? Ignore this — you won't hear from me again."),
    'footer verbatim',
  );
  assert.ok(!html.includes("You're subscribed"), 'must not claim subscribed pre-click');
});

test('carries the brand wordmark + tagline lockup', () => {
  const { html } = confirmEmail(TOKEN);
  assert.ok(html.includes('>coral<') && html.includes('>ticker<'), 'wordmark present');
  assert.ok(html.includes('Never miss the drop.'), 'tagline present');
});
