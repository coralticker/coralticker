// lib/format/lineage.ts
//
// formatLineage() — plain-string lineage formatter for <ListingCard>'s Lineage
// field per site.md §3.5.1. Consumed when namedCoralCanonicalName is non-null
// (the listing matches a row in named_corals); produces a short plain string
// describing origin + year, dropping NULL chunks per the same drop-on-NULL
// discipline that <DataRow> applies at /coral/[slug] page-level lineage row.
//
// This is a string-shape helper — feeds into <DataRow> fields as a plain `value`
// (not a discriminated kind). The lineage row at /coral/[slug] (page-level, not
// per-card) constructs the DataRow.fields[] directly from named_corals columns
// with the drop-on-NULL rule applied at the caller; this helper handles the
// single-line per-card case where the field is one string.

interface NamedCoralLineageFields {
  origin_vendor: string | null;
  year_introduced: number | null;
  coral_type?: string | null;
}

export function formatLineage(named: NamedCoralLineageFields): string {
  const chunks: string[] = [];
  if (named.origin_vendor) {
    chunks.push(named.origin_vendor);
  }
  if (named.year_introduced !== null && named.year_introduced !== undefined) {
    chunks.push(String(named.year_introduced));
  }
  return chunks.join(' · ');
}
