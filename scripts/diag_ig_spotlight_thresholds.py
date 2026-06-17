"""CTK-159 A-path spotlight scoring follow-up — read-only threshold diagnostics.

Pulls the in-stock spotlight-candidate current_price distribution (for the
MIN_SPOTLIGHT_PRICE floor + its cut rate) and the absolute dollar-drop distribution
(for DOLLAR_FULL) from prod Neon so both are picked from real percentiles, not
guessed (Item B5). No value-reward term / no VALUE_FULL — the final directive dropped
it. Read-only; no writes. Canonical agent path (scrapers.common.db.get_conn).

  python -m scripts.diag_ig_spotlight_thresholds
"""

from __future__ import annotations

from scrapers.common.db import get_conn
from scrapers.tools.content_queries import drop_fraction


def _pct(sorted_vals, q):
    if not sorted_vals:
        return None
    i = min(len(sorted_vals) - 1, int(q * (len(sorted_vals) - 1) + 0.5))
    return sorted_vals[i]


def main() -> int:
    with get_conn() as conn:
        # The realistic spotlight-candidate pool: in-stock, priced, non-auction.
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT current_price
                FROM vendor_listings
                WHERE in_stock = true
                  AND current_price IS NOT NULL
                  AND auction_end_time IS NULL
                  AND is_auction = false
                """
            )
            prices = sorted(float(r["current_price"]) for r in cur.fetchall())

        print(f"=== in-stock priced non-auction candidate pool: n={len(prices)} ===")
        for q in (0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95):
            print(f"  p{int(q*100):>2} = ${_pct(prices, q):.2f}")
        print(f"  min=${prices[0]:.2f}  max=${prices[-1]:.2f}")

        print("\n=== price-floor cut rates (candidate pool) ===")
        for floor in (15, 20, 25, 30, 40, 50):
            cut = sum(1 for p in prices if p < floor)
            print(f"  floor ${floor:>3}: cuts {cut:>5} / {len(prices)} = {100*cut/len(prices):.1f}%")

        # Absolute dollar-drop distribution over the medal surface (30d window).
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM get_recent_price_drops(%s)", (30,))
            rows = cur.fetchall()
        dollars = []
        for r in rows:
            baseline = r.get("prior_price") if r.get("prior_price") is not None else r.get("compare_at_price")
            cur_p = r.get("current_price")
            if baseline is not None and cur_p is not None and float(baseline) > 0:
                dollars.append(float(baseline) - float(cur_p))
        dollars = sorted(d for d in dollars if d > 0)

        print(f"\n=== absolute dollar-drop over get_recent_price_drops(30): n={len(dollars)} ===")
        for q in (0.10, 0.25, 0.50, 0.75, 0.90, 0.95):
            v = _pct(dollars, q)
            print(f"  p{int(q*100):>2} = ${v:.2f}" if v is not None else f"  p{int(q*100):>2} = n/a")
        if dollars:
            print(f"  min=${dollars[0]:.2f}  max=${dollars[-1]:.2f}")

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
