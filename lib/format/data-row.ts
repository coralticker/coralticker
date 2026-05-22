// lib/format/data-row.ts
//
// INV-01 channel-parity sibling for <DataRow> (§3.2). The web component renders
// the canonical em-dash data row to DOM; this helper renders the same logical
// content as plain text for non-DOM channels (CTK-009 email digest, CTK-011
// Discord embed, CTK-018 push body). Channel-specific styling (strikethrough,
// color, weight) is applied downstream by each channel adapter; the parity rule
// is shape-invariant — same field order, same labels, same em-dash separator,
// same value-kind text representation.
//
// Consumes formatRelativeTime() at send-time per site.md §3.6 fold-point E.

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
  if (value.kind === 'relative-time') {
    return formatRelativeTime(value.timestamp, now);
  }
  if (value.kind === 'invalidated') {
    // CTK-070 OOS state-marker: channel-neutral text representation of the
    // invalidated value. Strikethrough rendering is DOM-only per
    // branding-guide.md §"State markers" L197 generalized canon; non-DOM
    // channels carry the same semantic via the row-state-marker label
    // ("OUT OF STOCK") rendered separately at the channel adapter, plus
    // the bare value here. Channel adapters that want a unicode strikethrough
    // (combining char U+0336) can re-process at the adapter layer.
    return value.value;
  }
  // price-drop-new: "was $oldValue, now $newValue" — channel-neutral text;
  // strikethrough + forest-bold rendering is DOM-only per branding-guide.md §"State markers".
  return `was ${value.oldValue}, now ${value.newValue}`;
}
