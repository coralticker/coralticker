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
    case 'vendor-markdown':
      // Shared string with price-drop-new per /brand-manager Lock 1
      // (CTK-100 brand-manager-session-2026-06-01). Reefer-facing semantic
      // is identical at the field level; INV-01 channel-adapters inherit
      // one rendering shape for both value-kinds.
      return `was ${value.oldValue}, now ${value.newValue}`;
    case 'italic':
      // DOM-only emphasis (<em>). Non-DOM channels carry the bare text;
      // channel-adapters wanting italic in-channel (markdown asterisks for
      // Discord, <i> for HTML email, etc.) re-process at the adapter layer.
      return value.value;
    default: {
      // Exhaustiveness check — `_exhaustive: never` fails typecheck if a new
      // DataRowFieldValue kind lands without a branch here, forcing explicit
      // handling.
      const _exhaustive: never = value;
      throw new Error(`formatDataRow: unhandled value kind ${JSON.stringify(_exhaustive)}`);
    }
  }
}
