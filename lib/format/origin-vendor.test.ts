// Branch coverage for resolveOriginVendor() per branding-guide.md §"Originator
// full names" + §"Compound-attribution shape" + sentinel render policy.
//
// Covers the three render branches (sentinel exact-match, compound split,
// single-value lookup) plus the unknown-component passthrough fallback and
// the precedence rule (sentinel takes precedence over compound parsing
// because the literal contains a slash).
//
// Runs via Node's built-in test runner with native TypeScript type stripping:
//   node --test --experimental-strip-types lib/format/*.test.ts

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { resolveOriginVendor } from './origin-vendor.ts';

test('resolveOriginVendor: sentinel community/canonical → { suppress: true }', () => {
  assert.deepEqual(resolveOriginVendor('community/canonical'), {
    suppress: true,
  });
});

test('resolveOriginVendor: sentinel precedence — community/canonical does NOT route through compound branch', () => {
  // The sentinel contains a `/` and would otherwise split-parse into
  // ["community", "canonical"]. Sentinel exact-match must fire first.
  const result = resolveOriginVendor('community/canonical');
  assert.equal('suppress' in result && result.suppress, true);
});

test('resolveOriginVendor: single-value WWC → World Wide Corals', () => {
  assert.deepEqual(resolveOriginVendor('WWC'), {
    display: 'World Wide Corals',
  });
});

test('resolveOriginVendor: single-value TSA → Top Shelf Aquatics', () => {
  assert.deepEqual(resolveOriginVendor('TSA'), {
    display: 'Top Shelf Aquatics',
  });
});

test('resolveOriginVendor: single-value JF → Jason Fox Signature Corals', () => {
  assert.deepEqual(resolveOriginVendor('JF'), {
    display: 'Jason Fox Signature Corals',
  });
});

test('resolveOriginVendor: single-value Battlecorals → Battlecorals (one-word self-brand)', () => {
  assert.deepEqual(resolveOriginVendor('Battlecorals'), {
    display: 'Battlecorals',
  });
});

test('resolveOriginVendor: single-value ORA → ORA (self-branded-abbreviation carve-out)', () => {
  // Per branding-guide.md L144 carve-out — ORA IS the brand; full expansion
  // "Oceans, Reefs and Aquariums" is reserved for /about-class formal
  // contexts, not daily-use display.
  assert.deepEqual(resolveOriginVendor('ORA'), { display: 'ORA' });
});

test('resolveOriginVendor: single-value Tyree → Steve Tyree (originator-only)', () => {
  assert.deepEqual(resolveOriginVendor('Tyree'), { display: 'Steve Tyree' });
});

test('resolveOriginVendor: single-value Reeffarmers → Reeffarmers', () => {
  assert.deepEqual(resolveOriginVendor('Reeffarmers'), {
    display: 'Reeffarmers',
  });
});

test('resolveOriginVendor: single-value Pro Corals → Pro Corals (CTK-126 drift-add, plain full-name)', () => {
  // branding-guide.md L143 — "PC" is in-name shorthand only, too ambiguous
  // standalone for the carve-out; plain full-name default applies.
  assert.deepEqual(resolveOriginVendor('Pro Corals'), { display: 'Pro Corals' });
});

test('resolveOriginVendor: single-value GARF → GARF (CTK-126 drift-add, self-branded-abbreviation carve-out)', () => {
  // branding-guide.md L144 — GARF IS the brand (ORA pattern); expansion
  // "Geothermal Aquaculture Research Foundation" reserved for /about contexts.
  assert.deepEqual(resolveOriginVendor('GARF'), { display: 'GARF' });
});

test('resolveOriginVendor: compound Tyree/Reeffarmers → "Steve Tyree / Reeffarmers"', () => {
  // Compound-attribution per branding-guide.md L141 + §"Compound-attribution
  // shape" — split on /, per-component lookup, join with ' / ' (space-slash-
  // space). Exercises the Reeffarmers component-render branch + satisfies
  // SC-2 compound row criterion.
  assert.deepEqual(resolveOriginVendor('Tyree/Reeffarmers'), {
    display: 'Steve Tyree / Reeffarmers',
  });
});

test('resolveOriginVendor: compound whitespace-tolerant — "Tyree / Reeffarmers" → same', () => {
  assert.deepEqual(resolveOriginVendor('Tyree / Reeffarmers'), {
    display: 'Steve Tyree / Reeffarmers',
  });
});

test('resolveOriginVendor: unknown single-value passthrough — UnknownOriginator → UnknownOriginator', () => {
  // Drift-add discipline — unknown component values fall back to raw
  // passthrough; /code-review flags for /brand-manager canon-extension at
  // first-exercise.
  assert.deepEqual(resolveOriginVendor('UnknownOriginator'), {
    display: 'UnknownOriginator',
  });
});

test('resolveOriginVendor: compound with unknown component passes through raw', () => {
  // Tyree resolves; UnknownOriginator falls through to raw passthrough.
  assert.deepEqual(resolveOriginVendor('Tyree/UnknownOriginator'), {
    display: 'Steve Tyree / UnknownOriginator',
  });
});

test('resolveOriginVendor: whitespace trimmed before sentinel/compound check', () => {
  assert.deepEqual(resolveOriginVendor('  WWC  '), {
    display: 'World Wide Corals',
  });
});

test('resolveOriginVendor: sentinel drift form Community/Canonical → { suppress: true }', () => {
  // Defensive normalize-on-input — case + internal-whitespace drift on the
  // sentinel literal still suppresses cleanly. No schema constraint imposed
  // upstream; render-side resolver tolerates the drift.
  assert.deepEqual(resolveOriginVendor('Community/Canonical'), {
    suppress: true,
  });
});
