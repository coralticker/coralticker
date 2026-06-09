// lib/email/token.test.ts
//
// Pure-function tests for the CTK-016 token generator + URL builders.
//
// Runs via Node's built-in test runner with native TypeScript type stripping:
//   node --test --experimental-strip-types lib/email/*.test.ts

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { generate, confirmUrl, unsubscribeUrl } from './token.ts';

test('generate() returns a 43-char base64url string (32 bytes, no padding)', () => {
  const tok = generate();
  // 32 bytes -> 43 base64url chars (ceil(32/3)*4 = 44, minus the dropped '=' pad).
  assert.equal(tok.length, 43);
  // base64url charset only: no +, /, or = — drops straight into a ?t= param.
  assert.match(tok, /^[A-Za-z0-9_-]+$/);
});

test('generate() is non-repeating across calls', () => {
  const seen = new Set<string>();
  for (let i = 0; i < 1000; i++) {
    seen.add(generate());
  }
  assert.equal(seen.size, 1000);
});

test('confirmUrl builds an absolute apex link with the token in ?t=', () => {
  assert.equal(
    confirmUrl('abc-123_XYZ'),
    'https://coralticker.com/confirm?t=abc-123_XYZ',
  );
});

test('unsubscribeUrl builds an absolute apex link with the token in ?t=', () => {
  assert.equal(
    unsubscribeUrl('abc-123_XYZ'),
    'https://coralticker.com/unsubscribe?t=abc-123_XYZ',
  );
});

test('URL builders accept the UUID-format DB-default token unescaped', () => {
  // The 0037 gen_random_uuid()::text backfill is [0-9a-f-] — URL-safe, so the
  // builders pass it through verbatim (both token encodings are query-safe).
  const uuid = 'dbe7f164-31ec-4c0a-9a1b-2f3e4d5c6b7a';
  assert.equal(confirmUrl(uuid), `https://coralticker.com/confirm?t=${uuid}`);
});
