// Shared USD price formatter for the DataRow field-builders (coral-reference-fields
// + price-summary-fields). Non-null contract by design: both callers pre-filter to
// buyable rows (inStock && currentPrice > 0) before formatting, so this never sees
// the auction null that lib/format/listing-price.ts handles ("price on request").
// Kept separate from that nullable formatter precisely so this surface stays a
// plain `$N.NN` with no fallthrough branch.
export function formatPrice(value: number): string {
  return `$${value.toFixed(2)}`;
}
