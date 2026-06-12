import { test } from 'node:test';
import assert from 'node:assert/strict';
import { formatTypeLabel } from './type-label.ts';

test('formatTypeLabel: acronym SPS → ALL-CAPS, italic=false', () => {
  assert.deepEqual(formatTypeLabel('SPS'), { display: 'SPS', italic: false });
});

test('formatTypeLabel: acronym LPS → ALL-CAPS, italic=false', () => {
  assert.deepEqual(formatTypeLabel('LPS'), { display: 'LPS', italic: false });
});

test('formatTypeLabel: acronym case-insensitive — sps → SPS', () => {
  assert.deepEqual(formatTypeLabel('sps'), { display: 'SPS', italic: false });
});

test('formatTypeLabel: category word Zoa → Title Case, italic=false', () => {
  assert.deepEqual(formatTypeLabel('Zoa'), { display: 'Zoa', italic: false });
});

test('formatTypeLabel: category word Chalice → Title Case, italic=false', () => {
  assert.deepEqual(formatTypeLabel('Chalice'), {
    display: 'Chalice',
    italic: false,
  });
});

test('formatTypeLabel: category word case-insensitive — chalice → Chalice', () => {
  assert.deepEqual(formatTypeLabel('chalice'), {
    display: 'Chalice',
    italic: false,
  });
});

test('formatTypeLabel: binomial Acropora tenuis → italic=true, display preserved', () => {
  assert.deepEqual(formatTypeLabel('Acropora tenuis'), {
    display: 'Acropora tenuis',
    italic: true,
  });
});

test('formatTypeLabel: binomial does not match Acropora sp. (period-terminated species)', () => {
  // "Acropora sp." is shorthand, not a formal binomial; falls through to
  // passthrough rather than italic. Period in species token violates the
  // /^[a-z]+$/ binomial-class predicate.
  assert.deepEqual(formatTypeLabel('Acropora sp.'), {
    display: 'Acropora sp.',
    italic: false,
  });
});

test('formatTypeLabel: unknown value passthrough — Encrusting → display=Encrusting, italic=false', () => {
  // Not in any of the three classes; drift-add discipline says raw passthrough
  // until a class is assigned.
  assert.deepEqual(formatTypeLabel('Encrusting'), {
    display: 'Encrusting',
    italic: false,
  });
});

test('formatTypeLabel: whitespace trimmed before class match', () => {
  assert.deepEqual(formatTypeLabel('  SPS  '), {
    display: 'SPS',
    italic: false,
  });
});
