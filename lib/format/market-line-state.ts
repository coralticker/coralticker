// lib/format/market-line-state.ts
//
// The current-availability STATE classifier for the per-coral market line
// (CTK-187 /code-review #1; the state-machine seed CTK-182's buildMarketLine
// folds in). Pure so it's testable in isolation — the bug it fixes was a render
// branch that printed ALL OUT OF STOCK without consulting the classification,
// so the state decision lives here once and both the test and the component
// read it.
//
// Four states, in priority order:
//   available        — a buyable price exists (in stock, current_price > 0) → promote it.
//   price-on-request — in stock but NO buyable price (in_stock=true, current_price=null —
//                      non-auction cut-to-order / event-drop). The coral IS available;
//                      it must NOT read as out of stock.
//   all-oos          — 0 in-stock vendors but in-window carriers exist (the carriers are
//                      all out of stock). Distinct from not-listed.
//   not-listed       — 0 in-stock vendors AND no in-window carriers → truly absent.
//                      Mirrors /coral/[slug]'s NOT LISTED vs ALL OUT OF STOCK split.
//
// The available vs price-on-request split is the load-bearing guard: both have
// inStockVendorCount >= 1, so a classifier that only looked at "is there a
// buyable price" would mislabel an in-stock price-on-request coral as OOS — the
// reachable Tier-1B path (JF event-drop / TSA cut-to-order, current_price=null
// on an in-stock non-auction row).
export type MarketLineState =
  | 'available'
  | 'price-on-request'
  | 'all-oos'
  | 'not-listed';

export function marketLineState({
  inStockVendorCount,
  isAllOOS,
  hasBuyablePrice,
}: {
  inStockVendorCount: number;
  isAllOOS: boolean;
  hasBuyablePrice: boolean;
}): MarketLineState {
  if (hasBuyablePrice) return 'available';
  if (inStockVendorCount > 0) return 'price-on-request';
  if (isAllOOS) return 'all-oos';
  return 'not-listed';
}
