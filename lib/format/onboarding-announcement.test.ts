// Pure coverage for the CTK-214 onboarding-announcement leaf — tier
// classification + the canonical strings. The per-channel HTML/markdown/JSX
// styling is covered in lib/email/digest.test.ts, scripts/discord-digest.test.ts,
// and the /new strip at the component layer.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  COLLAPSE_THRESHOLD,
  NOW_TRACKING,
  batchedHeadline,
  classifyOnboarding,
  collapseHeadline,
  vendorPieces,
  type OnboardingVendor,
} from './onboarding-announcement.ts';

function v(displayName: string, n: number, vendorSlug = displayName.toLowerCase()): OnboardingVendor {
  return { vendorSlug, displayName, n };
}

test('classifyOnboarding: empty -> none', () => {
  assert.deepEqual(classifyOnboarding([]), { tier: 'none' });
});

test('classifyOnboarding: one -> single', () => {
  const block = classifyOnboarding([v('Biota', 276)]);
  assert.equal(block.tier, 'single');
  assert.equal(block.tier === 'single' && block.vendor.n, 276);
});

test('classifyOnboarding: 2-4 -> batched with count', () => {
  for (const k of [2, 3, 4]) {
    const block = classifyOnboarding(Array.from({ length: k }, (_, i) => v(`V${i}`, i + 1)));
    assert.equal(block.tier, 'batched');
    assert.equal(block.tier === 'batched' && block.count, k);
  }
});

test('classifyOnboarding: >=5 -> collapse with count', () => {
  const block = classifyOnboarding(Array.from({ length: 8 }, (_, i) => v(`V${i}`, i + 1)));
  assert.equal(block.tier, 'collapse');
  assert.equal(block.tier === 'collapse' && block.count, 8);
});

test('COLLAPSE_THRESHOLD boundary: 4 batched, 5 collapse', () => {
  const four = classifyOnboarding(Array.from({ length: COLLAPSE_THRESHOLD - 1 }, (_, i) => v(`V${i}`, 1)));
  const five = classifyOnboarding(Array.from({ length: COLLAPSE_THRESHOLD }, (_, i) => v(`V${i}`, 1)));
  assert.equal(four.tier, 'batched');
  assert.equal(five.tier, 'collapse');
});

test('vendorPieces: honest-framing noun, em-dash, never dropped', () => {
  assert.equal(vendorPieces('Biota', 276), 'Biota — 276 pieces');
  // The noun is structural — there is no path that emits a bare number.
  assert.match(vendorPieces('Coral Stop', 824), /824 pieces$/);
});

test('canonical lead strings', () => {
  assert.equal(NOW_TRACKING, 'Now tracking.');
  assert.equal(batchedHeadline(4), '4 new vendors:');
  assert.equal(collapseHeadline(8), 'Now tracking 8 new vendors:');
});
