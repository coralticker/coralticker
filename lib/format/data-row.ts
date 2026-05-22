// Channel-parity sibling for <DataRow>. The web component renders the canonical
// em-dash data row to DOM; this helper renders the same logical content as
// plain text for non-DOM channels (email digest, Discord embed, push body).
// Channel-specific styling (strikethrough, color, weight) is applied downstream
// by each channel adapter; the parity rule is shape-invariant — same field
// order, same labels, same em-dash separator, same value-kind text.

import type { DataRowField } from '@/components/ui/data-row';
import { formatRelativeTime } from '@/lib/format/relative-time';

export function formatDataRow(fields: DataRowField[], now: Date): string {
  return fields
    .map((field) => `${field.label}. ${formatValue(field.value, now)}`)
    .join(' — ');
}

function formatValue(value: DataRowField['value'], now: Date): string {
  if (typeof value === 'string') {
    return value;
  }
  switch (value.kind) {
    case 'relative-time':
      return formatRelativeTime(value.timestamp, now);
    case 'invalidated':
      // DOM-only strikethrough. Non-DOM channels carry the OOS semantic via a
      // separate row-state-marker label at the channel adapter, plus the bare
      // value here. Adapters wanting a unicode strikethrough (combining char
      // U+0336) can re-process at the adapter layer.
      return value.value;
    case 'price-drop-new':
      return `was ${value.oldValue}, now ${value.newValue}`;
    default: {
      // Exhaustiveness check: adding a 5th DataRowFieldValue kind fails
      // typecheck here, forcing the new branch to be handled explicitly.
      const _exhaustive: never = value;
      throw new Error(`formatDataRow: unhandled value kind ${JSON.stringify(_exhaustive)}`);
    }
  }
}
