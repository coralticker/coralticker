// CTK-129 regression guard (plan D-129-4). The ink/NN bug class was silent:
// `ink` lacks <alpha-value> in tailwind.config.ts (deliberately — the config
// flip was REJECTED at canon), so Tailwind v3 emits NO CSS for any ink/NN
// opacity modifier. Classes sat in source, absent from output, no build
// error — borders served preflight #E5E7EB, placeholders #9CA3AF, bg-ink/NN
// nothing, for ~3 weeks. The served-neutral re-spec (branding-guide
// §"Served-neutral re-spec") adopted literal tokens (line / mute / wash)
// instead; this test fails the suite if any dead-modifier form re-enters
// app/ or components/ source. Covers numeric (/30) and arbitrary-value
// (/[0.02]) forms across the utility prefixes the sweep retired.
//
// Runs via Node's built-in test runner with native TypeScript type stripping:
//   node --test --experimental-strip-types scripts/*.test.ts

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';

const DEAD_MODIFIER =
  /(?:text|border|bg|divide|placeholder:text|hover:bg)-ink\/[\d[]/;

const ROOTS = ['app', 'components'];
const EXTENSIONS = new Set(['.ts', '.tsx']);

function* walk(dir: string): Generator<string> {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      yield* walk(full);
    } else if (EXTENSIONS.has(full.slice(full.lastIndexOf('.')))) {
      yield full;
    }
  }
}

test('no dead ink/NN opacity-modifier utilities in app/ or components/ source', () => {
  const hits: string[] = [];
  for (const root of ROOTS) {
    for (const file of walk(root)) {
      const lines = readFileSync(file, 'utf8').split('\n');
      lines.forEach((line, i) => {
        if (DEAD_MODIFIER.test(line)) {
          hits.push(`${file}:${i + 1}: ${line.trim()}`);
        }
      });
    }
  }
  assert.deepEqual(
    hits,
    [],
    `ink/NN opacity modifiers generate NO CSS (ink has no <alpha-value>; ` +
      `the config flip is canon-rejected). Use the served-neutral tokens ` +
      `instead — line (hairlines), mute (placeholders), wash (skeleton/` +
      `wash fills) — per branding-guide §"Served-neutral re-spec".\n` +
      hits.join('\n'),
  );
});
