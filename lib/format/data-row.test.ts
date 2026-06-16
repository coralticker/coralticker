// CTK-161 D-3 — INV-01 parity: TS half. Pins formatDataRow() to the committed
// golden (data-row-golden.json). The Python mirror (scrapers/tools/data_row.py)
// pins to the SAME file in scrapers/tests/test_data_row_parity.py — so drift on
// EITHER side fails its own test, with no node-in-pytest coupling. The golden
// exercises every value-kind in the DataRowFieldValue union + a composite.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { formatDataRow } from './data-row.ts';
import type { DataRowField } from '@/components/ui/data-row';

interface GoldenCase {
  name: string;
  fields: DataRowField[];
  expected: string;
}
interface Golden {
  now: string;
  cases: GoldenCase[];
}

const golden = JSON.parse(
  readFileSync(new URL('./data-row-golden.json', import.meta.url), 'utf8'),
) as Golden;

const NOW = new Date(golden.now);

for (const c of golden.cases) {
  test(`formatDataRow golden: ${c.name}`, () => {
    assert.equal(formatDataRow(c.fields, NOW), c.expected);
  });
}
