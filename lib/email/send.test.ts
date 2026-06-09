// lib/email/send.test.ts
//
// Dry-run path proof for the D-3 transport wrapper: with RESEND_API_KEY unset
// (local / CI), sendEmail() must NOT call Resend, must NOT throw, and must
// return {sent:false}. This is the CTK-016 dependency-note guarantee — the
// local dry-run path must not require RESEND_API_KEY.
//
// The live-send + failure-alert branch is not unit-tested here: it requires a
// real Resend key + network and is verified by the Leg-3 forced-failure path
// (plan success criterion D-3). These tests cover the keyless short-circuit.
//
// Runs via Node's built-in test runner with native TypeScript type stripping:
//   node --test --experimental-strip-types lib/email/*.test.ts

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { sendEmail } from './send.ts';

test('sendEmail() dry-runs to {sent:false} when RESEND_API_KEY is unset', async () => {
  delete process.env.RESEND_API_KEY;

  const result = await sendEmail({
    to: 'reefer@example.com',
    subject: 'Confirm your email.',
    html: '<p>token link here</p>',
  });

  assert.deepEqual(result, { sent: false });
});

test('sendEmail() dry-run does not throw and ignores optional headers', async () => {
  delete process.env.RESEND_API_KEY;

  // headers? is part of the body-agnostic signature (CTK-136 List-Unsubscribe
  // reuse); the dry-run path must accept and ignore it without error.
  const result = await sendEmail({
    to: 'reefer@example.com',
    subject: 'x',
    html: '<p>x</p>',
    headers: { 'List-Unsubscribe': '<https://coralticker.com/unsubscribe?t=abc>' },
  });

  assert.deepEqual(result, { sent: false });
});
