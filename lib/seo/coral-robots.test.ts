import { test } from 'node:test';
import assert from 'node:assert/strict';
import { coralPageRobots } from './coral-robots.ts';

// The /coral/[slug] generateMetadata noindex decision (CTK-185(b)). The page's
// generateMetadata can't be imported under `node --test --experimental-strip-types`
// (JSX + '@/' aliases in the page graph), so the decision lives in this pure
// helper and is exercised directly — deleting the helper body fails these.

test('never-listed coral (has_ever_listed=false) is noindex, still followed', () => {
  const robots = coralPageRobots(false);
  assert.notEqual(robots, undefined, 'expected a robots directive for a thin page');
  assert.equal(typeof robots, 'object');
  // narrow off the union so the property reads typecheck
  const r = robots as { index?: boolean; follow?: boolean };
  assert.equal(r.index, false, 'thin lore-only page must be noindex');
  assert.equal(r.follow, true, 'links out (guides, /corals) must still pass equity');
});

test('ever-listed coral (has_ever_listed=true) sets no noindex', () => {
  // undefined → generateMetadata omits the robots key → Next defaults to
  // index,follow. The assertion that matters: NOT a noindex directive.
  assert.equal(coralPageRobots(true), undefined);
});
