// getRequiredEnv coverage (CTK-128 (f)). Pins the contract the three
// module-scope consumers (lib/db/neon.ts, app/corals/page.tsx,
// app/about/_components/social-links.tsx) rely on: set → value through,
// missing OR empty → throw, message names the var + .env.example.
//
// Runs via Node's built-in test runner with native TypeScript type stripping:
//   node --test --experimental-strip-types lib/*.test.ts

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { getRequiredEnv } from './env.ts';

const KEY = 'CTK128_TEST_ENV_VAR';

test('getRequiredEnv: returns the value when set', () => {
  process.env[KEY] = 'https://example.test/value';
  try {
    assert.equal(getRequiredEnv(KEY), 'https://example.test/value');
  } finally {
    delete process.env[KEY];
  }
});

test('getRequiredEnv: throws when missing, message names the var and .env.example', () => {
  delete process.env[KEY];
  assert.throws(
    () => getRequiredEnv(KEY),
    (err: unknown) =>
      err instanceof Error &&
      err.message.includes(KEY) &&
      err.message.includes('.env.example'),
  );
});

test('getRequiredEnv: empty string counts as missing (pre-extraction falsy semantics)', () => {
  process.env[KEY] = '';
  try {
    assert.throws(() => getRequiredEnv(KEY));
  } finally {
    delete process.env[KEY];
  }
});
