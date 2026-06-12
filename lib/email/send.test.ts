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

  // headers? is part of the body-agnostic signature; the dry-run path must
  // accept and ignore it without error.
  const result = await sendEmail({
    to: 'reefer@example.com',
    subject: 'x',
    html: '<p>x</p>',
    headers: { 'List-Unsubscribe': '<https://coralticker.com/unsubscribe?t=abc>' },
  });

  assert.deepEqual(result, { sent: false });
});
