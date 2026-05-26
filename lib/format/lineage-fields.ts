// Pure-function builder for the /coral/[slug] page-level lineage row's
// DataRowField[] array. Applies class-aware type casing (formatTypeLabel) +
// originator full-name resolution (resolveOriginVendor) + sentinel
// suppression in one boundary.
//
// Em-dash auto-collapse — `<DataRow>` (components/ui/data-row.tsx) interleaves
// em-dash separators between BOUND fields only, so a suppressed Origin field
// (community/canonical sentinel) simply doesn't enter this array; no orphan
// separator can render. Per branding-guide.md §"Sentinel render policy": with
// only Type populated the lineage row renders bare `Type. SPS` — no trailing
// em-dash, no Origin slot. With both Type and Origin populated it renders
// `Type. SPS — Origin. World Wide Corals`.
//
// Lifted from app/coral/[slug]/page.tsx during CTK-092 Session 2 so the
// sentinel-suppression + class-casing + originator-resolution composition
// has a pure-function test boundary per feedback_review_results_spec_flow_
// trace.md (diff-at-consumer ≠ behavior-at-DOM).

import type { DataRowField } from '@/components/ui/data-row';
import type { NamedCoral } from '@/lib/queries/named-corals';
import { formatTypeLabel } from './type-label.ts';
import { resolveOriginVendor } from './origin-vendor.ts';

export function buildLineageFields(coral: NamedCoral): DataRowField[] {
  const fields: DataRowField[] = [];
  // Truthy guards (not !== null) — rule out null AND empty-string drift in
  // one boundary. Empty strings in DB columns would otherwise render as a
  // bound-but-blank field, breaking em-dash collapse and chrome registers.
  if (coral.coral_type) {
    const typeRender = formatTypeLabel(coral.coral_type);
    fields.push({
      label: 'Type',
      value: typeRender.italic
        ? { kind: 'italic', value: typeRender.display }
        : typeRender.display,
    });
  }
  if (coral.origin_vendor) {
    const originRender = resolveOriginVendor(coral.origin_vendor);
    if (!('suppress' in originRender && originRender.suppress)) {
      fields.push({ label: 'Origin', value: originRender.display });
    }
  }
  return fields;
}
