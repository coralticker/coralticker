// Max-timestamp accessor for eyebrow LATEST chunks. Reading index 0 relied on
// recency ordering; price-sorted feeds (/new, /deals) and the /coral/[slug]
// buy-intent ladder broke that assumption — LATEST must be max over the set
// regardless of render order.
//
// Lexical string max: every consumer feeds Postgres-serialized ISO-8601
// timestamps in one uniform format per source column, where lexicographic
// order equals chronological order. No Date allocation per row.

export function latestTimestamp<T>(
  items: readonly T[],
  accessor: (item: T) => string,
): string {
  let max = accessor(items[0]!);
  for (let i = 1; i < items.length; i++) {
    const v = accessor(items[i]!);
    if (v > max) max = v;
  }
  return max;
}
